import os
import logging
import shutil
import hashlib
import time
import requests
import json
from datetime import datetime
from qdrant_client import QdrantClient
from qdrant_client.http import models
from PyPDF2 import PdfReader
import docx
import markdown
import psycopg2
from psycopg2 import sql

# Конфигурация
SOURCE_DIR = "/app/source"
PROCESSED_DIR = "/app/processed"
LOG_DIR = "/app/logs"
SUPPORTED_EXT = ['.txt', '.pdf', '.docx', '.md']
CHUNK_SIZE = 512

# Конфигурация PostgreSQL
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_DB = os.getenv("POSTGRES_DB", "ragdb")
POSTGRES_USER = os.getenv("POSTGRES_USER", "raguser")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "ragpassword")

# Конфигурация Ollama
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")

def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, f"loader_{datetime.now().strftime('%Y%m%d')}.log")
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    return logging.getLogger()

def wait_for_service(url, service_name):
    logger = logging.getLogger()
    while True:
        try:
            response = requests.get(url)
            if response.status_code == 200:
                logger.info(f"{service_name} is ready!")
                return
        except Exception:
            pass
        logger.info(f"Waiting for {service_name} to start...")
        time.sleep(5)

def init_qdrant():
    client = QdrantClient(
        url=os.getenv("QDRANT_URL", "http://qdrant:6333"),
        api_key=os.getenv("QDRANT_API_KEY")
    )
    
    collection_name = os.getenv("COLLECTION_NAME", "documents")
    
    try:
        if not client.collection_exists(collection_name):
            # Получаем размерность эмбеддингов
            embedding_size = get_embedding_size()
            if not embedding_size:
                raise ValueError("Failed to get embedding dimension")
                
            client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=embedding_size,
                    distance=models.Distance.COSINE
                )
            )
            logger.info(f"Created collection: {collection_name} with dim={embedding_size}")
    except Exception as e:
        logger.error(f"Qdrant connection error: {str(e)}")
        raise
    
    return client, collection_name

def get_embedding_size():
    """Получаем размерность эмбеддингов из Ollama"""
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/tags")
        models = response.json().get("models", [])
        for model in models:
            if model["name"] == EMBEDDING_MODEL:
                return model["details"]["embedding_size"]
        
        # Если не нашли модель, попробуем получить через тестовый запрос
        test_response = requests.post(
            f"{OLLAMA_HOST}/api/embeddings",
            json={"model": EMBEDDING_MODEL, "prompt": "test"}
        )
        if test_response.status_code == 200:
            return len(test_response.json().get("embedding", []))
            
        logger.error(f"Embedding model {EMBEDDING_MODEL} not found")
        return 768  # Значение по умолчанию
    except Exception as e:
        logger.error(f"Error getting embedding size: {str(e)}")
        return 768  # Значение по умолчанию

def get_embedding(text: str) -> list:
    """Получение эмбеддинга из Ollama"""
    try:
        response = requests.post(
            f"{OLLAMA_HOST}/api/embeddings",
            json={
                "model": EMBEDDING_MODEL,
                "prompt": text
            },
            timeout=30.0
        )
        if response.status_code != 200:
            logger.error(f"Ollama embedding error: {response.text}")
            return []
        return response.json().get("embedding", [])
    except Exception as e:
        logger.error(f"Embedding request failed: {str(e)}")
        return []

def extract_text(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == '.pdf':
            reader = PdfReader(file_path)
            return " ".join(page.extract_text() for page in reader.pages)
        elif ext == '.docx':
            doc = docx.Document(file_path)
            return " ".join(para.text for para in doc.paragraphs)
        elif ext == '.md':
            with open(file_path, 'r') as f:
                return markdown.markdown(f.read())
        else:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
    except Exception as e:
        logger.error(f"Error reading {file_path}: {str(e)}")
        return None

def chunk_text(text):
    if not text:
        return []
    
    chunks = []
    words = text.split()
    current_chunk = []
    char_count = 0
    
    for word in words:
        if char_count + len(word) + len(current_chunk) > CHUNK_SIZE:
            chunks.append(" ".join(current_chunk))
            current_chunk = []
            char_count = 0
        
        current_chunk.append(word)
        char_count += len(word)
    
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    
    return chunks

def save_processing_stats(processed_files: int, processed_vectors: int, errors: int):
    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD
        )
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO processing_stats (processed_files, processed_vectors, errors) VALUES (%s, %s, %s)",
            (processed_files, processed_vectors, errors)
        )
        conn.commit()
        logger.info(f"Saved stats: files={processed_files}, vectors={processed_vectors}, errors={errors}")
    except Exception as e:
        logger.error(f"Error saving stats: {str(e)}")
    finally:
        if conn:
            conn.close()

def process_files(qdrant_client, collection_name):
    processed_files = []
    total_vectors = 0
    error_count = 0
    
    for file_name in os.listdir(SOURCE_DIR):
        file_path = os.path.join(SOURCE_DIR, file_name)
        if not os.path.isfile(file_path):
            continue
        
        ext = os.path.splitext(file_name)[1].lower()
        if ext not in SUPPORTED_EXT:
            logger.warning(f"Unsupported format: {file_name}")
            continue
        
        logger.info(f"Processing: {file_name}")
        text = extract_text(file_path)
        if not text:
            error_count += 1
            continue
        
        chunks = chunk_text(text)
        logger.info(f"Created {len(chunks)} chunks")
        
        if not chunks:
            error_count += 1
            continue
        
        # Получаем эмбеддинги для всех чанков
        embeddings = []
        for chunk in chunks:
            embedding = get_embedding(chunk)
            if embedding:
                embeddings.append(embedding)
            else:
                logger.warning(f"Failed to get embedding for chunk: {chunk[:50]}...")
        
        if not embeddings:
            logger.error(f"No embeddings generated for {file_name}")
            error_count += 1
            continue
        
        # Подготовка точек для Qdrant
        points = []
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            points.append(models.PointStruct(
                id=hashlib.md5(f"{file_name}_{idx}".encode()).hexdigest(),
                vector=embedding,
                payload={
                    "filename": file_name,
                    "chunk_index": idx,
                    "text": chunk,
                    "processed": datetime.now().isoformat()
                }
            ))
        
        try:
            # Загрузка в Qdrant
            qdrant_client.upsert(
                collection_name=collection_name,
                points=points,
                wait=True
            )
            logger.info(f"Uploaded {len(points)} vectors")
            
            # Перемещаем обработанный файл
            new_path = os.path.join(PROCESSED_DIR, file_name)
            shutil.move(file_path, new_path)
            processed_files.append(file_name)
            total_vectors += len(points)
        except Exception as e:
            logger.error(f"Upload error: {str(e)}")
            error_count += 1
    
    # Сохраняем статистику
    if processed_files or error_count:
        save_processing_stats(len(processed_files), total_vectors, error_count)
    
    return processed_files

def main():
    global logger
    logger = setup_logging()
    
    os.makedirs(SOURCE_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    
    logger.info("===== Document loader started =====")
    
    # Ожидаем доступности сервисов
    wait_for_service(f"{OLLAMA_HOST}/api/tags", "Ollama")
    wait_for_service(f"{os.getenv('QDRANT_URL', 'http://qdrant:6333')}/readyz", "Qdrant")
    
    qdrant_client, collection_name = init_qdrant()
    
    while True:
        logger.info("Starting scan cycle...")
        processed = process_files(qdrant_client, collection_name)
        if processed:
            logger.info(f"Processed files: {', '.join(processed)}")
        time.sleep(60)

if __name__ == "__main__":
    main()