"""
MQTT client factory with optional TLS support (Phase 6).
All services should use make_mqtt_client() for consistent configuration.
"""
from __future__ import annotations

import paho.mqtt.client as mqtt


def make_mqtt_client(config, suffix: str) -> mqtt.Client:
    """
    Create a configured MQTT client.

    Applies:
      - client_id from config.mqtt.client_id_prefix + suffix
      - username/password if set
      - TLS if config.mqtt.tls is True (uses ca_certs / certfile / keyfile if provided)
    """
    client_id = f"{config.mqtt.client_id_prefix}-{suffix}"
    client = mqtt.Client(client_id=client_id)

    if config.mqtt.username:
        client.username_pw_set(config.mqtt.username, config.mqtt.password)

    if config.mqtt.tls:
        client.tls_set(
            ca_certs=config.mqtt.ca_certs or None,
            certfile=config.mqtt.certfile or None,
            keyfile=config.mqtt.keyfile or None,
        )

    return client
