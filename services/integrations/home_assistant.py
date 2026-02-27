"""Home Assistant REST + MQTT integration. Set HASS_TOKEN and base_url in config."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any, Generator, Optional

import httpx

from jarvis_core import load_config


@contextmanager
def _client() -> Generator[Optional[httpx.Client], None, None]:
    config = getattr(load_config(), "home_assistant", None)
    if not config:
        yield None
        return
    base = getattr(config, "base_url", "").rstrip("/")
    token = os.getenv(getattr(config, "token_env_var", "HASS_TOKEN"), "").strip()
    if not base or not token:
        yield None
        return
    with httpx.Client(
        base_url=base,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=10.0,
    ) as c:
        yield c


def set_light_state(room: str, on_off: bool, brightness: Optional[int] = None) -> dict[str, Any]:
    """Turn a light on/off. room can be entity_id (e.g. light.living_room) or a name mapped in config."""
    config = load_config().home_assistant
    entity_id = getattr(config, "default_light_entity", "light.living_room")
    if room and room != "default":
        entity_id = f"light.{room.replace(' ', '_').lower()}" if not room.startswith("light.") else room
    service = "turn_on" if on_off else "turn_off"
    data: dict[str, Any] = {"entity_id": entity_id}
    if on_off and brightness is not None:
        data["brightness_pct"] = min(100, max(0, brightness))
    with _client() as client:
        if client is None:
            return {"ok": False, "error": "Home Assistant not configured"}
        r = client.post(f"/api/services/light/{service}", json=data)
        if r.is_success:
            return {"ok": True, "entity_id": entity_id}
        return {"ok": False, "error": r.text}


def get_light_state(room: str) -> dict[str, Any]:
    """Get state of a light."""
    config = load_config().home_assistant
    entity_id = getattr(config, "default_light_entity", "light.living_room")
    if room and room != "default":
        entity_id = f"light.{room.replace(' ', '_').lower()}" if not room.startswith("light.") else room
    with _client() as client:
        if client is None:
            return {"state": "unknown", "error": "Home Assistant not configured"}
        r = client.get(f"/api/states/{entity_id}")
        if not r.is_success:
            return {"state": "unknown", "error": r.text}
        data = r.json()
        return {"state": data.get("state"), "attributes": data.get("attributes", {})}


def publish_light_mqtt(room: str, on_off: bool, brightness: Optional[int] = None) -> dict[str, Any]:
    """
    Publish light command to MQTT (e.g. home/room/light/set with payload ON/OFF).
    Requires orchestrator or caller to pass an MQTT client, or use env MQTT_* for a dedicated client.
    """
    try:
        import paho.mqtt.client as mqtt
        from jarvis_core import load_config
        cfg = load_config().mqtt
        topic = f"home/{room.replace(' ', '_').lower()}/light/set" if room else "home/light/set"
        payload = "ON" if on_off else "OFF"
        if on_off and brightness is not None:
            payload = json.dumps({"state": "ON", "brightness": min(255, max(0, int(brightness * 2.55)))})
        c = mqtt.Client(client_id=f"{cfg.client_id_prefix}-ha-mqtt")
        if cfg.username:
            c.username_pw_set(cfg.username, cfg.password)
        c.connect(cfg.host, cfg.port, 60)
        c.publish(topic, payload, qos=1)
        c.disconnect()
        return {"ok": True, "topic": topic}
    except Exception as e:
        return {"ok": False, "error": str(e)}
