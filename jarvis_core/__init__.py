"""
Shared utilities for the Jarvis assistant.

This package currently exposes:
- load_config: load configuration from YAML + environment.
- configure_logging: set up consistent logging across services.
"""

from .config import load_config
from .logging_config import configure_logging

__all__ = ["load_config", "configure_logging"]

