"""
Orchestrator: subscribe to jarvis/stt/text, call NLU /parse and /chat, run integrations, publish jarvis/tts/text.
Exposes /metrics (Prometheus-style) and applies rate limiting for sensitive actions.
"""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx
import paho.mqtt.client as mqtt

from jarvis_core import load_config, configure_logging

LOG = logging.getLogger(__name__)

TOPIC_STT_TEXT = "jarvis/stt/text"
TOPIC_TTS_TEXT = "jarvis/tts/text"
TOPIC_SCHEDULER_ADD = "jarvis/scheduler/add"
TOPIC_STATUS = "jarvis/status/orchestrator"

# In-memory metrics (Prometheus-style)
_metrics: Dict[str, float] = {"jarvis_utterances_total": 0, "jarvis_errors_total": 0}
_metrics_lock = threading.Lock()
_last_latency_sec: float = 0.0
_last_dangerous_action_time: float = 0.0
_intent_counts: Dict[str, int] = {}


def parse_nlu(text: str, config) -> dict:
    """Call NLU agent /parse."""
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
    """Call NLU agent /chat for open-ended response."""
    base = config.nlu_agent.base_url.rstrip("/")
    try:
        with httpx.Client(timeout=config.nlu_agent.timeout_seconds) as client:
            r = client.post(f"{base}/chat", json={"text": text})
            if r.is_success:
                data = r.json()
                return (data.get("response") or "").strip()
    except Exception as e:
        LOG.warning("NLU chat failed: %s", e)
    return "I'm having trouble connecting to the assistant."


def dispatch_and_respond(text: str, parsed: dict, config, mqtt_client: mqtt.Client) -> str:
    """Run integrations by intent and return response text. Publish to TTS."""
    global _last_dangerous_action_time
    intent = parsed.get("intent") or "general"
    entities = parsed.get("entities") or {}

    if intent == "greet":
        return "Hello. How can I help you today?"

    if intent == "weather":
        from services.integrations.web_apis import get_weather
        location = entities.get("location") or "here"
        info = get_weather(location)
        summary = info.get("summary", "Unknown")
        return f"The weather in {location} is {summary}."

    if intent == "light_control":
        # Rate limit sensitive actions
        rate_limit_sec = getattr(config.safety, "dangerous_actions_rate_limit_seconds", 30)
        if time.time() - _last_dangerous_action_time < rate_limit_sec:
            return "Please wait a moment before another smart home command."
        from services.integrations.home_assistant import set_light_state
        room = entities.get("room") or "default"
        on_off = "on" in (entities.get("on_off") or entities.get("action") or text or "").lower()
        if "off" in (entities.get("on_off") or entities.get("action") or "").lower():
            on_off = False
        result = set_light_state(room, on_off)
        with _metrics_lock:
            _last_dangerous_action_time = time.time()
        if result.get("ok"):
            return f"Turning {'on' if on_off else 'off'} the {room} lights."
        return result.get("error", "Could not control the lights.")

    if intent == "reminder":
        task = entities.get("task") or "something"
        time_str = entities.get("time") or "later"
        try:
            mqtt_client.publish(
                TOPIC_SCHEDULER_ADD,
                json.dumps({"task": task, "time": time_str, "channel": "tts"}),
                qos=1,
            )
            return f"Reminder set for {task} at {time_str}."
        except Exception as e:
            LOG.exception("Scheduler publish failed: %s", e)
            return f"I'll try to remind you for {task} at {time_str}. The scheduler may not be running."

    if intent == "timer":
        duration = entities.get("duration") or "1"
        unit = (entities.get("unit") or "min").lower()[:3]
        try:
            mqtt_client.publish(
                TOPIC_SCHEDULER_ADD,
                json.dumps({"task": "Timer", "duration": int(duration), "unit": unit, "channel": "tts"}),
                qos=1,
            )
            return f"Timer set for {duration} {unit}."
        except Exception as e:
            return "I couldn't set the timer."

    if intent == "time_query":
        import datetime
        now = datetime.datetime.now().strftime("%H:%M")
        return f"The time is {now}."

    if intent == "cancel":
        return "Cancelled."

    # Fallback: use chat endpoint for general/conversational
    return chat_nlu(text, config)


def on_stt(client: mqtt.Client, userdata, msg) -> None:
    global _last_latency_sec
    config = userdata["config"]
    correlation_id = f"req_{int(time.time() * 1000)}"
    start = time.time()
    with _metrics_lock:
        _metrics["jarvis_utterances_total"] = _metrics.get("jarvis_utterances_total", 0) + 1
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        text = (payload.get("text") or "").strip()
        if not text:
            if payload.get("error"):
                LOG.debug("STT error: %s", payload.get("error"))
            return
        LOG.info("STT received: %s", extra={"correlation_id": correlation_id})
        parsed = parse_nlu(text, config)
        intent = parsed.get("intent") or "general"
        with _metrics_lock:
            _intent_counts[intent] = _intent_counts.get(intent, 0) + 1
        response = dispatch_and_respond(text, parsed, config, client)
        if response:
            client.publish(TOPIC_TTS_TEXT, json.dumps({"text": response}), qos=1)
            LOG.info("TTS published: %s", response[:80], extra={"correlation_id": correlation_id})
        _last_latency_sec = time.time() - start
    except Exception as e:
        with _metrics_lock:
            _metrics["jarvis_errors_total"] = _metrics.get("jarvis_errors_total", 0) + 1
        LOG.exception("Orchestrator failed: %s", e, extra={"correlation_id": correlation_id})
        try:
            client.publish(TOPIC_TTS_TEXT, json.dumps({"text": "Something went wrong. Please try again."}), qos=1)
        except Exception:
            pass
    finally:
        _last_latency_sec = time.time() - start


def _metrics_handler() -> None:
    """Run HTTP server for /metrics (Prometheus-style) on port 8002."""
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
    client = mqtt.Client(client_id=f"{config.mqtt.client_id_prefix}-orchestrator")
    if config.mqtt.username:
        client.username_pw_set(config.mqtt.username, config.mqtt.password)
    client.user_data_set({"config": config})
    client.connect(config.mqtt.host, config.mqtt.port, 60)
    client.subscribe(TOPIC_STT_TEXT, qos=1)
    client.message_callback_add(TOPIC_STT_TEXT, on_stt)
    client.publish(TOPIC_STATUS, json.dumps({"status": "ready"}), qos=0)
    LOG.info("Orchestrator ready; subscribed to %s; metrics on :8002/metrics", TOPIC_STT_TEXT)
    client.loop_forever()


if __name__ == "__main__":
    main()
