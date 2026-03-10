"""
Shared pytest fixtures for the Jarvis test suite.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure repo root is on sys.path so services/* imports work
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def mock_config():
    """Minimal JarvisConfig mock with all required sub-configs."""
    cfg = MagicMock()
    # LLM
    cfg.llm.enabled = False          # disable Ollama calls in unit tests
    cfg.llm.base_url = "http://localhost:11434"
    cfg.llm.model = "phi3"
    cfg.llm.timeout_seconds = 5
    # NLU agent
    cfg.nlu_agent.base_url = "http://localhost:8001"
    cfg.nlu_agent.timeout_seconds = 5
    # Safety
    cfg.safety.dangerous_actions_rate_limit_seconds = 0   # no rate limit in tests
    cfg.safety.allowed_system_commands = {"lock_pc": "echo lock"}
    # Personality
    cfg.personality.system_prompt = "You are Jarvis."
    cfg.personality.honorific = "Sir"
    # Agent
    cfg.agent.enabled = False
    cfg.agent.tools = []
    cfg.agent.max_iterations = 3
    # Audio
    cfg.audio.engine = "vosk"
    cfg.audio.silence_threshold = 500
    cfg.audio.sample_rate = 16000
    cfg.audio.input_device = None
    # TTS
    cfg.tts.engine = "piper"
    cfg.tts.voice_rate = 175
    cfg.tts.output_device = None
    # Memory
    cfg.memory.enabled = False
    cfg.memory.top_k = 5
    cfg.memory.max_conversation_turns = 20
    cfg.memory.embedding_model = "all-MiniLM-L6-v2"
    # Vision / desktop
    cfg.vision.enabled = False
    cfg.desktop.enabled = False
    # Email / plugins
    cfg.email.enabled = False
    cfg.plugins.enabled = False
    return cfg
