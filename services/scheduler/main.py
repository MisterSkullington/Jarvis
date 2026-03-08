"""
Scheduler service: subscribe to jarvis/scheduler/add (task, time or duration, channel),
schedule with APScheduler (SQLite job store), and publish reminder text to jarvis/tts/text.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import dateparser
import paho.mqtt.client as mqtt
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore as SQLAlchemyJobstore

from jarvis_core import load_config, configure_logging, make_mqtt_client

LOG = logging.getLogger(__name__)

TOPIC_SCHEDULER_ADD = "jarvis/scheduler/add"
TOPIC_TTS_TEXT = "jarvis/tts/text"
TOPIC_STATUS = "jarvis/status/scheduler"

JOBSTORE_PATH = Path(__file__).resolve().parents[2] / "data" / "scheduler.db"
JOBSTORE_PATH.parent.mkdir(parents=True, exist_ok=True)

_scheduler: BackgroundScheduler | None = None
_mqtt_client: mqtt.Client | None = None


def _tts_say(text: str) -> None:
    if _mqtt_client:
        _mqtt_client.publish(TOPIC_TTS_TEXT, json.dumps({"text": text}), qos=1)
        LOG.info("Scheduler TTS: %s", text[:80])


def _remind_job(task: str) -> None:
    _tts_say(f"Reminder: {task}")


def _timer_job() -> None:
    _tts_say("Your timer is up.")


def _add_reminder(task: str, run_at: datetime) -> None:
    global _scheduler
    if not _scheduler:
        return
    _scheduler.add_job(_remind_job, "date", run_date=run_at, args=[task], id=f"rem_{run_at.timestamp()}")
    LOG.info("Scheduled reminder %s at %s", task, run_at.isoformat())


def _add_timer(duration_sec: int) -> None:
    global _scheduler
    if not _scheduler:
        return
    run_at = datetime.now() + timedelta(seconds=duration_sec)
    _scheduler.add_job(_timer_job, "date", run_date=run_at, id=f"timer_{run_at.timestamp()}")
    LOG.info("Timer set for %s seconds", duration_sec)


def on_scheduler_add(client: mqtt.Client, userdata, msg) -> None:
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        task = payload.get("task") or "Reminder"
        channel = payload.get("channel") or "tts"
        time_str = payload.get("time")
        duration = payload.get("duration")
        unit = (payload.get("unit") or "min").lower()[:3]
        if time_str:
            run_at = dateparser.parse(time_str)
            if run_at:
                _add_reminder(task, run_at)
            else:
                LOG.warning("Could not parse time: %s", time_str)
        elif duration is not None:
            sec = int(duration)
            if "hour" in unit or unit == "hou":
                sec *= 3600
            elif "min" in unit or unit == "min":
                sec *= 60
            _add_timer(sec)
    except Exception as e:
        LOG.exception("Scheduler add failed: %s", e)


def main() -> None:
    global _scheduler, _mqtt_client
    config = load_config()
    configure_logging(config.log_level, "scheduler")
    jobstore = SQLAlchemyJobstore(url=f"sqlite:///{JOBSTORE_PATH}")
    _scheduler = BackgroundScheduler(jobstores={"default": jobstore})
    _scheduler.start()
    client = make_mqtt_client(config, "scheduler")
    client.connect(config.mqtt.host, config.mqtt.port, 60)
    client.subscribe(TOPIC_SCHEDULER_ADD, qos=1)
    client.message_callback_add(TOPIC_SCHEDULER_ADD, on_scheduler_add)
    _mqtt_client = client
    client.publish(TOPIC_STATUS, json.dumps({"status": "ready"}), qos=0)
    LOG.info("Scheduler ready; subscribed to %s", TOPIC_SCHEDULER_ADD)
    client.loop_forever()


if __name__ == "__main__":
    main()
