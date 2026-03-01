"""
Service health monitor for J.A.R.V.I.S.

Subscribes to jarvis/status/# and tracks which services are alive.
Publishes alerts when services go offline.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import paho.mqtt.client as mqtt

from jarvis_core import load_config, configure_logging

LOG = logging.getLogger(__name__)

TOPIC_STATUS_WILDCARD = "jarvis/status/#"
TOPIC_TTS_TEXT = "jarvis/tts/text"
TOPIC_UI_NOTIFICATION = "jarvis/ui/notification"
TOPIC_MONITOR_STATUS = "jarvis/status/monitor"

EXPECTED_SERVICES = ["orchestrator", "nlu_agent", "tts", "scheduler"]
TIMEOUT_SEC = 120

_service_last_seen: Dict[str, float] = {}
_alerted: Dict[str, bool] = {}


def on_status(client: mqtt.Client, userdata, msg) -> None:
    service = msg.topic.split("/")[-1]
    _service_last_seen[service] = time.time()
    if _alerted.get(service):
        _alerted[service] = False
        LOG.info("Service %s is back online", service)
        client.publish(
            TOPIC_UI_NOTIFICATION,
            json.dumps({"title": "Service Online", "body": f"{service} is back online.", "timestamp": time.time()}),
            qos=0,
        )


def check_health(client: mqtt.Client) -> None:
    now = time.time()
    for service in EXPECTED_SERVICES:
        last = _service_last_seen.get(service, 0)
        if now - last > TIMEOUT_SEC and not _alerted.get(service):
            _alerted[service] = True
            LOG.warning("Service %s appears offline (no status in %ds)", service, TIMEOUT_SEC)
            client.publish(
                TOPIC_UI_NOTIFICATION,
                json.dumps({
                    "title": "Service Offline",
                    "body": f"{service} has not reported in {TIMEOUT_SEC}s.",
                    "level": "warning",
                    "timestamp": now,
                }),
                qos=0,
            )


def main() -> None:
    config = load_config()
    configure_logging(config.log_level, "monitor")
    client = mqtt.Client(client_id=f"{config.mqtt.client_id_prefix}-monitor")
    if config.mqtt.username:
        client.username_pw_set(config.mqtt.username, config.mqtt.password)
    client.connect(config.mqtt.host, config.mqtt.port, 60)
    client.subscribe(TOPIC_STATUS_WILDCARD, qos=0)
    client.on_message = on_status
    client.loop_start()
    client.publish(TOPIC_MONITOR_STATUS, json.dumps({"status": "ready"}), qos=0)
    LOG.info("Health monitor ready. Watching: %s", ", ".join(EXPECTED_SERVICES))

    try:
        while True:
            time.sleep(30)
            check_health(client)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
