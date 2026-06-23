import os
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

# Try to import chromadb
try:
    import chromadb
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False
    logger.warning("chromadb is not installed. RAG service will run in memory-fallback mode.")

class SimpleDummyEmbeddingFunction:
    """A simple dummy embedding function compatible with ChromaDB 1.5.x protocol."""
    
    def __init__(self):
        pass

    @staticmethod
    def name() -> str:
        return "SimpleDummyEmbeddingFunction"

    def __call__(self, input: List[str]) -> List[List[float]]:
        # Return a dummy vector of 384 dimensions for each text
        return [[0.0] * 384 for _ in input]

    def embed_query(self, input: List[str]) -> List[List[float]]:
        return self.__call__(input)

    @staticmethod
    def build_from_config(config: Dict[str, Any]) -> "SimpleDummyEmbeddingFunction":
        return SimpleDummyEmbeddingFunction()

    def get_config(self) -> Dict[str, Any]:
        return {}

class RAGService:
    def __init__(self, persist_directory: str = "backend/storage/chroma_db"):
        self.persist_directory = persist_directory
        self.client = None
        self.fallback_db = {}  # student_id -> list of chunks for memory fallback
        
        if CHROMA_AVAILABLE:
            try:
                os.makedirs(persist_directory, exist_ok=True)
                self.client = chromadb.PersistentClient(path=persist_directory)
                logger.info("ChromaDB initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize ChromaDB: {e}. Falling back to memory-based RAG.")
                self.client = None

    def get_collection(self, student_id: int):
        if not self.client:
            return None
        collection_name = f"student_{student_id}_docs"
        try:
            return self.client.get_or_create_collection(
                name=collection_name,
                embedding_function=SimpleDummyEmbeddingFunction()
            )
        except Exception as e:
            logger.error(f"Failed to get or create collection: {e}")
            return None

    def add_document(self, student_id: int, document_id: int, filename: str, content: str):
        # Text chunker
        chunks = self._chunk_text(content, chunk_size=500, chunk_overlap=100)
        
        if not chunks:
            return
            
        collection = self.get_collection(student_id)
        if collection:
            try:
                ids = [f"doc_{document_id}_chunk_{i}" for i in range(len(chunks))]
                metadatas = [{"document_id": document_id, "filename": filename} for _ in range(len(chunks))]
                collection.add(
                    documents=chunks,
                    ids=ids,
                    metadatas=metadatas
                )
                logger.info(f"Added {len(chunks)} chunks to ChromaDB for document {filename}.")
            except Exception as e:
                logger.error(f"Failed to add document to ChromaDB: {e}. Saving to fallback DB.")
                self._add_to_fallback(student_id, document_id, filename, chunks)
        else:
            self._add_to_fallback(student_id, document_id, filename, chunks)

    def _add_to_fallback(self, student_id: int, document_id: int, filename: str, chunks: List[str]):
        if student_id not in self.fallback_db:
            self.fallback_db[student_id] = []
        for i, chunk in enumerate(chunks):
            self.fallback_db[student_id].append({
                "id": f"doc_{document_id}_chunk_{i}",
                "document_id": document_id,
                "filename": filename,
                "content": chunk
            })
        logger.info(f"Added {len(chunks)} chunks to memory-fallback RAG for document {filename}.")

    def query_documents(self, student_id: int, query: str, limit: int = 4) -> List[Dict[str, Any]]:
        collection = self.get_collection(student_id)
        results = []
        if collection:
            try:
                query_results = collection.query(
                    query_texts=[query],
                    n_results=limit
                )
                if query_results and 'documents' in query_results and query_results['documents']:
                    docs = query_results['documents'][0]
                    metadatas = query_results['metadatas'][0] if 'metadatas' in query_results else [{}] * len(docs)
                    for doc, meta in zip(docs, metadatas):
                        results.append({
                            "content": doc,
                            "filename": meta.get("filename", "unknown"),
                            "document_id": meta.get("document_id", None)
                        })
            except Exception as e:
                logger.error(f"ChromaDB query failed: {e}. Falling back to memory search.")
                
        # If no results and fallback_db has contents, search there
        if not results and student_id in self.fallback_db:
            # Simple keyword matching for fallback
            chunks = self.fallback_db[student_id]
            words = query.lower().split()
            scored_chunks = []
            for c in chunks:
                score = sum(1 for w in words if w in c["content"].lower())
                if score > 0:
                    scored_chunks.append((score, c))
            scored_chunks.sort(key=lambda x: x[0], reverse=True)
            for _, c in scored_chunks[:limit]:
                results.append({
                    "content": c["content"],
                    "filename": c["filename"],
                    "document_id": c["document_id"]
                })
                
        return results

    def _chunk_text(self, text: str, chunk_size: int = 500, chunk_overlap: int = 100) -> List[str]:
        words = text.split()
        chunks = []
        for i in range(0, len(words), chunk_size - chunk_overlap):
            chunk = " ".join(words[i:i + chunk_size])
            if chunk:
                chunks.append(chunk)
            if i + chunk_size >= len(words):
                break
        return chunks

    def clear_student_documents(self, student_id: int):
        """Remove all RAG data (ChromaDB collection + fallback) for a student."""
        # Clear ChromaDB collection
        if self.client:
            collection_name = f"student_{student_id}_docs"
            try:
                self.client.delete_collection(collection_name)
                logger.info(f"Deleted ChromaDB collection for student {student_id}.")
            except Exception as e:
                logger.warning(f"Could not delete ChromaDB collection for student {student_id}: {e}")
        
        # Clear in-memory fallback
        if student_id in self.fallback_db:
            del self.fallback_db[student_id]
            logger.info(f"Cleared fallback RAG for student {student_id}.")

