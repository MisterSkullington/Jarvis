"""
Orchestrator: the central brain of J.A.R.V.I.S.

Subscribes to jarvis/stt/text, calls NLU /parse and /chat, dispatches intents to
integrations, manages conversation state, and publishes responses to jarvis/tts/text.
Exposes /metrics (Prometheus-style) on port 8002.
"""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx
import paho.mqtt.client as mqtt

from jarvis_core import load_config, configure_logging
from jarvis_core.persona import UserProfile
import jarvis_core.persona as persona

LOG = logging.getLogger(__name__)

_memory = None
try:
    from services.memory.main import get_memory_store
    _memory = get_memory_store()
    LOG.info("Memory store connected (session=%s)", _memory.session_id)
except Exception as e:
    LOG.debug("Memory store unavailable: %s", e)

_skill_registry = {}
try:
    from skills import load_skills
    _skill_registry = load_skills()
    if _skill_registry:
        LOG.info("Loaded %d skill(s): %s", len(_skill_registry), ", ".join(_skill_registry.keys()))
except Exception as e:
    LOG.debug("Skill loading skipped: %s", e)

TOPIC_STT_TEXT = "jarvis/stt/text"
TOPIC_TTS_TEXT = "jarvis/tts/text"
TOPIC_SCHEDULER_ADD = "jarvis/scheduler/add"
TOPIC_STATUS = "jarvis/status/orchestrator"
TOPIC_UI_STATE = "jarvis/ui/state"
TOPIC_TEXT_INPUT = "jarvis/text/input"

_metrics: Dict[str, float] = {"jarvis_utterances_total": 0, "jarvis_errors_total": 0}
_metrics_lock = threading.Lock()
_last_latency_sec: float = 0.0
_last_dangerous_action_time: float = 0.0
_intent_counts: Dict[str, int] = {}

_pending_confirmation: Optional[Dict[str, Any]] = None
_confirmation_lock = threading.Lock()


def _get_user(config) -> UserProfile:
    u = getattr(config, "user", None)
    if u:
        return UserProfile(
            name=getattr(u, "name", "Sir"),
            preferred_address=getattr(u, "preferred_address", "sir"),
            location=getattr(u, "location", ""),
            timezone=getattr(u, "timezone", ""),
        )
    return UserProfile()


def parse_nlu(text: str, config) -> dict:
    base = config.nlu_agent.base_url.rstrip("/")
    try:
        with httpx.Client(timeout=config.nlu_agent.timeout_seconds) as client:
            r = client.post(f"{base}/parse", json={"text": text})
            if r.is_success:
                return r.json()
    except Exception as e:
        LOG.warning("NLU parse failed: %s", e)
    return {"intent": "general", "entities": {}, "confidence": 0.0, "raw_text": text}


def chat_nlu(text: str, config) -> str:
    base = config.nlu_agent.base_url.rstrip("/")
    user = _get_user(config)
    try:
        with httpx.Client(timeout=config.nlu_agent.timeout_seconds) as client:
            r = client.post(f"{base}/chat", json={"text": text})
            if r.is_success:
                data = r.json()
                return (data.get("response") or "").strip()
    except Exception as e:
        LOG.warning("NLU chat failed: %s", e)
    return f"I'm having trouble reaching my language centres, {user.preferred_address}. One moment."


def _publish_state(mqtt_client: mqtt.Client, state: str) -> None:
    """Publish UI state for HUD visualisation."""
    try:
        mqtt_client.publish(
            TOPIC_UI_STATE,
            json.dumps({"state": state, "timestamp": time.time()}),
            qos=0,
        )
    except Exception:
        pass


