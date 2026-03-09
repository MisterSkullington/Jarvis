"""
MQTT client factory with auto-reconnect, re-subscription, and optional TLS support.
All services should use make_mqtt_client() for consistent configuration.
"""
from __future__ import annotations

import logging
from typing import List, Tuple

import paho.mqtt.client as mqtt

LOG = logging.getLogger(__name__)


def make_mqtt_client(config, suffix: str) -> mqtt.Client:
    """
    Create a configured MQTT client with auto-reconnect and logging.

    Applies:
      - client_id from config.mqtt.client_id_prefix + suffix
      - username/password if set
      - TLS if config.mqtt.tls is True (uses ca_certs / certfile / keyfile if provided)
      - Exponential back-off reconnect (1-30 s)
      - on_disconnect logging + on_connect re-subscription
    """
    client_id = f"{config.mqtt.client_id_prefix}-{suffix}"
    client = mqtt.Client(client_id=client_id)

    # Store subscriptions for auto re-subscribe on reconnect
    client.user_data_set({"_subscriptions": [], "_service": suffix})

    if config.mqtt.username:
        client.username_pw_set(config.mqtt.username, config.mqtt.password)

    if config.mqtt.tls:
        client.tls_set(
            ca_certs=config.mqtt.ca_certs or None,
            certfile=config.mqtt.certfile or None,
            keyfile=config.mqtt.keyfile or None,
        )

    # Exponential back-off: 1 s initial, 30 s max
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    # --- Auto re-subscribe on reconnect ---------------------------------
    def _on_connect(client: mqtt.Client, userdata, flags, rc):
        svc = (userdata or {}).get("_service", suffix)
        if rc == 0:
            LOG.info("[%s] MQTT connected (rc=%s)", svc, rc)
            # Re-subscribe to all stored topics
            for topic, qos in (userdata or {}).get("_subscriptions", []):
                client.subscribe(topic, qos)
                LOG.debug("[%s] Re-subscribed to %s (qos=%s)", svc, topic, qos)
        else:
            LOG.warning("[%s] MQTT connection failed (rc=%s)", svc, rc)

    def _on_disconnect(client: mqtt.Client, userdata, rc):
        svc = (userdata or {}).get("_service", suffix)
        if rc != 0:
            LOG.warning("[%s] MQTT disconnected unexpectedly (rc=%s), will auto-reconnect...", svc, rc)
        else:
            LOG.info("[%s] MQTT disconnected cleanly", svc)

    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect

    return client


def subscribe_and_track(client: mqtt.Client, topic: str, qos: int = 1) -> None:
    """
    Subscribe to an MQTT topic and register it for auto-reconnect re-subscription.

    Use this instead of ``client.subscribe()`` directly so subscriptions survive
    broker disconnects.
    """
    userdata = client._userdata  # noqa: SLF001
    if userdata is None:
        userdata = {"_subscriptions": []}
        client.user_data_set(userdata)

    subs: List[Tuple[str, int]] = userdata.setdefault("_subscriptions", [])
    # Avoid duplicates
    if (topic, qos) not in subs:
        subs.append((topic, qos))

    client.subscribe(topic, qos)
