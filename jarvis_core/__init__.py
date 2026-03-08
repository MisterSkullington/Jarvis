"""
Shared utilities for the Jarvis assistant.

This package currently exposes:
- load_config: load configuration from YAML + environment.
- configure_logging: set up consistent logging across services.
- make_mqtt_client: create a configured Paho MQTT client.
- get_honorific: retrieve the configured honorific (e.g. "Sir").
- get_system_message: build the Ollama system message dict.
- ollama_chat: POST to Ollama /api/chat and return the message dict.
"""

from .config import load_config
from .logging_config import configure_logging
from .mqtt_helpers import make_mqtt_client
from .llm_helpers import get_honorific, get_system_message, ollama_chat

__all__ = [
    "load_config",
    "configure_logging",
    "make_mqtt_client",
    "get_honorific",
    "get_system_message",
    "ollama_chat",
]

