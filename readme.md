Пересоберите сервис:
docker-compose build backend
Перезапустите сервис:
docker-compose up -d --no-deps backend
Проверьте результат:    
docker-compose logs -f backend

Кеширование моделей:
Для RAG добавьте в Dockerfile:
# Предзагрузка моделей
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

Размер образа:
Удаляйте кеш после установки:
RUN pip install --no-cache-dir -r requirements.txt && \
    rm -rf /root/.cache/pip

Многоступенчатые сборки (для production):
# Этап сборки
FROM python:3.10 as builder
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# Финальный образ
FROM python:3.10-slim
COPY --from=builder /wheels /wheels
RUN pip install --no-cache /wheels/*
COPY . .


9. Мониторинг задач
backend/app/main.py:
@app.get("/api/async-tasks")
async def list_async_tasks(
    status: str = None,
    user_id: str = None,
    limit: int = 100
):
    with get_db_cursor() as cursor:
        query = "SELECT task_id, status, created_at, username, user_id, question FROM async_tasks"
        conditions = []
        params = []
        
        if status:
            conditions.append("status = %s")
            params.append(status)
        
        if user_id:
            conditions.append("user_id = %s")
            params.append(user_id)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        
        cursor.execute(query, params)
        tasks = cursor.fetchall()
        
    return [
        {
            "task_id": str(task[0]),
            "status": task[1],
            "created_at": task[2].isoformat(),
            "username": task[3],
            "user_id": task[4],
            "question": task[5]
        }
        for task in tasks
    ]



    6. Пример использования API
1. Создание асинхронной задачи:

POST /api/async-query HTTP/1.1
Content-Type: application/x-www-form-urlencoded

username=JohnDoe&user_id=12345&question=Каковы основные преимущества вашего продукта?&session_id=5a9e8b7c-6d3f-4e2a-bb1c-9f8d7e6c5b4a

Ответ:
{
  "task_id": "c7b6d5e4-f3a2-4e1d-bc9a-8f7e6d5c4b3a",
  "session_id": "5a9e8b7c-6d3f-4e2a-bb1c-9f8d7e6c5b4a",
  "status": "pending",
  "created_at": "2023-10-25T12:34:56.789Z"
}

2. Проверка статуса задачи:
GET /api/async-result/c7b6d5e4-f3a2-4e1d-bc9a-8f7e6d5c4b3a HTTP/1.1

Ответ (в процессе):
{
  "task_id": "c7b6d5e4-f3a2-4e1d-bc9a-8f7e6d5c4b3a",
  "session_id": "5a9e8b7c-6d3f-4e2a-bb1c-9f8d7e6c5b4a",
  "created_at": "2023-10-25T12:34:56.789Z",
  "started_at": "2023-10-25T12:34:57.123Z",
  "completed_at": null,
  "status": "processing",
  "username": "JohnDoe",
  "user_id": "12345",
  "question": "Каковы основные преимущества вашего продукта?",
  "answer": null,
  "error": null
}

Ответ (завершено):

{
  "task_id": "c7b6d5e4-f3a2-4e1d-bc9a-8f7e6d5c4b3a",
  "session_id": "5a9e8b7c-6d3f-4e2a-bb1c-9f8d7e6c5b4a",
  "created_at": "2023-10-25T12:34:56.789Z",
  "started_at": "2023-10-25T12:34:57.123Z",
  "completed_at": "2023-10-25T12:35:02.456Z",
  "status": "completed",
  "username": "JohnDoe",
  "user_id": "12345",
  "question": "Каковы основные преимущества вашего продукта?",
  "answer": "Наш продукт имеет несколько ключевых преимуществ...",
  "error": null
}