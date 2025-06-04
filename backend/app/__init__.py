"""
RAG Service Application Package

Этот пакет содержит основную логику веб-сервиса для обработки запросов с использованием RAG.
"""

from .db import (
    create_tables,
    create_session,
    save_message,
    get_session_history,
    get_full_context,
    create_async_task,
    get_async_task,
    update_task_status
)

from .rag import RAGProcessor
from .tasks import task_worker

# Экспорт основных компонентов для удобного доступа
__all__ = [
    'create_tables',
    'create_session',
    'save_message',
    'get_session_history',
    'get_full_context',
    'create_async_task',
    'get_async_task',
    'update_task_status',
    'RAGProcessor',
    'task_worker'
]

# Инициализация логгера
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)
logger.info("RAG application package initialized")