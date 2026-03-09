"""
NLU + Agent service: FastAPI with /parse (intent + entities) and /chat (Ollama + tools).
Rule-based intents for lights, reminder, timer, weather, calendar, system_command, etc.;
LLM fallback for open-ended queries. Personality via system prompt. Optional RAG memory.
"""
from __future__ import annotations

import asyncio
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from jarvis_core import load_config, configure_logging, get_honorific, get_system_message, ollama_chat

LOG = __import__("logging").getLogger(__name__)

app = FastAPI(title="Jarvis NLU Agent", version="0.1.0")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")

# ---------------------------------------------------------------------------
# Rule patterns: (regex, intent, entity_keys, optional_static_entities)
# entity_keys: list of names for regex capture groups (positional)
# optional_static_entities: dict of key→value added verbatim (no capture group)
# ---------------------------------------------------------------------------
RULES: list[tuple] = [
    (r"\b(hi|hello|hey|good morning|good evening)\b", "greet", []),
    (r"(?:weather|temperature|forecast).*?(?:in|at)\s+(\w+(?:\s+\w+)?)", "weather", ["location"]),
    (r"\bweather\b", "weather", []),
    (r"\b(turn on|switch on|enable)\s+(?:the\s+)?(.+?)\s*(?:light|lights)\b", "light_control", ["action", "room"]),
    (r"\b(turn off|switch off|disable)\s+(?:the\s+)?(.+?)\s*(?:light|lights)\b", "light_control", ["action", "room"]),
    (r"\b(living room|bedroom|kitchen|bathroom|office)\s*(?:light|lights)?\s*(on|off)\b", "light_control", ["room", "on_off"]),
    (r"\bremind me to (.+?) (?:at|in|on) (.+?)(?:\s|$)", "reminder", ["task", "time"]),
    (r"\b(?:timer|set timer).*?(\d+)\s*(min|minute|hour|sec)", "timer", ["duration", "unit"]),
    (r"\b(what time|current time|time now)\b", "time_query", []),
    # Calendar / agenda
    (r"\b(?:what(?:'s| is) on my|check my|show my|open my)\s*(?:calendar|schedule|agenda)\b", "calendar", []),
    (r"\b(?:next meeting|upcoming event|my event|my meeting|my agenda|my schedule)\b", "calendar", []),
    (r"\b(?:calendar|agenda)\b", "calendar", []),
    # System control — static entity, no capture groups needed
    (r"\block\s+(?:my\s+)?(?:pc|computer|screen|workstation)\b", "system_command", [], {"command_id": "lock_pc"}),
    (r"\block\s+(?:the\s+)?screen\b", "system_command", [], {"command_id": "lock_pc"}),
    (r"\b(stop|cancel|never mind)\b", "cancel", []),
]

# Pre-compiled RULES for efficient per-request matching
_COMPILED_RULES = [
    (re.compile(r[0], re.IGNORECASE), r[1], r[2], r[3] if len(r) > 3 else {})
    for r in RULES
]

# In-memory conversation history fallback when memory is disabled
CHAT_HISTORY: List[Dict[str, str]] = []
MAX_HISTORY = 10
_chat_history_lock = threading.Lock()

# Module-level config cache — loaded once at startup, not per-request
_config = None


