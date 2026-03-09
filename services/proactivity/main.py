"""
Proactivity service (Phase 3).

Monitors the calendar and time, then proactively announces upcoming events
and delivers an optional morning brief via TTS — all without any user prompt.

MQTT topics:
  Publishes: jarvis/tts/text, jarvis/status/proactivity

Config: proactivity section in jarvis.example.yaml
  enabled, reminder_minutes, morning_brief_enabled, morning_brief_time, timezone
"""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Set

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import paho.mqtt.client as mqtt
from apscheduler.schedulers.background import BackgroundScheduler

from jarvis_core import load_config, configure_logging, make_mqtt_client, get_honorific

LOG = logging.getLogger(__name__)

TOPIC_TTS = "jarvis/tts/text"
TOPIC_STATUS = "jarvis/status/proactivity"

# Track which events have already been announced to avoid repeat notifications
_announced: Set[str] = set()
_announced_lock = threading.Lock()
_mqtt_client: mqtt.Client | None = None


def _say(text: str) -> None:
    if _mqtt_client:
        _mqtt_client.publish(TOPIC_TTS, json.dumps({"text": text}), qos=1)
        LOG.info("Proactivity TTS: %s", text[:80])


def _parse_event_dt(raw: str) -> datetime | None:
    """Parse YYYYMMDD or YYYYMMDDTHHMMSS into a datetime."""
    raw = raw.replace("Z", "").replace("+00:00", "")
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(raw[:len(fmt.replace("%", "XX").replace("X", ""))], fmt)
        except ValueError:
            continue
    return None


def _check_calendar_reminders(config) -> None:
    """Check for events starting within reminder_minutes and announce them."""
    from services.integrations.calendar import get_next_events
    try:
        events = get_next_events(limit=10)
    except Exception as exc:
        LOG.warning("Proactivity calendar check failed: %s", exc)
        return

    reminder_min = getattr(config.proactivity, "reminder_minutes", 10)
    now = datetime.now()
    window = timedelta(minutes=reminder_min)

    for ev in events:
        start_raw = ev.get("start", "")
        if not start_raw:
            continue
        dt = _parse_event_dt(start_raw)
        if dt is None:
            continue

        delta = dt - now
        # Announce if the event starts within the window and hasn't been announced yet
        event_key = f"{ev.get('summary','')}_{start_raw}"
        if timedelta(0) <= delta <= window:
            with _announced_lock:
                if event_key not in _announced:
                    summary = ev.get("summary", "an event")
                    mins_away = max(1, int(delta.total_seconds() / 60))
                    _say(f"Sir, your upcoming event '{summary}' starts in {mins_away} minute{'s' if mins_away != 1 else ''}.")
                    _announced.add(event_key)

    # Expire old announced keys (events more than 1 hour past)
    with _announced_lock:
        for key in list(_announced):
            try:
                ts = key.rsplit("_", 1)[-1]
                dt = _parse_event_dt(ts)
                if dt and datetime.now() - dt > timedelta(hours=1):
                    _announced.discard(key)
            except Exception:
                pass


def _morning_brief(config) -> None:
    """Deliver a morning brief: time, calendar events, optional weather."""
    from services.integrations.calendar import get_next_events
    from services.integrations.web_apis import get_weather

    honorific = get_honorific(config)
    now = datetime.now()
    greeting = f"Good morning, {honorific}. It is {now.strftime('%A, %B %d')} and the time is {now.strftime('%H:%M')}."
    _say(greeting)
    time.sleep(1)

    # Calendar
    try:
        events = get_next_events(limit=3)
        if events:
            lines = [f"{e.get('summary','?')} at {e.get('start','?')}" for e in events]
            _say(f"Today you have {len(events)} event{'s' if len(events)!=1 else ''}: " + "; ".join(lines) + ".")
        else:
            _say(f"Your calendar is clear today, {honorific}.")
    except Exception as exc:
        LOG.warning("Morning brief calendar failed: %s", exc)

    time.sleep(0.5)

    # Weather (best-effort)
    try:
        weather = get_weather("here")
        summary = weather.get("summary", "")
        if summary and "not configured" not in summary.lower():
            _say(f"The weather: {summary}.")
    except Exception:
        pass


def main() -> None:
    global _mqtt_client

    config = load_config()
    configure_logging(config.log_level, "proactivity")

    if not config.proactivity.enabled:
        LOG.info("Proactivity service is disabled (proactivity.enabled: false). Exiting.")
        return

    _mqtt_client = make_mqtt_client(config, "proactivity")
    _mqtt_client.connect(config.mqtt.host, config.mqtt.port, 60)
    _mqtt_client.loop_start()
    _mqtt_client.publish(TOPIC_STATUS, json.dumps({"status": "ready"}), qos=0)

    scheduler = BackgroundScheduler()

    # Calendar reminder check every 60 seconds
    scheduler.add_job(
        _check_calendar_reminders,
        "interval",
        seconds=60,
        args=[config],
        id="calendar_reminders",
    )

    # Morning brief (cron)
    if config.proactivity.morning_brief_enabled:
        try:
            h, m = config.proactivity.morning_brief_time.split(":")
            scheduler.add_job(
                _morning_brief,
                "cron",
                hour=int(h),
                minute=int(m),
                args=[config],
                id="morning_brief",
            )
            LOG.info("Morning brief scheduled at %s", config.proactivity.morning_brief_time)
        except Exception as exc:
            LOG.warning("Could not schedule morning brief: %s", exc)

    scheduler.start()
    LOG.info(
        "Proactivity service ready. Calendar reminders every 60s; "
        "morning brief %s.",
        "enabled" if config.proactivity.morning_brief_enabled else "disabled",
    )

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.shutdown()
        _mqtt_client.loop_stop()
        _mqtt_client.disconnect()


if __name__ == "__main__":
    main()
