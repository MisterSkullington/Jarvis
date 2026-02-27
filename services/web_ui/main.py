"""
J.A.R.V.I.S. Web HUD — holographic-style dashboard.

Serves the web UI and provides WebSocket bridge to MQTT for real-time updates.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Set

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import paho.mqtt.client as mqtt
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from jarvis_core import load_config, configure_logging

LOG = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
app = FastAPI(title="J.A.R.V.I.S. HUD", version="0.2.0")

_ws_clients: Set[WebSocket] = set()
_ws_lock = threading.Lock()
_mqtt_client: mqtt.Client | None = None

MQTT_SUBSCRIBE_TOPICS = [
    ("jarvis/tts/text", 0),
    ("jarvis/stt/text", 0),
    ("jarvis/ui/state", 0),
    ("jarvis/status/#", 0),
]


async def _broadcast(data: dict) -> None:
    """Send JSON to all connected WebSocket clients."""
    message = json.dumps(data)
    with _ws_lock:
        clients = list(_ws_clients)
    for ws in clients:
        try:
            await ws.send_text(message)
        except Exception:
            with _ws_lock:
                _ws_clients.discard(ws)


def _on_mqtt_message(client: mqtt.Client, userdata, msg) -> None:
    """Forward MQTT messages to WebSocket clients."""
    try:
        payload = msg.payload.decode("utf-8")
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = {"raw": payload}
        data["_topic"] = msg.topic
        data["_ts"] = time.time()
        loop = userdata.get("loop")
        if loop and _ws_clients:
            asyncio.run_coroutine_threadsafe(_broadcast(data), loop)
    except Exception as e:
        LOG.debug("MQTT->WS forward error: %s", e)


def _start_mqtt(config, loop: asyncio.AbstractEventLoop) -> mqtt.Client:
    client = mqtt.Client(client_id=f"{config.mqtt.client_id_prefix}-webui")
    if config.mqtt.username:
        client.username_pw_set(config.mqtt.username, config.mqtt.password)
    client.user_data_set({"loop": loop})
    client.on_message = _on_mqtt_message
    client.connect(config.mqtt.host, config.mqtt.port, 60)
    for topic, qos in MQTT_SUBSCRIBE_TOPICS:
        client.subscribe(topic, qos)
    client.loop_start()
    return client


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>J.A.R.V.I.S. HUD</h1><p>Static files not found.</p>")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    with _ws_lock:
        _ws_clients.add(ws)
    LOG.info("WebSocket client connected (%d total)", len(_ws_clients))
    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                topic = msg.get("topic", "jarvis/text/input")
                payload = msg.get("payload", data)
                if _mqtt_client:
                    _mqtt_client.publish(topic, json.dumps(payload) if isinstance(payload, dict) else str(payload), qos=1)
            except json.JSONDecodeError:
                if _mqtt_client:
                    _mqtt_client.publish("jarvis/text/input", json.dumps({"text": data}), qos=1)
    except WebSocketDisconnect:
        pass
    finally:
        with _ws_lock:
            _ws_clients.discard(ws)
        LOG.info("WebSocket client disconnected (%d remaining)", len(_ws_clients))


@app.get("/health")
async def health():
    return {"status": "ok", "service": "web_ui"}


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def main() -> None:
    global _mqtt_client
    config = load_config()
    configure_logging(config.log_level, "web_ui")
    loop = asyncio.new_event_loop()

    def run_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    t = threading.Thread(target=run_loop, daemon=True)
    t.start()

    _mqtt_client = _start_mqtt(config, loop)

    host = getattr(config.web_ui, "host", "0.0.0.0")
    port = getattr(config.web_ui, "port", 8080)
    LOG.info("J.A.R.V.I.S. HUD starting on http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
