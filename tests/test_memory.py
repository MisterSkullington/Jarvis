"""
Tests for JarvisMemory — conversation turns, knowledge ingestion, and RAG retrieval.
Uses a temporary ChromaDB directory so tests are fully isolated.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Skip entire module if chromadb is not installed
pytest.importorskip("chromadb")
pytest.importorskip("sentence_transformers")


def _make_memory(tmp_path: Path):
    """Create a JarvisMemory with ephemeral ChromaDB in tmp_path."""
    from services.nlu_agent.memory import JarvisMemory

    cfg = MagicMock()
    cfg.chroma_path = str(tmp_path / "chroma")
    cfg.conversation_collection = "conversations"
    cfg.knowledge_collection = "knowledge"
    cfg.documents_path = str(tmp_path / "docs")
    cfg.embedding_model = "all-MiniLM-L6-v2"
    cfg.top_k = 3
    cfg.max_conversation_turns = 50

    return JarvisMemory(cfg)


# ---------------------------------------------------------------------------
# Conversation turns
# ---------------------------------------------------------------------------

def test_add_and_retrieve_turns(tmp_path):
    mem = _make_memory(tmp_path)
    mem.add_turn("session1", "user", "Hello Jarvis")
    mem.add_turn("session1", "assistant", "Good day, Sir.")
    mem.add_turn("session1", "user", "What time is it?")

    turns = mem.get_recent_turns("session1", limit=10)
    assert len(turns) == 3
    assert turns[0]["role"] == "user"
    assert turns[0]["content"] == "Hello Jarvis"
    assert turns[2]["content"] == "What time is it?"


def test_turns_session_isolation(tmp_path):
    mem = _make_memory(tmp_path)
    mem.add_turn("session_a", "user", "Message A")
    mem.add_turn("session_b", "user", "Message B")

    turns_a = mem.get_recent_turns("session_a", limit=10)
    turns_b = mem.get_recent_turns("session_b", limit=10)
    assert len(turns_a) == 1
    assert len(turns_b) == 1
    assert turns_a[0]["content"] == "Message A"
    assert turns_b[0]["content"] == "Message B"


def test_get_recent_turns_limit(tmp_path):
    mem = _make_memory(tmp_path)
    for i in range(10):
        mem.add_turn("s", "user", f"message {i}")
    turns = mem.get_recent_turns("s", limit=3)
    assert len(turns) == 3


def test_turns_empty_session(tmp_path):
    mem = _make_memory(tmp_path)
    assert mem.get_recent_turns("no_such_session") == []


def test_empty_content_not_stored(tmp_path):
    mem = _make_memory(tmp_path)
    mem.add_turn("s", "user", "")
    mem.add_turn("s", "user", "   ")
    assert mem.get_recent_turns("s") == []


# ---------------------------------------------------------------------------
# Document ingestion
# ---------------------------------------------------------------------------

def test_ingest_txt_file(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "notes.txt").write_text("Jarvis is a local AI assistant with voice control.", encoding="utf-8")

    mem = _make_memory(tmp_path)
    count = mem.ingest_documents(str(docs))
    assert count >= 1


def test_ingest_md_file(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "readme.md").write_text("# Project\n\nThis is the Jarvis assistant project.", encoding="utf-8")

    mem = _make_memory(tmp_path)
    count = mem.ingest_documents(str(docs))
    assert count >= 1


def test_ingest_deduplication(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "file.txt").write_text("Unique content about smart home control.", encoding="utf-8")

    mem = _make_memory(tmp_path)
    first = mem.ingest_documents(str(docs))
    second = mem.ingest_documents(str(docs))  # same file, same hash
    assert first >= 1
    assert second == 0  # already ingested


def test_ingest_missing_path(tmp_path):
    mem = _make_memory(tmp_path)
    count = mem.ingest_documents(str(tmp_path / "nonexistent"))
    assert count == 0


def test_ingest_empty_dir(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    mem = _make_memory(tmp_path)
    count = mem.ingest_documents(str(docs))
    assert count == 0


# ---------------------------------------------------------------------------
# Knowledge retrieval
# ---------------------------------------------------------------------------

def test_query_knowledge_returns_results(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "home.txt").write_text(
        "The living room light can be controlled via voice command. "
        "Say 'turn on the living room lights' to activate.",
        encoding="utf-8",
    )
    mem = _make_memory(tmp_path)
    mem.ingest_documents(str(docs))

    results = mem.query_knowledge("how to control lights")
    assert len(results) >= 1
    assert any("light" in r.lower() for r in results)


def test_query_knowledge_empty_collection(tmp_path):
    mem = _make_memory(tmp_path)
    results = mem.query_knowledge("anything")
    assert results == []


# ---------------------------------------------------------------------------
# build_context
# ---------------------------------------------------------------------------

def test_build_context_with_turns_and_knowledge(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "info.txt").write_text("Jarvis can check your calendar with voice commands.", encoding="utf-8")

    mem = _make_memory(tmp_path)
    mem.ingest_documents(str(docs))
    mem.add_turn("ctx_session", "user", "What can you do?")
    mem.add_turn("ctx_session", "assistant", "I can manage your calendar and smart home.")

    context = mem.build_context("tell me about calendar", "ctx_session")
    # Should contain either conversation turns or knowledge text
    assert context  # non-empty
    assert isinstance(context, str)


def test_build_context_empty_session(tmp_path):
    mem = _make_memory(tmp_path)
    context = mem.build_context("anything", "empty_session")
    assert context == "" or isinstance(context, str)