def _get_config():
    """Return the cached JarvisConfig, loading on first call."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


# Optional persistent memory (initialised in startup event)
_memory: Optional[Any] = None  # JarvisMemory | None

# Control-character stripping regex (keeps normal whitespace)
_CTRL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize(text: str) -> str:
    """Strip control characters from user input before passing to LLM."""
    return _CTRL_CHAR_RE.sub("", text).strip()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ParseRequest(BaseModel):
    text: str


class ParseResponse(BaseModel):
    intent: str
    entities: Dict[str, Any]
    confidence: float
    raw_text: str


class ChatRequest(BaseModel):
    text: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    intent: Optional[str] = None
    tools_used: List[str] = []


class IngestRequest(BaseModel):
    path: Optional[str] = None


class IngestResponse(BaseModel):
    chunks_ingested: int
    status: str


# ---------------------------------------------------------------------------
# Startup: initialise memory / RAG
# ---------------------------------------------------------------------------

@app.on_event("startup")
def _startup() -> None:
    global _memory, _config
    _config = load_config()
    config = _config
    configure_logging(config.log_level, "nlu_agent")
    if getattr(config, "memory", None) and config.memory.enabled:
        try:
            from services.nlu_agent.memory import JarvisMemory
            _memory = JarvisMemory(config.memory)
            count = _memory.ingest_documents()
            LOG.info("Memory ready. Ingested %d chunks from documents path.", count)
        except Exception as exc:
            LOG.warning("Memory init failed (continuing without RAG): %s", exc)


# ---------------------------------------------------------------------------
# NLU helpers
# ---------------------------------------------------------------------------

def rule_based_parse(text: str) -> Optional[tuple[str, Dict[str, Any], float]]:
    """Return (intent, entities, confidence) or None."""
    text_lower = (text or "").strip().lower()
    if not text_lower:
        return None
    for pattern, intent, entity_keys, static_entities in _COMPILED_RULES:
        m = pattern.search(text_lower)
        if m:
            entities: Dict[str, Any] = dict(static_entities)
            if entity_keys and m.groups():
                for i, key in enumerate(entity_keys):
                    if i < len(m.groups()) and m.group(i + 1):
                        entities[key] = m.group(i + 1).strip()
            return (intent, entities, 0.9)
    return None


def _ollama_parse_intent(text: str, config) -> Optional[tuple[str, Dict[str, Any], float]]:
    """Use LLM to extract intent/entities if rule-based missed."""
    import json
    system = {
        "role": "system",
        "content": (
            "You are a precise intent extraction system. "
            "Reply with exactly: INTENT: <name> ENTITIES: <json object>. "
            "Use intents: greet, weather, light_control, reminder, timer, "
            "time_query, calendar, system_command, cancel, general."
        ),
    }
    user = {
        "role": "user",
        "content": f"Extract intent and entities from: {text}",
    }
    content = (ollama_chat([system, user], config, timeout=15) or {}).get("content")
    if not content:
        return None
    intent = "general"
    entities: Dict[str, Any] = {}
    for line in content.strip().split("\n"):
        if line.strip().upper().startswith("INTENT:"):
            intent = line.split(":", 1)[1].strip().lower().replace(" ", "_")[:50]
        elif line.strip().upper().startswith("ENTITIES:"):
            try:
                entities = json.loads(line.split(":", 1)[1].strip())
            except Exception:
                pass
    return (intent, entities, 0.7)


# ---------------------------------------------------------------------------
# Endpoints (async — blocking LLM/memory calls run in thread pool)
# ---------------------------------------------------------------------------

@app.post("/parse", response_model=ParseResponse)
async def parse(req: ParseRequest) -> ParseResponse:
    config = _get_config()
    text = _sanitize(req.text or "")
    if not text:
        return ParseResponse(intent="unknown", entities={}, confidence=0.0, raw_text=text)

    result = rule_based_parse(text)
    if result is None and getattr(config.llm, "enabled", True):
        result = await asyncio.to_thread(_ollama_parse_intent, text, config)
    if result:
        intent, entities, conf = result
        return ParseResponse(intent=intent, entities=entities, confidence=conf, raw_text=text)
    return ParseResponse(intent="general", entities={}, confidence=0.5, raw_text=text)


def _do_chat(text: str, session_id: Optional[str], config) -> ChatResponse:
    """Synchronous chat logic — run via asyncio.to_thread."""
    messages: List[Dict[str, str]] = [get_system_message(config)]

    if _memory and session_id:
        try:
            context = _memory.build_context(text, session_id)
            if context:
                messages.append({"role": "system", "content": f"Relevant context:\n{context}"})
            for turn in _memory.get_recent_turns(session_id, limit=MAX_HISTORY):
                messages.append({"role": turn["role"], "content": turn["content"]})
        except Exception as exc:
            LOG.warning("Memory retrieval failed: %s", exc)
    else:
        with _chat_history_lock:
            for h in CHAT_HISTORY[-MAX_HISTORY:]:
                messages.append({"role": h["role"], "content": h["content"]})

    messages.append({"role": "user", "content": text})

    content = (ollama_chat(messages, config) or {}).get("content")
    if content:
        if _memory and session_id:
            try:
                _memory.add_turn(session_id, "user", text)
                _memory.add_turn(session_id, "assistant", content)
            except Exception as exc:
                LOG.warning("Memory store failed: %s", exc)
        else:
            with _chat_history_lock:
                CHAT_HISTORY.append({"role": "user", "content": text})
                CHAT_HISTORY.append({"role": "assistant", "content": content})
                if len(CHAT_HISTORY) > MAX_HISTORY * 2:
                    CHAT_HISTORY[:] = CHAT_HISTORY[-MAX_HISTORY * 2:]
        return ChatResponse(response=content.strip(), intent=None, tools_used=[])

    # LLM unavailable — personality-infused rule-based fallback
    honorific = get_honorific(config)
    parsed = rule_based_parse(text)
    intent = parsed[0] if parsed else "general"
    fallbacks = {
        "greet": f"Good day, {honorific}. How may I be of assistance?",
        "weather": f"The weather API doesn't appear to be configured, {honorific}. Check your integrations.",
        "light_control": f"I'll relay that to the smart home, {honorific}. Ensure the orchestrator is connected.",
        "reminder": f"Noted, {honorific}. The scheduler will handle your reminder.",
        "timer": "Timer set.",
        "time_query": f"The time is {time.strftime('%H:%M')}, {honorific}.",
        "calendar": f"I'm unable to reach the calendar at the moment, {honorific}.",
        "system_command": f"System command noted, {honorific}.",
        "cancel": "Cancelled.",
    }
    return ChatResponse(
        response=fallbacks.get(
            intent,
            f"I'm afraid I couldn't process that, {honorific}. Try asking about weather, lights, or your calendar.",
        ),
        intent=intent,
        tools_used=[],
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    config = _get_config()
    text = _sanitize(req.text or "")
    if not text:
        return ChatResponse(
            response=f"I didn't quite catch that, {get_honorific(config)}.",
            intent=None,
            tools_used=[],
        )
    return await asyncio.to_thread(_do_chat, text, req.session_id, config)


def _do_agent(text: str, session_id: Optional[str], config) -> ChatResponse:
    """Synchronous agent logic — run via asyncio.to_thread."""
    if not getattr(getattr(config, "agent", None), "enabled", False):
        return _do_chat(text, session_id, config)
    try:
        from services.nlu_agent.agent import run_agent
        response, tools_used = run_agent(text, session_id, config, _memory)
    except Exception as exc:
        LOG.warning("Agent failed, falling back to chat: %s", exc)
        return _do_chat(text, session_id, config)

    if _memory and session_id:
        try:
            _memory.add_turn(session_id, "user", text)
            _memory.add_turn(session_id, "assistant", response)
        except Exception as exc:
            LOG.warning("Memory store (agent) failed: %s", exc)

    return ChatResponse(response=response, intent=None, tools_used=tools_used)


@app.post("/agent", response_model=ChatResponse)
async def agent(req: ChatRequest) -> ChatResponse:
    """Tool-calling agent endpoint. Requires agent.enabled: true in config."""
    config = _get_config()
    text = _sanitize(req.text or "")
    honorific = get_honorific(config)
    if not text:
        return ChatResponse(response=f"I didn't quite catch that, {honorific}.", tools_used=[])
    return await asyncio.to_thread(_do_agent, text, req.session_id, config)


@app.post("/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest) -> IngestResponse:
    if not _memory:
        raise HTTPException(status_code=503, detail="Memory is not enabled or failed to initialise.")
    try:
        count = await asyncio.to_thread(_memory.ingest_documents, req.path)
        return IngestResponse(chunks_ingested=count, status="ok")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/health")
async def health() -> Dict[str, str]:
    memory_status = "enabled" if _memory else "disabled"
    return {"status": "ok", "service": "nlu_agent", "memory": memory_status}


def main() -> None:
    import uvicorn
    config = load_config()
    configure_logging(config.log_level, "nlu_agent")
    uvicorn.run(app, host="127.0.0.1", port=8001)


if __name__ == "__main__":
    main()
