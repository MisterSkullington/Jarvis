"""
NLU + Agent service: FastAPI with /parse (intent + entities) and /chat (Ollama + tools).
Rule-based intents for lights, reminder, timer, weather, etc.; LLM fallback with
full J.A.R.V.I.S. persona for open-ended queries.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from jarvis_core import load_config, configure_logging
from jarvis_core.persona import UserProfile, build_system_prompt
import jarvis_core.persona as persona

LOG = __import__("logging").getLogger(__name__)

app = FastAPI(title="Jarvis NLU Agent", version="0.2.0")

RULES = [
    (r"\b(hi|hello|hey|good morning|good evening|good afternoon)\b", "greet", []),
    (r"(?:search|look up|google|find|research)\s+(?:for\s+)?(.+)", "web_search", ["query"]),
    (r"(?:weather|temperature|forecast).*?(?:in|at|for)\s+(\w+(?:\s+\w+)?)", "weather", ["location"]),
    (r"\bweather\b", "weather", []),
    (r"\b(living room|bedroom|kitchen|bathroom|office|garage|hallway|dining room|basement|attic)\s*(?:light|lights)?\s*(on|off)\b", "light_control", ["room", "on_off"]),
    (r"\b(turn on|switch on|enable)\s+(?:the\s+)?((?:(?!light)\w)+(?:\s+(?!light)\w+)*)\s+(?:light|lights)\b", "light_control", ["action", "room"]),
    (r"\b(turn off|switch off|disable)\s+(?:the\s+)?((?:(?!light)\w)+(?:\s+(?!light)\w+)*)\s+(?:light|lights)\b", "light_control", ["action", "room"]),
    (r"\b(turn on|turn off|switch on|switch off)\s+(?:the\s+)?(?:light|lights)\b", "light_control", ["action"]),
    (r"\b(?:set|adjust)\s+(?:the\s+)?(?:temperature|thermostat|heating|cooling).*?(\d+)", "climate_control", ["temperature"]),
    (r"\b(lock|unlock)\s+(?:the\s+)?(.+?)\s*(?:door|doors|lock)\b", "lock_control", ["action", "door"]),
    (r"\b(?:play|put on)\s+(?:some\s+)?(.+?)(?:\s+on\s+(.+))?$", "media_control", ["media", "device"]),
    (r"\b(pause|resume|skip|next|previous)\s*(?:the\s+)?(?:music|song|track|media)?\b", "media_control", ["action"]),
    (r"\b(stop)\s+(?:the\s+)?(?:music|song|track|media|playback)\b", "media_control", ["action"]),
    (r"\bremind me to (.+?) (?:at|in|on) (.+)$", "reminder", ["task", "time"]),
    (r"\b(?:timer|set timer|set a timer).*?(\d+)\s*(min|minute|minutes|hour|hours|sec|seconds)", "timer", ["duration", "unit"]),
    (r"\b(?:what(?:'s| is) (?:the |my )?(?:schedule|calendar|agenda)|my events|upcoming events)\b", "calendar_query", []),
    (r"\b(?:news|headlines|what's happening)\b", "news_query", []),
    (r"\b(what time|current time|time now|what's the time)\b", "time_query", []),
    (r"\b(?:morning briefing|daily briefing|brief me|status report)\b", "briefing", []),
    (r"\b(?:system status|system info|how.s the (?:system|server|computer)|diagnostics)\b", "system_status", []),
    (r"\b(stop|cancel|never mind|forget it)\b", "cancel", []),
    (r"\b(yes|yeah|yep|affirmative|do it|go ahead|proceed)\b", "confirm_yes", []),
    (r"\b(no|nope|negative|don't|hold off|abort)\b", "confirm_no", []),
]

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
                    if i < len(m.groups()) and m.group(i + 1):
                        entities[key] = m.group(i + 1).strip()
            return (intent, entities, 0.9)
    return None


def _get_user_profile(config) -> UserProfile:
    """Extract UserProfile from config."""
    u = getattr(config, "user", None)
    if u:
        return UserProfile(
            name=getattr(u, "name", "Sir"),
            preferred_address=getattr(u, "preferred_address", "sir"),
            location=getattr(u, "location", ""),
            timezone=getattr(u, "timezone", ""),
        )
    return UserProfile()


def ollama_chat(messages: List[Dict[str, str]], config, timeout: int = 60) -> Optional[str]:
    """Call Ollama /api/chat with JARVIS persona and return assistant message content."""
    if not getattr(config, "llm", None) or not getattr(config.llm, "enabled", True):
        return None
    url = f"{config.llm.base_url.rstrip('/')}/api/chat"
    user_profile = _get_user_profile(config)
    system_prompt = build_system_prompt(user_profile)
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    payload = {"model": config.llm.model, "messages": full_messages, "stream": False}
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
        "Extract intent and entities from this user message. Reply with exactly: "
        "INTENT: <name> ENTITIES: <json object>.\n"
        "Use intents: greet, weather, light_control, climate_control, lock_control, "
        "media_control, reminder, timer, calendar_query, news_query, time_query, "
        "web_search, briefing, cancel, general.\n"
        f"User: {text}\n"
    )
    content = ollama_chat([{"role": "user", "content": prompt}], config, timeout=15)
    if not content:
        return None
    intent = "general"
    entities: Dict[str, Any] = {}
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
    user_profile = _get_user_profile(config)
    text = (req.text or "").strip()
    if not text:
        return ChatResponse(
            response=f"I didn't quite catch that, {user_profile.preferred_address}.",
            intent=None,
            tools_used=[],
        )
    messages = []
    for h in CHAT_HISTORY[-MAX_HISTORY:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": text})
    content = ollama_chat(messages, config)
    if content:
        CHAT_HISTORY.append({"role": "user", "content": text})
        CHAT_HISTORY.append({"role": "assistant", "content": content})
        if len(CHAT_HISTORY) > MAX_HISTORY * 2:
            CHAT_HISTORY[:] = CHAT_HISTORY[-MAX_HISTORY * 2:]
        return ChatResponse(response=content.strip(), intent=None, tools_used=[])
    parsed = rule_based_parse(text)
    intent = parsed[0] if parsed else "general"
    addr = user_profile.preferred_address
    fallbacks = {
        "greet": persona.greet(user_profile),
        "weather": persona.weather_response("your area", "Weather API not configured", user_profile),
        "light_control": f"I'll relay that to the smart home system, {addr}. Please ensure Home Assistant is connected.",
        "reminder": f"Reminder noted, {addr}. The scheduler will handle it.",
        "timer": f"Timer set, {addr}.",
        "time_query": persona.time_response(user_profile),
        "cancel": persona.cancel_response(user_profile),
    }
    return ChatResponse(
        response=fallbacks.get(intent, persona.fallback_response(user_profile)),
        intent=intent,
        tools_used=[],
    )


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "service": "nlu_agent", "version": "0.2.0"}


def main() -> None:
    import uvicorn
    config = load_config()
    configure_logging(config.log_level, "nlu_agent")
    uvicorn.run(app, host="0.0.0.0", port=8001)


if __name__ == "__main__":
    main()
