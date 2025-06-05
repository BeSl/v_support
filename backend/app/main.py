import os
import uuid
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException, Form # type: ignore
from fastapi.middleware.cors import CORSMiddleware # type: ignore
from fastapi.staticfiles import StaticFiles # type: ignore
from fastapi.responses import HTMLResponse, JSONResponse # type: ignore

# Локальные импорты
from app.db import (
    create_tables,
    create_session,
    get_session_history,
    create_async_task,
    get_async_task
)
from app.rag import RAGProcessor
from app.tasks import task_worker

# Создаем директорию для логов, если ее нет
log_dir = Path("/app/logs")
log_dir.mkdir(parents=True, exist_ok=True)

# Настройка логирования (один раз)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/app/logs/backend.log")
    ]
)
logger = logging.getLogger(__name__)
logger.info("RAG application package initialized")

app = FastAPI()
rag = RAGProcessor()

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Получаем абсолютный путь к директории со статическими файлами
current_dir = Path(__file__).parent
static_dir = current_dir / "static"

# Проверяем существование директории
if not static_dir.exists():
    logger.error(f"Static directory not found: {static_dir}")
    raise RuntimeError(f"Static directory not found: {static_dir}")

# Mount static files
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.on_event("startup")
async def startup_event():
    create_tables()
    logger.info("Database tables initialized")
    
    # Запускаем воркер асинхронных задач в фоне
    asyncio.create_task(task_worker())

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    # Используем правильный путь к файлу
    index_path = static_dir / "index.html"
    if not index_path.exists():
        logger.error(f"index.html not found at {index_path}")
        raise HTTPException(status_code=404, detail="Home page not found")
    
    with open(index_path, "r") as f:
        return HTMLResponse(content=f.read(), status_code=200)

@app.post("/api/session")
async def create_new_session(request: Request):
    session_id = create_session(
        user_agent=request.headers.get("User-Agent", ""),
        ip_address=request.client.host if request.client else ""
    )
    return {"session_id": str(session_id)}

@app.get("/api/history/{session_id}")
async def get_history(session_id: uuid.UUID):
    history = get_session_history(session_id)
    return [
        {"role": role, "content": content, "timestamp": timestamp.isoformat()}
        for role, content, timestamp in history
    ]

@app.get("/api/query")
async def query_endpoint(q: str, session_id: uuid.UUID):
    if not q or len(q) < 3:
        raise HTTPException(status_code=400, detail="Query too short")
    
    try:
        result = await rag.process_query(q, session_id)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Query processing error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

# Изменяем API на JSON вместо Form
from pydantic import BaseModel

class AsyncQueryRequest(BaseModel):
    username: str
    user_id: str
    question: str
    session_id: uuid.UUID = None # type: ignore

@app.post("/api/async-query")
async def create_async_query(
    request: Request,
    data: AsyncQueryRequest
):
    # Создаем новую сессию, если не предоставлена
    if not data.session_id:
        session_id = create_session(
            user_agent=request.headers.get("User-Agent", ""),
            ip_address=request.client.host if request.client else ""
        )
    else:
        session_id = data.session_id
    
    # Создаем асинхронную задачу
    task_id = create_async_task(session_id, data.username, data.user_id, data.question)
    
    logger.info(f"Created async task: {task_id} for user: {data.user_id}")
    
    return {
        "task_id": str(task_id),
        "session_id": str(session_id),
        "status": "pending",
        "created_at": datetime.utcnow().isoformat()
    }

@app.get("/api/async-result/{task_id}")
async def get_async_result(task_id: uuid.UUID):
    task = get_async_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Преобразуем временные метки в строки
    if task["created_at"]:
        task["created_at"] = task["created_at"].isoformat()
    if task["started_at"]:
        task["started_at"] = task["started_at"].isoformat()
    if task["completed_at"]:
        task["completed_at"] = task["completed_at"].isoformat()
    
    return JSONResponse(content=task)

