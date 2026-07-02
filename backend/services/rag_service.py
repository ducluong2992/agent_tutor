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

class SmartEmbeddingFunction:
    """A smart embedding function that dynamically chooses between Gemini, OpenAI,
    and local ONNX (all-MiniLM-L6-v2) embeddings based on the current active LLM provider.
    """
    def __init__(self):
        self._local_emb = None
        self._last_config_key = None
        self._active_emb = None
        self._init_local_emb()

    @staticmethod
    def name() -> str:
        return "SmartEmbeddingFunction"

    def get_config(self) -> Dict[str, Any]:
        return {}

    @staticmethod
    def build_from_config(config: Dict[str, Any]) -> "SmartEmbeddingFunction":
        return SmartEmbeddingFunction()

    def embed_query(self, input: List[str]) -> List[List[float]]:
        return self.__call__(input)

    def _init_local_emb(self):
        try:
            from chromadb.utils import embedding_functions
            self._local_emb = embedding_functions.DefaultEmbeddingFunction()
            logger.info("Local ONNX Embedding Function (all-MiniLM-L6-v2) initialized.")
        except Exception as e:
            logger.warning(f"Could not initialize local ONNX embedding: {e}. Using dummy.")
            self._local_emb = SimpleDummyEmbeddingFunction()

    def __call__(self, input: List[str]) -> List[List[float]]:
        # Dynamically read active LLM config from environment
        provider = os.getenv("LLM_PROVIDER", "mock").lower()
        openai_key = os.getenv("OPENAI_API_KEY", "")
        gemini_key = os.getenv("GEMINI_API_KEY", "")

        config_key = (provider, bool(openai_key), bool(gemini_key))
        if config_key != self._last_config_key or self._active_emb is None:
            self._last_config_key = config_key
            self._active_emb = self._get_embedding_fn(provider, openai_key, gemini_key)

        try:
            return self._active_emb(input)
        except Exception as e:
            logger.error(f"Error generating embedding with {type(self._active_emb).__name__}: {e}. Falling back to local/dummy.")
            try:
                return self._local_emb(input)
            except Exception:
                return [[0.0] * 384 for _ in input]

    def _get_embedding_fn(self, provider: str, openai_key: str, gemini_key: str):
        try:
            from chromadb.utils import embedding_functions
        except ImportError:
            logger.warning("Could not import chromadb.utils.embedding_functions, falling back to local.")
            return self._local_emb

        if provider == "openai" and openai_key:
            try:
                logger.info("Initializing OpenAI Embedding Function (text-embedding-3-small)")
                return embedding_functions.OpenAIEmbeddingFunction(
                    api_key=openai_key,
                    model_name="text-embedding-3-small"
                )
            except Exception as e:
                logger.warning(f"Failed to init OpenAI embedding function: {e}")

        elif provider == "gemini" and gemini_key:
            try:
                logger.info("Initializing Gemini Embedding Function (text-embedding-004)")
                return embedding_functions.GoogleGenerativeAiEmbeddingFunction(
                    api_key=gemini_key,
                    model_name="models/text-embedding-004"
                )
            except Exception as e:
                logger.warning(f"Failed to init Gemini embedding function: {e}")

        logger.info("Using local ONNX Embedding Function (all-MiniLM-L6-v2)")
        return self._local_emb

class RAGService:
    def __init__(self, persist_directory: str = "backend/storage/chroma_db"):
        self.persist_directory = persist_directory
        self.client = None
        self.fallback_db = {}  # student_id -> list of chunks for memory fallback
        self.embedding_function = SmartEmbeddingFunction()
        
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
                embedding_function=self.embedding_function
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
                logger.error(f"Failed to add document to ChromaDB: {e}.")
                # If we get a dimension mismatch, delete the collection and retry
                if "match" in str(e).lower() or "dimension" in str(e).lower():
                    try:
                        self.client.delete_collection(f"student_{student_id}_docs")
                        logger.info(f"Deleted collection student_{student_id}_docs due to dimension mismatch. Retrying...")
                        collection = self.get_collection(student_id)
                        if collection:
                            collection.add(
                                documents=chunks,
                                ids=ids,
                                metadatas=metadatas
                            )
                            logger.info(f"Successfully re-added chunks after resetting collection.")
                            return
                    except Exception as retry_err:
                        logger.error(f"Retry add failed: {retry_err}")
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
                # If we get a dimension mismatch, delete the collection to heal it
                if "match" in str(e).lower() or "dimension" in str(e).lower():
                    try:
                        self.client.delete_collection(f"student_{student_id}_docs")
                        logger.info(f"Deleted collection student_{student_id}_docs due to dimension mismatch.")
                    except Exception as del_err:
                        logger.error(f"Failed to delete collection: {del_err}")
                
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

