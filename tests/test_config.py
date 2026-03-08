"""
Tests for config loading, defaults, and profile merging.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from jarvis_core.config import (
    JarvisConfig, MqttConfig, LlmConfig, AudioConfig, SafetyConfig,
    MemoryConfig, PersonalityConfig, AgentConfig, ProactivityConfig,
    VisionConfig, DesktopConfig, EmailConfig, PluginConfig,
    load_config,
)


# ---------------------------------------------------------------------------
# Dataclass defaults
# ---------------------------------------------------------------------------

def test_mqtt_defaults():
    cfg = MqttConfig()
    assert cfg.host == "localhost"
    assert cfg.port == 1883
    assert cfg.tls is False
    assert cfg.ca_certs is None


def test_llm_defaults():
    cfg = LlmConfig()
    assert cfg.enabled is True
    assert cfg.model == "phi3"


def test_audio_defaults():
    cfg = AudioConfig()
    assert cfg.engine == "vosk"
    assert cfg.sample_rate == 16000
    assert cfg.whisper_model == "base"


def test_safety_defaults():
    cfg = SafetyConfig()
    assert "lock_pc" in cfg.allowed_system_commands
    assert cfg.dangerous_actions_rate_limit_seconds == 30


def test_memory_defaults():
    cfg = MemoryConfig()
    assert cfg.enabled is True
    assert cfg.top_k == 5
    assert cfg.chroma_path == "data/chroma"


def test_personality_defaults():
    cfg = PersonalityConfig()
    assert "Sir" in cfg.system_prompt or "Jarvis" in cfg.system_prompt
    assert cfg.honorific == "Sir"


def test_agent_defaults():
    cfg = AgentConfig()
    assert cfg.enabled is False
    assert "calendar" in cfg.tools
    assert cfg.max_iterations == 5


def test_proactivity_defaults():
    cfg = ProactivityConfig()
    assert cfg.enabled is False
    assert cfg.reminder_minutes == 10


def test_vision_defaults():
    cfg = VisionConfig()
    assert cfg.enabled is False
    assert cfg.ollama_vision_model == "llava"


def test_desktop_defaults():
    cfg = DesktopConfig()
    assert cfg.enabled is False
    assert cfg.rate_limit_seconds == 5


def test_email_defaults():
    cfg = EmailConfig()
    assert cfg.enabled is False
    assert cfg.provider == "smtp"


def test_plugin_defaults():
    cfg = PluginConfig()
    assert cfg.enabled is False
    assert cfg.plugins_path == "plugins"


# ---------------------------------------------------------------------------
# JarvisConfig wiring
# ---------------------------------------------------------------------------

def test_jarvis_config_has_all_sections():
    cfg = JarvisConfig()
    for attr in [
        "mqtt", "llm", "nlu_agent", "audio", "wakeword", "tts",
        "home_assistant", "safety", "memory", "personality",
        "agent", "proactivity", "vision", "desktop", "email", "plugins",
    ]:
        assert hasattr(cfg, attr), f"JarvisConfig missing field: {attr}"


# ---------------------------------------------------------------------------
# load_config from example YAML
# ---------------------------------------------------------------------------

def test_load_config_returns_jarvis_config():
    cfg = load_config(profile="nonexistent_profile_xyz")
    assert isinstance(cfg, JarvisConfig)


def test_load_config_base_yaml():
    """load_config() reads jarvis.example.yaml and sets sensible defaults."""
    cfg = load_config(profile="nonexistent_profile_xyz")
    assert cfg.mqtt.port == 1883
    assert cfg.llm.model == "phi3"
    assert cfg.personality.honorific == "Sir"


def test_load_config_profile_merge(tmp_path):
    """Profile YAML values override base YAML values."""
    from jarvis_core.config import CONFIG_DIR
    profile_file = CONFIG_DIR / "_test_profile_.yaml"
    try:
        profile_file.write_text("llm:\n  model: llama3.2\nlog_level: DEBUG\n", encoding="utf-8")
        cfg = load_config(profile="_test_profile_")
        assert cfg.llm.model == "llama3.2"
        assert cfg.log_level == "DEBUG"
        # Base values not overridden should remain
        assert cfg.mqtt.port == 1883
    finally:
        if profile_file.exists():
            profile_file.unlink()


def test_load_config_env_override(monkeypatch):
    """Environment variables override YAML values."""
    monkeypatch.setenv("JARVIS_MQTT_HOST", "mqtt.example.com")
    monkeypatch.setenv("JARVIS_LLM_ENABLED", "false")
    monkeypatch.setenv("JARVIS_LOG_LEVEL", "WARNING")
    cfg = load_config(profile="nonexistent_profile_xyz")
    assert cfg.mqtt.host == "mqtt.example.com"
    assert cfg.llm.enabled is False
    assert cfg.log_level == "WARNING"


def test_load_config_unknown_yaml_keys_ignored(tmp_path):
    """Unknown keys in profile YAML are silently dropped (no TypeError)."""
    from jarvis_core.config import CONFIG_DIR
    profile_file = CONFIG_DIR / "_test_unknown_.yaml"
    try:
        profile_file.write_text(
            "mqtt:\n  host: localhost\n  totally_unknown_key: boom\n",
            encoding="utf-8",
        )
        # Should not raise
        cfg = load_config(profile="_test_unknown_")
        assert cfg.mqtt.host == "localhost"
    finally:
        if profile_file.exists():
            profile_file.unlink()
