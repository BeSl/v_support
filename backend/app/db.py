import os
import uuid
import psycopg2
from psycopg2 import sql
from datetime import datetime
from contextlib import contextmanager

# Конфигурация PostgreSQL
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_DB = os.getenv("POSTGRES_DB", "ragdb")
POSTGRES_USER = os.getenv("POSTGRES_USER", "raguser")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "ragpassword")

@contextmanager
def get_db_connection():
    conn = psycopg2.connect(
        host=POSTGRES_HOST,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD
    )
    try:
        yield conn
    finally:
        conn.close()

@contextmanager
def get_db_cursor():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        finally:
            cursor.close()

def create_tables():
    with get_db_cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id UUID PRIMARY KEY,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                user_agent TEXT,
                ip_address TEXT
            );
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id SERIAL PRIMARY KEY,
                session_id UUID REFERENCES sessions(session_id) ON DELETE CASCADE,
                timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                role VARCHAR(10) NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                context TEXT,
                sources TEXT
            );
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processing_stats (
                stat_id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                processed_files INTEGER NOT NULL,
                processed_vectors INTEGER NOT NULL,
                errors INTEGER NOT NULL
            );
        """)

def create_session(user_agent: str, ip_address: str) -> uuid.UUID:
    session_id = uuid.uuid4()
    with get_db_cursor() as cursor:
        cursor.execute(
            "INSERT INTO sessions (session_id, user_agent, ip_address) VALUES (%s, %s, %s)",
            (session_id, user_agent, ip_address)
        )
    return session_id

def save_message(session_id: uuid.UUID, role: str, content: str, context: str = None, sources: str = None):
    with get_db_cursor() as cursor:
        cursor.execute(
            "INSERT INTO messages (session_id, role, content, context, sources) VALUES (%s, %s, %s, %s, %s)",
            (session_id, role, content, context, sources)
        )
        
        # Обновляем время последней активности сессии
        cursor.execute(
            "UPDATE sessions SET last_activity = CURRENT_TIMESTAMP WHERE session_id = %s",
            (session_id,)
        )

def get_session_history(session_id: uuid.UUID, limit: int = 10) -> list:
    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT role, content, timestamp FROM messages WHERE session_id = %s ORDER BY timestamp DESC LIMIT %s",
            (session_id, limit)
        )
        return cursor.fetchall()

def get_full_context(session_id: uuid.UUID) -> str:
    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT role, content FROM messages WHERE session_id = %s ORDER BY timestamp",
            (session_id,)
        )
        history = cursor.fetchall()
        
    context = []
    for role, content in history:
        context.append(f"{role.capitalize()}: {content}")
    
    return "\n\n".join(context)

def create_async_task(session_id: uuid.UUID, username: str, user_id: str, question: str) -> uuid.UUID:
    task_id = uuid.uuid4()
    with get_db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO async_tasks (task_id, session_id, username, user_id, question, status)
            VALUES (%s, %s, %s, %s, %s, 'pending')
            """,
            (task_id, session_id, username, user_id, question)
        )
    return task_id

def get_async_task(task_id: uuid.UUID) -> dict:
    with get_db_cursor() as cursor:
        cursor.execute(
            """
            SELECT task_id, session_id, created_at, started_at, completed_at, status, 
                   username, user_id, question, answer, error
            FROM async_tasks
            WHERE task_id = %s
            """,
            (task_id,)
        )
        task = cursor.fetchone()
        if not task:
            return None
        
        return {
            "task_id": task[0],
            "session_id": task[1],
            "created_at": task[2],
            "started_at": task[3],
            "completed_at": task[4],
            "status": task[5],
            "username": task[6],
            "user_id": task[7],
            "question": task[8],
            "answer": task[9],
            "error": task[10]
        }

def update_task_status(task_id: uuid.UUID, status: str, answer: str = None, error: str = None):
    update_fields = []
    params = []
    
    update_fields.append("status = %s")
    params.append(status)
    
    if status == 'processing':
        update_fields.append("started_at = CURRENT_TIMESTAMP")
    elif status == 'completed':
        update_fields.append("completed_at = CURRENT_TIMESTAMP")
        update_fields.append("answer = %s")
        params.append(answer)
    elif status == 'failed':
        update_fields.append("completed_at = CURRENT_TIMESTAMP")
        update_fields.append("error = %s")
        params.append(error)
    
    with get_db_cursor() as cursor:
        query = sql.SQL("UPDATE async_tasks SET {} WHERE task_id = %s").format(
            sql.SQL(', ').join(map(sql.SQL, update_fields))
        )
        params.append(task_id)
        cursor.execute(query, params)