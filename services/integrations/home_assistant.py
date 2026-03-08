"""
Home Assistant integration: lights, climate, locks, scenes, media, and generic service calls.
Set HASS_TOKEN and base_url in config.
"""
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


def _not_configured() -> dict[str, Any]:
    return {"ok": False, "error": "Home Assistant not configured"}


# ---------------------------------------------------------------------------
# Lights
# ---------------------------------------------------------------------------

def set_light_state(room: str, on_off: bool, brightness: Optional[int] = None) -> dict[str, Any]:
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
            return _not_configured()
        r = client.post(f"/api/services/light/{service}", json=data)
        if r.is_success:
            return {"ok": True, "entity_id": entity_id}
        return {"ok": False, "error": r.text}


def get_light_state(room: str) -> dict[str, Any]:
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


# ---------------------------------------------------------------------------
# Climate / Thermostat
# ---------------------------------------------------------------------------

def set_climate(temperature: int, entity_id: str = "climate.thermostat") -> dict[str, Any]:
    with _client() as client:
        if client is None:
            return _not_configured()
        r = client.post(
            "/api/services/climate/set_temperature",
            json={"entity_id": entity_id, "temperature": temperature},
        )
        if r.is_success:
            return {"ok": True, "entity_id": entity_id, "temperature": temperature}
        return {"ok": False, "error": r.text}


def get_climate(entity_id: str = "climate.thermostat") -> dict[str, Any]:
    with _client() as client:
        if client is None:
            return _not_configured()
        r = client.get(f"/api/states/{entity_id}")
        if not r.is_success:
            return {"state": "unknown", "error": r.text}
        data = r.json()
        attrs = data.get("attributes", {})
        return {
            "state": data.get("state"),
            "current_temperature": attrs.get("current_temperature"),
            "target_temperature": attrs.get("temperature"),
        }


# ---------------------------------------------------------------------------
# Locks
# ---------------------------------------------------------------------------

def lock_control(action: str, door: str = "front") -> dict[str, Any]:
    entity_id = f"lock.{door.replace(' ', '_').lower()}" if not door.startswith("lock.") else door
    service = "lock" if action.lower() in ("lock", "close") else "unlock"
    with _client() as client:
        if client is None:
            return _not_configured()
        r = client.post(f"/api/services/lock/{service}", json={"entity_id": entity_id})
        if r.is_success:
            return {"ok": True, "entity_id": entity_id, "action": service}
        return {"ok": False, "error": r.text}


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------

def activate_scene(scene_name: str) -> dict[str, Any]:
    entity_id = f"scene.{scene_name.replace(' ', '_').lower()}" if not scene_name.startswith("scene.") else scene_name
    with _client() as client:
        if client is None:
            return _not_configured()
        r = client.post("/api/services/scene/turn_on", json={"entity_id": entity_id})
        if r.is_success:
            return {"ok": True, "scene": entity_id}
        return {"ok": False, "error": r.text}


# ---------------------------------------------------------------------------
# Media Player
# ---------------------------------------------------------------------------

def media_control(
    action: Optional[str] = None,
    media: Optional[str] = None,
    device: Optional[str] = None,
) -> dict[str, Any]:
    entity_id = f"media_player.{device.replace(' ', '_').lower()}" if device and not device.startswith("media_player.") else (device or "media_player.default")
    with _client() as client:
        if client is None:
            return _not_configured()
        if action and action.lower() in ("pause", "stop"):
            r = client.post("/api/services/media_player/media_pause", json={"entity_id": entity_id})
            return {"ok": r.is_success} if r.is_success else {"ok": False, "error": r.text}
        if action and action.lower() in ("resume", "play"):
            r = client.post("/api/services/media_player/media_play", json={"entity_id": entity_id})
            return {"ok": r.is_success} if r.is_success else {"ok": False, "error": r.text}
        if action and action.lower() in ("next", "skip"):
            r = client.post("/api/services/media_player/media_next_track", json={"entity_id": entity_id})
            return {"ok": r.is_success} if r.is_success else {"ok": False, "error": r.text}
        if action and action.lower() == "previous":
            r = client.post("/api/services/media_player/media_previous_track", json={"entity_id": entity_id})
            return {"ok": r.is_success} if r.is_success else {"ok": False, "error": r.text}
        if media:
            r = client.post(
                "/api/services/media_player/play_media",
                json={"entity_id": entity_id, "media_content_id": media, "media_content_type": "music"},
            )
            return {"ok": r.is_success} if r.is_success else {"ok": False, "error": r.text}
        return {"ok": False, "error": "No action or media specified"}


# ---------------------------------------------------------------------------
# MQTT-based light control (direct MQTT, no HA API)
# ---------------------------------------------------------------------------

def publish_light_mqtt(room: str, on_off: bool, brightness: Optional[int] = None) -> dict[str, Any]:
    try:
        import paho.mqtt.client as mqtt
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
