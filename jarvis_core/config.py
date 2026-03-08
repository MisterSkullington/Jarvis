from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    ca_certs: Optional[str] = None    # path to CA certificate for TLS
    certfile: Optional[str] = None    # path to client certificate
    keyfile: Optional[str] = None     # path to client private key


@dataclass
class LlmConfig:
    enabled: bool = True
    base_url: str = "http://localhost:11434"
    model: str = "llama3.1:8b"
    timeout_seconds: int = 60


@dataclass
class NluAgentConfig:
    base_url: str = "http://localhost:8001"
    timeout_seconds: int = 30


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    channels: int = 1
    engine: str = "vosk"              # vosk | faster_whisper
    vosk_model_path: str = "models/vosk-model-small-en-us-0.15"
    whisper_model: str = "base"       # for faster_whisper: tiny/base/small/medium/large


@dataclass
class WakewordConfig:
    wake_word: str = "jarvis"
    enabled: bool = True
    sensitivity: float = 0.5


@dataclass
class TtsConfig:
    engine: str = "piper"             # piper | pyttsx3
    piper_executable: str = "piper"
    piper_model: str = "en_US-libritts-high.onnx"
    xtts_model: str = "tts_models/multilingual/multi-dataset/xtts_v2"
    xtts_speaker_wav: str = "assets/jarvis_voice_reference.wav"
    xtts_language: str = "en"
    voice_rate: int = 180
    voice_volume: float = 1.0


@dataclass
class UserProfileConfig:
    name: str = "Sir"
    preferred_address: str = "sir"
    location: str = ""
    timezone: str = ""
    interests: List[str] = field(default_factory=list)


@dataclass
class WebUiConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class MemoryConfig:
    enabled: bool = True
    db_path: str = "data/memory.db"
    max_history_per_session: int = 50
    max_search_results: int = 10


@dataclass
class ProactiveConfig:
    enabled: bool = True
    morning_briefing_hour: int = 8
    morning_briefing_minute: int = 0
    calendar_alert_minutes_before: int = 10
    weather_update_interval_hours: int = 3


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
    require_confirmation: List[str] = field(
        default_factory=lambda: ["lock", "shutdown", "restart"]
    )


@dataclass
class MemoryConfig:
    enabled: bool = True
    chroma_path: str = "data/chroma"
    conversation_collection: str = "conversations"
    knowledge_collection: str = "knowledge"
    documents_path: str = "data/documents"
    embedding_model: str = "all-MiniLM-L6-v2"
    top_k: int = 5
    max_conversation_turns: int = 50


@dataclass
class PersonalityConfig:
    system_prompt: str = (
        "You are Jarvis, a highly intelligent personal assistant inspired by the "
        "iconic AI from Iron Man. You speak with dry British wit, address the user "
        "as 'Sir', and keep responses concise and direct. You may be subtly sarcastic "
        "when appropriate, but always prioritize being genuinely useful. You have access "
        "to calendar, weather, smart home controls, and general knowledge. Never break character."
    )
    honorific: str = "Sir"


@dataclass
class AgentConfig:
    enabled: bool = False             # set true to route general queries through tool-calling agent
    tools: List[str] = field(default_factory=lambda: [
        "calendar", "weather", "news", "light_control", "system_command",
    ])
    max_iterations: int = 5           # max tool-call rounds before forcing final answer


@dataclass
class ProactivityConfig:
    enabled: bool = False
    reminder_minutes: int = 10        # remind this many minutes before calendar events
    morning_brief_enabled: bool = False
    morning_brief_time: str = "07:30" # HH:MM local time
    timezone: str = "UTC"


@dataclass
class VisionConfig:
    enabled: bool = False
    base_url: str = "http://localhost:8003"   # vision microservice
    ollama_vision_model: str = "llava"        # Ollama multimodal model for description
    screen_capture_region: Optional[Dict[str, int]] = None  # {top,left,width,height} or null


@dataclass
class DesktopConfig:
    enabled: bool = False
    allowed_apps: List[str] = field(default_factory=lambda: [
        "notepad", "calculator", "chrome", "firefox", "explorer",
    ])
    rate_limit_seconds: int = 5


@dataclass
class EmailConfig:
    enabled: bool = False
    provider: str = "smtp"            # smtp | google | microsoft
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    token_env_var: str = "EMAIL_PASSWORD"
    from_address: str = ""


@dataclass
class PluginConfig:
    enabled: bool = False
    plugins_path: str = "plugins"     # directory containing plugin modules


@dataclass
class JarvisConfig:
    profile: str = "dev"
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    nlu_agent: NluAgentConfig = field(default_factory=NluAgentConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    wakeword: WakewordConfig = field(default_factory=WakewordConfig)
    tts: TtsConfig = field(default_factory=TtsConfig)
    user: UserProfileConfig = field(default_factory=UserProfileConfig)
    web_ui: WebUiConfig = field(default_factory=WebUiConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    proactive: ProactiveConfig = field(default_factory=ProactiveConfig)
    home_assistant: HomeAssistantConfig = field(default_factory=HomeAssistantConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    personality: PersonalityConfig = field(default_factory=PersonalityConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    proactivity: ProactivityConfig = field(default_factory=ProactivityConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    desktop: DesktopConfig = field(default_factory=DesktopConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    plugins: PluginConfig = field(default_factory=PluginConfig)
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
    - config/{profile}.yaml (overrides, default "dev")
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

    # Environment-level overrides
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

    def build(section_cls, key: str):
        section_dict = merged.get(key, {}) or {}
        # Drop unknown keys so dataclasses don't blow up on future YAML additions
        valid = {f.name for f in section_cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in section_dict.items() if k in valid}
        return section_cls(**filtered)

    return JarvisConfig(
        profile=profile,
        mqtt=build(MqttConfig, "mqtt"),
        llm=build(LlmConfig, "llm"),
        nlu_agent=build(NluAgentConfig, "nlu_agent"),
        audio=build(AudioConfig, "audio"),
        wakeword=build(WakewordConfig, "wakeword"),
        tts=build(TtsConfig, "tts"),
        user=build(UserProfileConfig, "user"),
        web_ui=build(WebUiConfig, "web_ui"),
        memory=build(MemoryConfig, "memory"),
        proactive=build(ProactiveConfig, "proactive"),
        home_assistant=build(HomeAssistantConfig, "home_assistant"),
        safety=build(SafetyConfig, "safety"),
        memory=build(MemoryConfig, "memory"),
        personality=build(PersonalityConfig, "personality"),
        agent=build(AgentConfig, "agent"),
        proactivity=build(ProactivityConfig, "proactivity"),
        vision=build(VisionConfig, "vision"),
        desktop=build(DesktopConfig, "desktop"),
        email=build(EmailConfig, "email"),
        plugins=build(PluginConfig, "plugins"),
        log_level=merged.get("log_level", "INFO"),
    )
