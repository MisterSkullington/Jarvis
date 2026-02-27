"""
MQTT helper utilities: auto-reconnect, connection callbacks.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Callable, List, Optional, Tuple

import paho.mqtt.client as mqtt

LOG = logging.getLogger(__name__)


def create_client(
    config,
    client_id_suffix: str,
    subscriptions: Optional[List[Tuple[str, int]]] = None,
    on_connect_extra: Optional[Callable] = None,
) -> mqtt.Client:
    """
    Create an MQTT client with auto-reconnect and standard callbacks.

    Returns a connected client with loop not yet started.
    """
    prefix = getattr(config.mqtt, "client_id_prefix", "jarvis")
    client = mqtt.Client(client_id=f"{prefix}-{client_id_suffix}")

    if config.mqtt.username:
        client.username_pw_set(config.mqtt.username, config.mqtt.password)

    client.reconnect_delay_set(min_delay=1, max_delay=30)

    def on_connect(client, userdata, flags, rc, *args):
        if rc == 0:
            LOG.info("MQTT connected (%s)", client_id_suffix)
            if subscriptions:
                for topic, qos in subscriptions:
                    client.subscribe(topic, qos)
                    LOG.debug("Subscribed to %s (qos=%d)", topic, qos)
            status_topic = f"jarvis/status/{client_id_suffix}"
            client.publish(status_topic, json.dumps({"status": "ready"}), qos=0)
            if on_connect_extra:
                on_connect_extra(client, userdata, flags, rc)
        else:
            LOG.warning("MQTT connect failed with rc=%d (%s)", rc, client_id_suffix)

    def on_disconnect(client, userdata, rc, *args):
        if rc != 0:
            LOG.warning("MQTT disconnected unexpectedly (%s), will auto-reconnect", client_id_suffix)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    retries = 0
    max_retries = 5
    while retries < max_retries:
        try:
            client.connect(config.mqtt.host, config.mqtt.port, 60)
            return client
        except Exception as e:
            retries += 1
            wait = min(2 ** retries, 30)
            LOG.warning(
                "MQTT connect attempt %d/%d failed: %s. Retrying in %ds...",
                retries, max_retries, e, wait,
            )
            time.sleep(wait)

    LOG.error("Failed to connect to MQTT after %d attempts", max_retries)
    client.connect(config.mqtt.host, config.mqtt.port, 60)
    return client
