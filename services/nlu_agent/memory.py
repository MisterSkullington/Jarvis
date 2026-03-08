"""
Persistent conversation and knowledge memory backed by ChromaDB.

Two collections:
  - conversations: per-session chat turns for multi-turn context and semantic recall
  - knowledge:     user documents ingested from the configured documents_path
"""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG = logging.getLogger(__name__)

# Chunk parameters for document ingestion
_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 50


def _chunk_text(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping chunks."""
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start += size - overlap
    return [c.strip() for c in chunks if c.strip()]


def _file_hash(path: Path) -> str:
    """MD5 of a file — used to skip already-ingested unchanged files."""
    h = hashlib.md5()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


class _SentenceTransformerEF:
    """Minimal ChromaDB EmbeddingFunction wrapping sentence-transformers.

    Compatible with ChromaDB >=1.x which calls ef.name() as a method.
    """

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer
        self._model_name = model_name
        self._model = SentenceTransformer(model_name)

    def __call__(self, input: List[str]) -> List[List[float]]:  # noqa: A002
        return self._model.encode(input, convert_to_numpy=True).tolist()

    # ChromaDB 1.x calls name() as a callable method
    def name(self) -> str:  # type: ignore[override]
        return f"sentence-transformers/{self._model_name}"

    def get_config(self) -> dict:
        return {"model_name": self._model_name}

    @classmethod
    def build_from_config(cls, config: dict) -> "_SentenceTransformerEF":
        return cls(config.get("model_name", "all-MiniLM-L6-v2"))


class JarvisMemory:
    """
    Persistent conversation + knowledge memory.

    Usage::

        mem = JarvisMemory(config.memory)
        mem.add_turn(session_id, "user", "What's the weather?")
        mem.add_turn(session_id, "assistant", "Sunny, 20°C, Sir.")
        context = mem.build_context("tell me about today", session_id)
    """

    def __init__(self, config: Any) -> None:
        """
        Initialise ChromaDB persistent client and ensure collections exist.

        config is a MemoryConfig dataclass with fields:
          chroma_path, conversation_collection, knowledge_collection,
          embedding_model, top_k, max_conversation_turns, documents_path
        """
        import chromadb

        self._cfg = config
        self._client = chromadb.PersistentClient(path=str(config.chroma_path))

        # Shared embedding function
        try:
            self._ef = _SentenceTransformerEF(config.embedding_model)
            LOG.info("Loaded embedding model: %s", config.embedding_model)
        except Exception as exc:
            LOG.warning("sentence-transformers unavailable (%s); using Chroma default embeddings.", exc)
            self._ef = None  # type: ignore[assignment]

        ef_kwargs: Dict[str, Any] = {"embedding_function": self._ef} if self._ef else {}

        self._conv = self._client.get_or_create_collection(
            name=config.conversation_collection,
            **ef_kwargs,
        )
        self._know = self._client.get_or_create_collection(
            name=config.knowledge_collection,
            **ef_kwargs,
        )

    # ------------------------------------------------------------------
    # Conversation turns
    # ------------------------------------------------------------------

    def add_turn(self, session_id: str, role: str, content: str) -> None:
        """Store a single conversation turn."""
        if not content or not content.strip():
            return
        ts = time.time()
        doc_id = f"{session_id}_{role}_{int(ts * 1000)}"
        self._conv.add(
            ids=[doc_id],
            documents=[content],
            metadatas=[{"session_id": session_id, "role": role, "timestamp": ts}],
        )

    def get_recent_turns(self, session_id: str, limit: int = 10) -> List[Dict[str, str]]:
        """
        Return the last *limit* turns for *session_id*, ordered oldest-first.
        Each dict has keys: role, content.
        """
        try:
            results = self._conv.get(
                where={"session_id": session_id},
                include=["documents", "metadatas"],
            )
        except Exception as exc:
            LOG.warning("get_recent_turns failed: %s", exc)
            return []

        docs = results.get("documents") or []
        metas = results.get("metadatas") or []
        if not docs:
            return []

        pairs = sorted(zip(metas, docs), key=lambda x: x[0].get("timestamp", 0))
        recent = pairs[-limit:]
        return [{"role": m.get("role", "user"), "content": d} for m, d in recent]

    # ------------------------------------------------------------------
    # Knowledge retrieval
    # ------------------------------------------------------------------

    def query_knowledge(self, query: str, top_k: Optional[int] = None) -> List[str]:
        """Semantic search over ingested documents. Returns top_k text chunks."""
        k = top_k if top_k is not None else self._cfg.top_k
        try:
            results = self._know.query(
                query_texts=[query],
                n_results=min(k, max(self._know.count(), 1)),
                include=["documents"],
            )
            docs: List[str] = (results.get("documents") or [[]])[0]
            return docs
        except Exception as exc:
            LOG.warning("query_knowledge failed: %s", exc)
            return []

    def query_conversations(
        self,
        query: str,
        session_id: Optional[str] = None,
        top_k: int = 3,
    ) -> List[str]:
        """Semantic search over past conversation turns, optionally filtered by session."""
        where = {"session_id": session_id} if session_id else None
        try:
            kwargs: Dict[str, Any] = {
                "query_texts": [query],
                "n_results": min(top_k, max(self._conv.count(), 1)),
                "include": ["documents"],
            }
            if where:
                kwargs["where"] = where
            results = self._conv.query(**kwargs)
            return (results.get("documents") or [[]])[0]
        except Exception as exc:
            LOG.warning("query_conversations failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Context builder (for LLM prompt injection)
    # ------------------------------------------------------------------

    def build_context(self, query: str, session_id: str) -> str:
        """
        Combine recent turns + knowledge hits into a concise context block.

        Returns an empty string when there is nothing useful to inject.
        """
        parts: List[str] = []

        recent = self.get_recent_turns(session_id, limit=6)
        if recent:
            lines = [f"  [{t['role'].upper()}] {t['content']}" for t in recent]
            parts.append("[Recent conversation]\n" + "\n".join(lines))

        knowledge = self.query_knowledge(query)
        if knowledge:
            parts.append("[Relevant knowledge]\n" + "\n---\n".join(knowledge))

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Document ingestion
    # ------------------------------------------------------------------

    def ingest_documents(self, path: Optional[str] = None) -> int:
        """
        Walk *path* (or config.documents_path) and ingest .txt and .md files
        into the knowledge collection.

        Files whose content hash is already stored are skipped.
        Returns the number of new chunks added.
        """
        doc_path = Path(path or self._cfg.documents_path)
        if not doc_path.exists():
            LOG.debug("Documents path does not exist, skipping ingestion: %s", doc_path)
            return 0

        # Fetch hashes of already-ingested files to avoid re-ingesting
        try:
            existing_meta = self._know.get(include=["metadatas"]).get("metadatas") or []
            known_hashes = {m.get("file_hash") for m in existing_meta if m.get("file_hash")}
        except Exception:
            known_hashes = set()

        total_chunks = 0
        for file in doc_path.rglob("*"):
            if file.suffix.lower() not in {".txt", ".md"}:
                continue
            try:
                fhash = _file_hash(file)
                if fhash in known_hashes:
                    continue  # already ingested

                text = file.read_text(encoding="utf-8", errors="ignore").strip()
                if not text:
                    continue

                chunks = _chunk_text(text)
                ids = [f"{fhash}_{i}" for i in range(len(chunks))]
                metadatas = [
                    {"source": str(file), "file_hash": fhash, "chunk": i}
                    for i in range(len(chunks))
                ]
                self._know.add(ids=ids, documents=chunks, metadatas=metadatas)
                total_chunks += len(chunks)
                LOG.info("Ingested %d chunks from %s", len(chunks), file.name)
            except Exception as exc:
                LOG.warning("Failed to ingest %s: %s", file, exc)

        return total_chunks
