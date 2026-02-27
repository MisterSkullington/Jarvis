"""
Proactive briefings service for J.A.R.V.I.S.

Monitors time-based triggers (morning briefing, calendar alerts) and
publishes proactive messages to TTS and UI.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import paho.mqtt.client as mqtt
from apscheduler.schedulers.background import BackgroundScheduler

from jarvis_core import load_config, configure_logging
from jarvis_core.persona import UserProfile
import jarvis_core.persona as persona

LOG = logging.getLogger(__name__)

TOPIC_TTS_TEXT = "jarvis/tts/text"
TOPIC_STATUS = "jarvis/status/proactive"
TOPIC_UI_NOTIFICATION = "jarvis/ui/notification"

_mqtt_client: mqtt.Client | None = None


def _get_user(config) -> UserProfile:
    u = getattr(config, "user", None)
    if u:
        return UserProfile(
            name=getattr(u, "name", "Sir"),
            preferred_address=getattr(u, "preferred_address", "sir"),
            location=getattr(u, "location", ""),
        )
    return UserProfile()


def _say(text: str) -> None:
    if _mqtt_client:
        _mqtt_client.publish(TOPIC_TTS_TEXT, json.dumps({"text": text}), qos=1)


def _notify(title: str, body: str) -> None:
    if _mqtt_client:
        _mqtt_client.publish(
            TOPIC_UI_NOTIFICATION,
            json.dumps({"title": title, "body": body, "timestamp": time.time()}),
            qos=0,
        )


def morning_briefing_job() -> None:
    config = load_config()
    user = _get_user(config)
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
    briefing = persona.morning_briefing(user, weather=weather_str, events=events or None)
    _say(briefing)
    _notify("Morning Briefing", briefing[:200])
    LOG.info("Morning briefing delivered")


def calendar_alert_job() -> None:
    config = load_config()
    user = _get_user(config)
    try:
        from services.integrations.calendar import get_next_events
        events = get_next_events(limit=3)
        if events:
            alert_min = getattr(config.proactive, "calendar_alert_minutes_before", 10)
            now = datetime.now()
            for event in events:
                summary = event.get("summary", "Event")
                _notify("Calendar", f"Upcoming: {summary}")
    except Exception as e:
        LOG.debug("Calendar alert check failed: %s", e)


def main() -> None:
    global _mqtt_client
    config = load_config()
    configure_logging(config.log_level, "proactive")

    if not getattr(config.proactive, "enabled", True):
        LOG.info("Proactive service disabled in config")
        return

    client = mqtt.Client(client_id=f"{config.mqtt.client_id_prefix}-proactive")
    if config.mqtt.username:
        client.username_pw_set(config.mqtt.username, config.mqtt.password)
    client.connect(config.mqtt.host, config.mqtt.port, 60)
    client.loop_start()
    _mqtt_client = client

    scheduler = BackgroundScheduler()

    briefing_hour = getattr(config.proactive, "morning_briefing_hour", 8)
    briefing_min = getattr(config.proactive, "morning_briefing_minute", 0)
    scheduler.add_job(
        morning_briefing_job, "cron",
        hour=briefing_hour, minute=briefing_min,
        id="morning_briefing",
    )

    scheduler.add_job(
        calendar_alert_job, "interval",
        minutes=5, id="calendar_alert",
    )

    scheduler.start()
    client.publish(TOPIC_STATUS, json.dumps({"status": "ready"}), qos=0)
    LOG.info(
        "Proactive service ready. Morning briefing at %02d:%02d",
        briefing_hour, briefing_min,
    )

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.shutdown()
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
