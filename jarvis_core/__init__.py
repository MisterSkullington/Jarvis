"""
Shared utilities for the Jarvis assistant.

This package currently exposes:
- load_config: load configuration from YAML + environment.
- configure_logging: set up consistent logging across services.
- persona: JARVIS personality, system prompt, and response templates.
"""

from .config import load_config
from .logging_config import configure_logging
from .persona import UserProfile, build_system_prompt

__all__ = ["load_config", "configure_logging", "UserProfile", "build_system_prompt"]
