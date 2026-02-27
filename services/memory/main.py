"""
Persistent conversation memory for J.A.R.V.I.S.

Stores conversation turns in SQLite with timestamps and session IDs.
Provides retrieval APIs for the orchestrator and NLU to maintain context
across sessions.
"""
from __future__ import annotations

import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from jarvis_core import load_config

LOG = logging.getLogger(__name__)
Base = declarative_base()


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True, nullable=False)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    intent = Column(String(64), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    latency_sec = Column(Float, nullable=True)


class MemoryStore:
    """Persistent conversation memory backed by SQLite."""

    def __init__(self, db_path: str = "data/memory.db"):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(f"sqlite:///{path}", echo=False)
        Base.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine)
        self._current_session_id = str(uuid.uuid4())[:12]
        LOG.info("Memory store initialised at %s (session=%s)", path, self._current_session_id)

    @property
    def session_id(self) -> str:
        return self._current_session_id

    def new_session(self) -> str:
        self._current_session_id = str(uuid.uuid4())[:12]
        return self._current_session_id

    def add_turn(
        self,
        role: str,
        content: str,
        intent: Optional[str] = None,
        latency_sec: Optional[float] = None,
        session_id: Optional[str] = None,
    ) -> None:
        sid = session_id or self._current_session_id
        with self._Session() as session:
            turn = ConversationTurn(
                session_id=sid,
                role=role,
                content=content,
                intent=intent,
                latency_sec=latency_sec,
            )
            session.add(turn)
            session.commit()

    def get_recent(self, limit: int = 20, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        sid = session_id or self._current_session_id
        with self._Session() as session:
            turns = (
                session.query(ConversationTurn)
                .filter(ConversationTurn.session_id == sid)
                .order_by(ConversationTurn.timestamp.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "role": t.role,
                    "content": t.content,
                    "intent": t.intent,
                    "timestamp": t.timestamp.isoformat() if t.timestamp else None,
                }
                for t in reversed(turns)
            ]

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        with self._Session() as session:
            turns = (
                session.query(ConversationTurn)
                .filter(ConversationTurn.content.contains(query))
                .order_by(ConversationTurn.timestamp.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "role": t.role,
                    "content": t.content,
                    "intent": t.intent,
                    "session_id": t.session_id,
                    "timestamp": t.timestamp.isoformat() if t.timestamp else None,
                }
                for t in turns
            ]

    def get_stats(self) -> Dict[str, Any]:
        with self._Session() as session:
            total = session.query(ConversationTurn).count()
            sessions = session.query(ConversationTurn.session_id).distinct().count()
            return {"total_turns": total, "total_sessions": sessions, "current_session": self._current_session_id}


_store: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        config = load_config()
        db_path = getattr(config.memory, "db_path", "data/memory.db")
        _store = MemoryStore(db_path)
    return _store
