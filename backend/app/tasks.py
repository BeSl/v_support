import asyncio
import uuid
import logging
from .db import update_task_status
from .rag import RAGProcessor

logger = logging.getLogger("AsyncTasks")
rag = RAGProcessor()

async def process_async_task(task_id: uuid.UUID):
    # Обновляем статус задачи на "в обработке"
    update_task_status(task_id, 'processing')
    
    try:
        # Получаем данные задачи
        task = get_async_task(task_id)
        if not task:
            logger.error(f"Task not found: {task_id}")
            return
        
        question = task['question']
        session_id = task['session_id']
        
        # Обрабатываем запрос
        result = await rag.process_query(question, session_id)
        
        # Обновляем статус задачи на "завершено"
        update_task_status(
            task_id, 
            'completed', 
            answer=result['response']
        )
        
        logger.info(f"Task completed: {task_id}")
        
    except Exception as e:
        logger.error(f"Task failed: {task_id}, error: {str(e)}")
        update_task_status(
            task_id, 
            'failed', 
            error=str(e)
        )

async def task_worker():
    logger.info("Async task worker started")
    while True:
        try:
            # Получаем следующую задачу из очереди
            task = get_next_pending_task()
            if task:
                task_id = task['task_id']
                logger.info(f"Processing task: {task_id}")
                await process_async_task(task_id)
            else:
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Task worker error: {str(e)}")
            await asyncio.sleep(5)

def get_next_pending_task():
    with get_db_cursor() as cursor:
        cursor.execute(
            """
            SELECT task_id 
            FROM async_tasks 
            WHERE status = 'pending' 
            ORDER BY created_at 
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        )
        task = cursor.fetchone()
        return {'task_id': task[0]} if task else None