from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"


@dataclass
class MqttConfig:
    host: str = "localhost"
    port: int = 1883
    username: Optional[str] = None
    password: Optional[str] = None
    client_id_prefix: str = "jarvis"
    tls: bool = False


@dataclass
class LlmConfig:
    enabled: bool = True
    base_url: str = "http://localhost:11434"
    model: str = "phi3"
    timeout_seconds: int = 60


@dataclass
class NluAgentConfig:
    base_url: str = "http://localhost:8001"
    timeout_seconds: int = 30


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    channels: int = 1
    vosk_model_path: str = "models/vosk-model-small-en-us-0.15"
    whisper_model: str = "base"


@dataclass
class WakewordConfig:
    wake_word: str = "jarvis"
    enabled: bool = True
    sensitivity: float = 0.5


@dataclass
class TtsConfig:
    engine: str = "piper"  # or "pyttsx3"
    piper_executable: str = "piper"
    piper_model: str = "en_US-libritts-high.onnx"
    voice_rate: int = 180
    voice_volume: float = 1.0


@dataclass
class HomeAssistantConfig:
    base_url: str = "http://homeassistant.local:8123"
    token_env_var: str = "HASS_TOKEN"
    default_light_entity: str = "light.living_room"


@dataclass
class SafetyConfig:
    allowed_system_commands: Dict[str, str] = field(
        default_factory=lambda: {
            "lock_pc": "rundll32.exe user32.dll,LockWorkStation",
        }
    )
    dangerous_actions_rate_limit_seconds: int = 30


@dataclass
class JarvisConfig:
    profile: str = "dev"
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    nlu_agent: NluAgentConfig = field(default_factory=NluAgentConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    wakeword: WakewordConfig = field(default_factory=WakewordConfig)
    tts: TtsConfig = field(default_factory=TtsConfig)
    home_assistant: HomeAssistantConfig = field(default_factory=HomeAssistantConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    log_level: str = "INFO"


def _deep_update_dict(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_update_dict(base[key], value)
        else:
            base[key] = value
    return base


def _load_yaml_if_exists(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(profile: Optional[str] = None) -> JarvisConfig:
    """
    Load configuration from:
    - config/jarvis.example.yaml (base defaults)
    - config/{profile}.yaml (overrides, default \"dev\")
    - Environment variables (minor overrides)
    """
    load_dotenv()

    if profile is None:
        profile = os.getenv("JARVIS_PROFILE", "dev")

    base_cfg = _load_yaml_if_exists(CONFIG_DIR / "jarvis.example.yaml")
    profile_cfg = _load_yaml_if_exists(CONFIG_DIR / f"{profile}.yaml")

    merged: Dict[str, Any] = {}
    _deep_update_dict(merged, base_cfg)
    _deep_update_dict(merged, profile_cfg)

    # Environment-level overrides for quick tweaks
    mqtt_host = os.getenv("JARVIS_MQTT_HOST")
    if mqtt_host:
        merged.setdefault("mqtt", {})
        merged["mqtt"]["host"] = mqtt_host

    llm_enabled = os.getenv("JARVIS_LLM_ENABLED")
    if llm_enabled is not None:
        merged.setdefault("llm", {})
        merged["llm"]["enabled"] = llm_enabled.lower() in {"1", "true", "yes"}

    log_level = os.getenv("JARVIS_LOG_LEVEL")
    if log_level:
        merged["log_level"] = log_level

    # Convert dict into dataclasses
    def build(section_cls, key: str):
        section_dict = merged.get(key, {}) or {}
        return section_cls(**section_dict)

    cfg = JarvisConfig(
        profile=profile,
        mqtt=build(MqttConfig, "mqtt"),
        llm=build(LlmConfig, "llm"),
        nlu_agent=build(NluAgentConfig, "nlu_agent"),
        audio=build(AudioConfig, "audio"),
        wakeword=build(WakewordConfig, "wakeword"),
        tts=build(TtsConfig, "tts"),
        home_assistant=build(HomeAssistantConfig, "home_assistant"),
        safety=build(SafetyConfig, "safety"),
        log_level=merged.get("log_level", "INFO"),
    )

    return cfg