def dispatch_and_respond(
    text: str, parsed: dict, config, mqtt_client: mqtt.Client
) -> str:
    global _last_dangerous_action_time, _pending_confirmation
    intent = parsed.get("intent") or "general"
    entities = parsed.get("entities") or {}
    user = _get_user(config)

    # --- Confirmation flow ---
    with _confirmation_lock:
        if _pending_confirmation and intent in ("confirm_yes", "confirm_no"):
            pending = _pending_confirmation
            _pending_confirmation = None
            if intent == "confirm_yes":
                return _execute_confirmed(pending, config, mqtt_client, user)
            return persona.confirmation_rejected(user)

    if intent == "greet":
        return persona.greet(user)

    if intent == "weather":
        from services.integrations.web_apis import get_weather
        location = entities.get("location") or user.location or "London"
        info = get_weather(location)
        summary = info.get("summary", "Unknown")
        return persona.weather_response(info.get("location", location), summary, user)

    if intent == "light_control":
        room = entities.get("room")
        if room and room.lower().strip() in ("the", "a", "my", ""):
            room = None
        if not room:
            return f"Which room, {user.preferred_address}?"
        rate_limit_sec = getattr(config.safety, "dangerous_actions_rate_limit_seconds", 30)
        if time.time() - _last_dangerous_action_time < rate_limit_sec:
            return persona.rate_limited_response(user)
        from services.integrations.home_assistant import set_light_state
        on_off = "on" in (entities.get("on_off") or entities.get("action") or text or "").lower()
        if "off" in (entities.get("on_off") or entities.get("action") or "").lower():
            on_off = False
        result = set_light_state(room, on_off)
        with _metrics_lock:
            _last_dangerous_action_time = time.time()
        return persona.light_response(
            room, on_off, result.get("ok", False), result.get("error", ""), user
        )

    if intent == "climate_control":
        temp = entities.get("temperature")
        if temp:
            from services.integrations.home_assistant import set_climate
            result = set_climate(int(temp))
            if result.get("ok"):
                return f"Thermostat adjusted to {temp} degrees, {user.preferred_address}."
            return f"I'm unable to reach the climate system at the moment, {user.preferred_address}. {result.get('error', '')}"
        return f"What temperature would you like, {user.preferred_address}?"

    if intent == "lock_control":
        action = entities.get("action", "lock")
        door = entities.get("door", "front")
        with _confirmation_lock:
            _pending_confirmation = {"type": "lock", "action": action, "door": door}
        return persona.confirmation_prompt(f"{action}ing the {door} door", user)

    if intent == "media_control":
        action = entities.get("action")
        media = entities.get("media")
        device = entities.get("device")
        from services.integrations.home_assistant import media_control
        result = media_control(action=action, media=media, device=device)
        if result.get("ok"):
            if media:
                return f"Playing {media}, {user.preferred_address}."
            return f"Done, {user.preferred_address}."
        return f"I couldn't control the media system, {user.preferred_address}. {result.get('error', '')}"

    if intent == "reminder":
        task = entities.get("task") or "something"
        time_str = entities.get("time") or "later"
        try:
            mqtt_client.publish(
                TOPIC_SCHEDULER_ADD,
                json.dumps({"task": task, "time": time_str, "channel": "tts"}),
                qos=1,
            )
            return persona.reminder_response(task, time_str, user)
        except Exception as e:
            LOG.exception("Scheduler publish failed: %s", e)
            return persona.reminder_failed_response(task, time_str, user)

    if intent == "timer":
        duration = entities.get("duration") or "1"
        unit = (entities.get("unit") or "min").lower()[:3]
        try:
            mqtt_client.publish(
                TOPIC_SCHEDULER_ADD,
                json.dumps({"task": "Timer", "duration": int(duration), "unit": unit, "channel": "tts"}),
                qos=1,
            )
            return persona.timer_response(duration, unit, user)
        except Exception:
            return f"I couldn't set the timer, {user.preferred_address}."

    if intent == "time_query":
        return persona.time_response(user)

    if intent == "calendar_query":
        from services.integrations.calendar import get_next_events
        events = get_next_events(limit=5)
        return persona.calendar_response(events, user)

    if intent == "news_query":
        from services.integrations.web_apis import get_news
        result = get_news(limit=5)
        headlines = result.get("headlines", [])
        return persona.news_response(headlines, user)

    if intent == "web_search":
        query = entities.get("query") or text
        try:
            from services.integrations.web_search import search_web
            results = search_web(query)
            return persona.search_response(query, results, user)
        except ImportError:
            return f"Web search is not yet configured, {user.preferred_address}. I'll need a search API integration."

    if intent == "briefing":
        return _morning_briefing(config, user)

    if intent == "cancel":
        with _confirmation_lock:
            _pending_confirmation = None
        return persona.cancel_response(user)

    if intent in _skill_registry:
        try:
            return _skill_registry[intent](text, entities, config, mqtt_client, user)
        except Exception as e:
            LOG.warning("Skill %s failed: %s", intent, e)

    return chat_nlu(text, config)


def _execute_confirmed(
    pending: Dict[str, Any], config, mqtt_client: mqtt.Client, user: UserProfile
) -> str:
    """Execute a previously confirmed action."""
    if pending["type"] == "lock":
        from services.integrations.home_assistant import lock_control
        result = lock_control(pending["action"], pending["door"])
        if result.get("ok"):
            return f"{pending['door'].title()} door {pending['action']}ed, {user.preferred_address}."
        return f"I'm afraid I couldn't {pending['action']} the {pending['door']} door. {result.get('error', '')}"
    return persona.confirmation_accepted(user)


