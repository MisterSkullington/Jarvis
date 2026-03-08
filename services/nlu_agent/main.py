"""
NLU + Agent service: FastAPI with /parse (intent + entities) and /chat (Ollama + tools).
Rule-based intents for lights, reminder, timer, weather, calendar, system_command, etc.;
LLM fallback for open-ended queries. Personality via system prompt. Optional RAG memory.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from jarvis_core import load_config, configure_logging

LOG = __import__("logging").getLogger(__name__)

app = FastAPI(title="Jarvis NLU Agent", version="0.1.0")

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

# In-memory conversation history fallback when memory is disabled
CHAT_HISTORY: List[Dict[str, str]] = []
MAX_HISTORY = 10

# Optional persistent memory (initialised in startup event)
_memory: Optional[Any] = None  # JarvisMemory | None


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
    global _memory
    config = load_config()
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
    for rule in RULES:
        pattern, intent, entity_keys = rule[0], rule[1], rule[2]
        static_entities: Dict[str, Any] = rule[3] if len(rule) > 3 else {}
        m = re.search(pattern, text_lower, re.IGNORECASE)
        if m:
            entities: Dict[str, Any] = dict(static_entities)
            if entity_keys and m.groups():
                for i, key in enumerate(entity_keys):
                    if i < len(m.groups()) and m.group(i + 1):
                        entities[key] = m.group(i + 1).strip()
            return (intent, entities, 0.9)
    return None


def _system_message(config) -> Dict[str, str]:
    """Return the Jarvis system message dict for Ollama calls."""
    prompt = getattr(getattr(config, "personality", None), "system_prompt", None) or (
        "You are Jarvis, a highly intelligent personal assistant. "
        "Speak with dry British wit, address the user as 'Sir', and be concise."
    )
    return {"role": "system", "content": prompt}


def ollama_chat(messages: List[Dict[str, str]], config, timeout: int = 60) -> Optional[str]:
    """Call Ollama /api/chat and return assistant message content."""
    if not getattr(config, "llm", None) or not getattr(config.llm, "enabled", True):
        return None
    url = f"{config.llm.base_url.rstrip('/')}/api/chat"
    payload = {"model": config.llm.model, "messages": messages, "stream": False}
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
            return (data.get("message") or {}).get("content")
    except Exception as e:
        LOG.warning("Ollama chat failed: %s", e)
        return None


def ollama_parse_intent(text: str, config) -> Optional[tuple[str, Dict[str, Any], float]]:
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
    content = ollama_chat([system, user], config, timeout=15)
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
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/parse", response_model=ParseResponse)
def parse(req: ParseRequest) -> ParseResponse:
    config = load_config()
    text = (req.text or "").strip()
    if not text:
        return ParseResponse(intent="unknown", entities={}, confidence=0.0, raw_text=text)
    result = rule_based_parse(text)
    if result is None and getattr(config.llm, "enabled", True):
        result = ollama_parse_intent(text, config)
    if result:
        intent, entities, conf = result
        return ParseResponse(intent=intent, entities=entities, confidence=conf, raw_text=text)
    return ParseResponse(intent="general", entities={}, confidence=0.5, raw_text=text)


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    config = load_config()
    text = (req.text or "").strip()
    if not text:
        honorific = getattr(getattr(config, "personality", None), "honorific", "Sir")
        return ChatResponse(
            response=f"I didn't quite catch that, {honorific}.",
            intent=None,
            tools_used=[],
        )

    # Build message list: system prompt → optional RAG context → history → user
    messages: List[Dict[str, str]] = [_system_message(config)]

    if _memory and req.session_id:
        try:
            context = _memory.build_context(text, req.session_id)
            if context:
                messages.append({"role": "system", "content": f"Relevant context:\n{context}"})
            for turn in _memory.get_recent_turns(req.session_id, limit=MAX_HISTORY):
                messages.append({"role": turn["role"], "content": turn["content"]})
        except Exception as exc:
            LOG.warning("Memory retrieval failed: %s", exc)
    else:
        for h in CHAT_HISTORY[-MAX_HISTORY:]:
            messages.append({"role": h["role"], "content": h["content"]})

    messages.append({"role": "user", "content": text})

    content = ollama_chat(messages, config)
    if content:
        # Persist turns
        if _memory and req.session_id:
            try:
                _memory.add_turn(req.session_id, "user", text)
                _memory.add_turn(req.session_id, "assistant", content)
            except Exception as exc:
                LOG.warning("Memory store failed: %s", exc)
        else:
            CHAT_HISTORY.append({"role": "user", "content": text})
            CHAT_HISTORY.append({"role": "assistant", "content": content})
            if len(CHAT_HISTORY) > MAX_HISTORY * 2:
                CHAT_HISTORY[:] = CHAT_HISTORY[-MAX_HISTORY * 2:]
        return ChatResponse(response=content.strip(), intent=None, tools_used=[])

    # LLM unavailable — personality-infused rule-based fallback
    honorific = getattr(getattr(config, "personality", None), "honorific", "Sir")
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


@app.post("/agent", response_model=ChatResponse)
def agent(req: ChatRequest) -> ChatResponse:
    """Tool-calling agent endpoint. Requires agent.enabled: true in config."""
    config = load_config()
    text = (req.text or "").strip()
    honorific = getattr(getattr(config, "personality", None), "honorific", "Sir")
    if not text:
        return ChatResponse(response=f"I didn't quite catch that, {honorific}.", tools_used=[])

    if not getattr(getattr(config, "agent", None), "enabled", False):
        # Agent disabled — fall through to regular chat
        return chat(req)

    try:
        from services.nlu_agent.agent import run_agent
        response, tools_used = run_agent(text, req.session_id, config, _memory)
    except Exception as exc:
        LOG.warning("Agent failed, falling back to chat: %s", exc)
        return chat(req)

    if _memory and req.session_id:
        try:
            _memory.add_turn(req.session_id, "user", text)
            _memory.add_turn(req.session_id, "assistant", response)
        except Exception as exc:
            LOG.warning("Memory store (agent) failed: %s", exc)

    return ChatResponse(response=response, intent=None, tools_used=tools_used)


@app.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest) -> IngestResponse:
    if not _memory:
        raise HTTPException(status_code=503, detail="Memory is not enabled or failed to initialise.")
    try:
        count = _memory.ingest_documents(req.path)
        return IngestResponse(chunks_ingested=count, status="ok")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/health")
def health() -> Dict[str, str]:
    memory_status = "enabled" if _memory else "disabled"
    return {"status": "ok", "service": "nlu_agent", "memory": memory_status}


def main() -> None:
    import uvicorn
    config = load_config()
    configure_logging(config.log_level, "nlu_agent")
    uvicorn.run(app, host="0.0.0.0", port=8001)


if __name__ == "__main__":
    main()
