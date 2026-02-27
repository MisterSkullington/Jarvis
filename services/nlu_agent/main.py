"""
NLU + Agent service: FastAPI with /parse (intent + entities) and /chat (Ollama + tools).
Rule-based intents for lights, reminder, timer, weather, etc.; LLM fallback for open-ended queries.
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

# Rule patterns: (regex, intent, entity_keys for capture groups 1, 2, ...)
RULES = [
    (r"\b(hi|hello|hey|good morning|good evening)\b", "greet", []),
    (r"(?:weather|temperature|forecast).*?(?:in|at)\s+(\w+(?:\s+\w+)?)", "weather", ["location"]),
    (r"\bweather\b", "weather", []),
    (r"\b(turn on|switch on|enable)\s+(?:the\s+)?(.+?)\s*(?:light|lights)\b", "light_control", ["action", "room"]),
    (r"\b(turn off|switch off|disable)\s+(?:the\s+)?(.+?)\s*(?:light|lights)\b", "light_control", ["action", "room"]),
    (r"\b(living room|bedroom|kitchen|bathroom|office)\s*(?:light|lights)?\s*(on|off)\b", "light_control", ["room", "on_off"]),
    (r"\bremind me to (.+?) (?:at|in|on) (.+?)(?:\s|$)", "reminder", ["task", "time"]),
    (r"\b(?:timer|set timer).*?(\d+)\s*(min|minute|hour|sec)", "timer", ["duration", "unit"]),
    (r"\b(what time|current time|time now)\b", "time_query", []),
    (r"\b(stop|cancel|never mind)\b", "cancel", []),
]

# In-memory conversation history (last N turns); can be replaced with SQLite
CHAT_HISTORY: List[Dict[str, str]] = []
MAX_HISTORY = 10


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


def rule_based_parse(text: str) -> Optional[tuple[str, Dict[str, Any], float]]:
    """Return (intent, entities, confidence) or None."""
    text_lower = (text or "").strip().lower()
    if not text_lower:
        return None
    for pattern, intent, entity_keys in RULES:
        m = re.search(pattern, text_lower, re.IGNORECASE)
        if m:
            entities = {}
            if entity_keys and m.groups():
                for i, key in enumerate(entity_keys):
                    if i + 1 < len(m.groups()) and m.group(i + 1):
                        entities[key] = m.group(i + 1).strip()
            return (intent, entities, 0.9)
    return None


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
    prompt = (
        "Extract intent and entities from this user message. Reply with exactly: INTENT: <name> ENTITIES: <json object>. "
        "Use intents: greet, weather, light_control, reminder, timer, time_query, cancel, general.\n"
        f"User: {text}\n"
    )
    content = ollama_chat([{"role": "user", "content": prompt}], config, timeout=15)
    if not content:
        return None
    intent = "general"
    entities = {}
    for line in content.strip().split("\n"):
        if line.strip().upper().startswith("INTENT:"):
            intent = line.split(":", 1)[1].strip().lower().replace(" ", "_")[:50]
        elif line.strip().upper().startswith("ENTITIES:"):
            try:
                import json
                entities = json.loads(line.split(":", 1)[1].strip())
            except Exception:
                pass
    return (intent, entities, 0.7)


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
        return ChatResponse(response="I didn't catch that.", intent=None, tools_used=[])
    # Optional: run tools from orchestrator; here we just LLM respond with context
    messages = []
    for h in CHAT_HISTORY[-MAX_HISTORY:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": text})
    content = ollama_chat(messages, config)
    if content:
        CHAT_HISTORY.append({"role": "user", "content": text})
        CHAT_HISTORY.append({"role": "assistant", "content": content})
        if len(CHAT_HISTORY) > MAX_HISTORY * 2:
            CHAT_HISTORY[:] = CHAT_HISTORY[-MAX_HISTORY * 2 :]
        return ChatResponse(response=content.strip(), intent=None, tools_used=[])
    # Fallback
    parsed = rule_based_parse(text)
    intent = parsed[0] if parsed else "general"
    fallbacks = {
        "greet": "Hello. How can I help you?",
        "weather": "I don't have weather data configured yet. You can add a weather API in integrations.",
        "light_control": "I'll pass that to the smart home. Make sure the orchestrator is connected to Home Assistant.",
        "reminder": "Reminder noted. The scheduler will handle it.",
        "timer": "Timer set.",
        "time_query": f"The time is not available from this service. It's {time.strftime('%H:%M')} here.",
        "cancel": "Cancelled.",
    }
    return ChatResponse(
        response=fallbacks.get(intent, "I'm not sure how to help with that. Try asking about weather, lights, or reminders."),
        intent=intent,
        tools_used=[],
    )


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "service": "nlu_agent"}


def main() -> None:
    import uvicorn
    config = load_config()
    configure_logging(config.log_level, "nlu_agent")
    uvicorn.run(app, host="0.0.0.0", port=8001)


if __name__ == "__main__":
    main()