def _morning_briefing(config, user: UserProfile) -> str:
    weather_str = None
    try:
        from services.integrations.web_apis import get_weather
        location = user.location or "London"
        w = get_weather(location)
        weather_str = w.get("summary")
    except Exception:
        pass
    events = []
    try:
        from services.integrations.calendar import get_next_events
        raw = get_next_events(limit=5)
        events = [e.get("summary", "Event") for e in raw if e.get("summary")]
    except Exception:
        pass
    return persona.morning_briefing(user, weather=weather_str, events=events or None)


def on_stt(client: mqtt.Client, userdata, msg) -> None:
    _handle_input(client, userdata, msg)


def on_text_input(client: mqtt.Client, userdata, msg) -> None:
    _handle_input(client, userdata, msg)


def _handle_input(client: mqtt.Client, userdata, msg) -> None:
    global _last_latency_sec
    config = userdata["config"]
    user = _get_user(config)
    correlation_id = f"req_{int(time.time() * 1000)}"
    start = time.time()

    _publish_state(client, "thinking")

    with _metrics_lock:
        _metrics["jarvis_utterances_total"] = _metrics.get("jarvis_utterances_total", 0) + 1
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        text = (payload.get("text") or "").strip()
        if not text:
            if payload.get("error"):
                LOG.debug("Input error: %s", payload.get("error"))
            _publish_state(client, "idle")
            return
        LOG.info("Input received: %s", text[:80], extra={"correlation_id": correlation_id})
        if _memory:
            _memory.add_turn("user", text)

        parsed = parse_nlu(text, config)
        intent = parsed.get("intent") or "general"
        with _metrics_lock:
            _intent_counts[intent] = _intent_counts.get(intent, 0) + 1

        _publish_state(client, "processing")
        response = dispatch_and_respond(text, parsed, config, client)
        if response:
            _publish_state(client, "speaking")
            client.publish(TOPIC_TTS_TEXT, json.dumps({"text": response}), qos=1)
            LOG.info("TTS published: %s", response[:80], extra={"correlation_id": correlation_id})
            if _memory:
                latency = time.time() - start
                _memory.add_turn("assistant", response, intent=intent, latency_sec=latency)
        _last_latency_sec = time.time() - start
    except Exception as e:
        with _metrics_lock:
            _metrics["jarvis_errors_total"] = _metrics.get("jarvis_errors_total", 0) + 1
        LOG.exception("Orchestrator failed: %s", e, extra={"correlation_id": correlation_id})
        try:
            client.publish(
                TOPIC_TTS_TEXT,
                json.dumps({"text": persona.error_response(user)}),
                qos=1,
            )
        except Exception:
            pass
    finally:
        _last_latency_sec = time.time() - start
        _publish_state(client, "idle")


def _metrics_handler() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/metrics":
                with _metrics_lock:
                    lines = [
                        "# HELP jarvis_utterances_total Total utterances processed",
                        "# TYPE jarvis_utterances_total counter",
                        f"jarvis_utterances_total {_metrics.get('jarvis_utterances_total', 0)}",
                        "# HELP jarvis_errors_total Total errors",
                        "# TYPE jarvis_errors_total counter",
                        f"jarvis_errors_total {_metrics.get('jarvis_errors_total', 0)}",
                        "# HELP jarvis_last_latency_seconds Last request latency",
                        "# TYPE jarvis_last_latency_seconds gauge",
                        f"jarvis_last_latency_seconds {_last_latency_sec}",
                    ]
                    for intent, count in _intent_counts.items():
                        lines.append(f'jarvis_intent_total{{intent="{intent}"}} {count}')
                body = "\n".join(lines) + "\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))
            elif self.path == "/health":
                body = '{"status":"ok","service":"orchestrator"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            LOG.debug("Metrics %s", args[0] if args else "")

    server = HTTPServer(("0.0.0.0", 8002), Handler)
    server.serve_forever()


def main() -> None:
    config = load_config()
    configure_logging(config.log_level, "orchestrator")
    t = threading.Thread(target=_metrics_handler, daemon=True)
    t.start()

    from jarvis_core.mqtt_helpers import create_client
    client = create_client(
        config,
        "orchestrator",
        subscriptions=[(TOPIC_STT_TEXT, 1), (TOPIC_TEXT_INPUT, 1)],
    )
    client.user_data_set({"config": config})
    client.message_callback_add(TOPIC_STT_TEXT, on_stt)
    client.message_callback_add(TOPIC_TEXT_INPUT, on_text_input)
    user = _get_user(config)
    LOG.info(
        "J.A.R.V.I.S. orchestrator online. Addressing user as '%s'. Metrics on :8002",
        user.preferred_address,
    )
    client.loop_forever()


if __name__ == "__main__":
    main()
