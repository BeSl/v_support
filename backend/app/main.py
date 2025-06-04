import os
import uuid
import logging
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from app.rag import RAGProcessor
from app.db import create_tables, create_session, get_session_history
from .tasks import task_worker
import asyncio

# Создаем директорию для логов, если ее нет
log_dir = Path("/app/logs")
log_dir.mkdir(parents=True, exist_ok=True)

# Настройка логирования
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/app/logs/backend.log")
    ]
)

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



@app.on_event("startup")
async def startup_event():
    create_tables()
    logger.info("Database tables initialized")

    # Запускаем воркер асинхронных задач в фоне
    asyncio.create_task(task_worker())

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    with open("app/static/index.html") as f:
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
        logging.error(f"Query processing error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
    
# Асинхронный API
@app.post("/api/async-query")
async def create_async_query(
    request: Request,
    username: str = Form(...),
    user_id: str = Form(...),
    question: str = Form(...),
    session_id: uuid.UUID = Form(None)
):
    # Создаем новую сессию, если не предоставлена
    if not session_id:
        session_id = create_session(
            user_agent=request.headers.get("User-Agent", ""),
            ip_address=request.client.host if request.client else ""
        )
    
    # Создаем асинхронную задачу
    task_id = create_async_task(session_id, username, user_id, question)
    
    logger.info(f"Created async task: {task_id} for user: {user_id}")
    
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
    task["created_at"] = task["created_at"].isoformat() if task["created_at"] else None
    task["started_at"] = task["started_at"].isoformat() if task["started_at"] else None
    task["completed_at"] = task["completed_at"].isoformat() if task["completed_at"] else None
    
    return JSONResponse(content=task)