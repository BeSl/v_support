import os
import uuid
import logging
import httpx
from qdrant_client import QdrantClient
from .db import save_message, get_full_context

class RAGProcessor:
    def __init__(self):
        self.logger = logging.getLogger("RAGService")
        self.logger.setLevel(logging.INFO)
        
        # Подключение к Qdrant
        self.qdrant_client = QdrantClient(
            url=os.getenv("QDRANT_URL", "http://qdrant:6333"),
            api_key=os.getenv("QDRANT_API_KEY")
        )
        self.collection_name = os.getenv("COLLECTION_NAME", "documents")
        
        # Конфигурация Ollama
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://ollama:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:latest")
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
        
        self.logger.info("RAG processor initialized")

    async def get_embedding(self, text: str) -> list[float]:
        """Получение эмбеддинга из Ollama"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.ollama_host}/api/embeddings",
                json={
                    "model": self.embedding_model,
                    "prompt": text
                },
                timeout=30.0
            )
            if response.status_code != 200:
                self.logger.error(f"Ollama embedding error: {response.text}")
                return []
            return response.json().get("embedding", [])

    def generate_prompt(self, query: str, context: str, history: str) -> str:
        return f"""
        Ты - ИИ-ассистент компании. Используй предоставленный контекст и историю диалога для ответа на вопрос.
        Если ответа нет в контексте, скажи, что не знаешь ответа.
        
        Контекст из документов:
        {context}
        
        История диалога:
        {history}
        
        Вопрос: {query}
        Ответ:
        """

    async def generate_response(self, prompt: str) -> str:
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                response = await client.post(
                    f"{self.ollama_host}/api/generate",
                    json={
                        "model": self.ollama_model,
                        "prompt": prompt,
                        "stream": False
                    }
                )
                response.raise_for_status()
                return response.json()["response"]
            except Exception as e:
                self.logger.error(f"Ollama error: {str(e)}")
                return "Произошла ошибка при генерации ответа"

    def search_context(self, query_embedding: list, top_k: int = 3) -> str:
        try:
            search_result = self.qdrant_client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                limit=top_k,
                with_payload=True
            )
            
            context = "\n\n".join(
                f"Источник {i+1}:\n{result.payload['text']}" 
                for i, result in enumerate(search_result)
            )
            return context
        except Exception as e:
            self.logger.error(f"Vector search error: {str(e)}")
            return ""

    async def process_query(self, query: str, session_id: uuid.UUID) -> dict:
        self.logger.info(f"Processing query: '{query}' for session {session_id}")
        
        # Сохраняем запрос пользователя
        save_message(session_id, "user", query)
        
        # Получаем историю диалога
        history = get_full_context(session_id)
        
        # Получаем эмбеддинг запроса
        query_embedding = await self.get_embedding(query)
        if not query_embedding:
            return {
                "query": query,
                "response": "Ошибка получения эмбеддинга",
                "session_id": str(session_id)
            }
        
        # Поиск релевантного контекста
        context = self.search_context(query_embedding)
        self.logger.debug(f"Retrieved context: {context[:200]}...")
        
        # Генерация промпта с историей
        prompt = self.generate_prompt(query, context, history)
        self.logger.debug(f"Generated prompt: {prompt[:500]}...")
        
        # Запрос к Ollama
        response = await self.generate_response(prompt)
        
        # Сохраняем ответ ассистента
        save_message(
            session_id, 
            "assistant", 
            response,
            context=context[:1000],
            sources=str(len(context.split("Источник"))))
        
        return {
            "query": query,
            "response": response,
            "session_id": str(session_id)
        }