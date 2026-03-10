"""
settings_dialog.py — Settings dialog for Jarvis desktop app.

Reads from jarvis_core.load_config() and saves changes to config/{profile}.yaml.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGroupBox, QLabel, QLineEdit, QScrollArea, QSpinBox, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

from desktop_client.styles import APP_QSS

LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Audio device helpers
# ---------------------------------------------------------------------------

def _query_audio_devices() -> List[Dict]:
    """Return list of device dicts from sounddevice, or [] on error."""
    try:
        import sounddevice as sd
        return list(sd.query_devices())
    except Exception:
        LOG.debug("sounddevice.query_devices() unavailable", exc_info=True)
        return []


def _build_input_device_list(devices: List[Dict]) -> Tuple[List[str], List[Optional[str]]]:
    """
    Return (display_labels, device_names) for all input-capable devices.
    Index 0 is always "System Default" / None.
    Deduplicates by name — Windows returns the same physical device once per
    host API (WASAPI, MME, DirectSound, WDM-KS); we keep only the first entry.
    """
    labels: List[str] = ["System Default"]
    names: List[Optional[str]] = [None]
    seen: set = set()
    for d in devices:
        if d.get("max_input_channels", 0) > 0:
            n = d["name"]
            if n not in seen:
                seen.add(n)
                ch = d["max_input_channels"]
                labels.append(f"{n}  ({ch} ch)")
                names.append(n)
    return labels, names


def _build_output_device_list(devices: List[Dict]) -> Tuple[List[str], List[Optional[str]]]:
    """
    Return (display_labels, device_names) for all output-capable devices.
    Index 0 is always "System Default" / None.
    Deduplicates by name — Windows returns the same physical device once per
    host API (WASAPI, MME, DirectSound, WDM-KS); we keep only the first entry.
    """
    labels: List[str] = ["System Default"]
    names: List[Optional[str]] = [None]
    seen: set = set()
    for d in devices:
        if d.get("max_output_channels", 0) > 0:
            n = d["name"]
            if n not in seen:
                seen.add(n)
                ch = d["max_output_channels"]
                labels.append(f"{n}  ({ch} ch)")
                names.append(n)
    return labels, names


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    """Modal settings editor — reads/writes Jarvis YAML config."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Jarvis Settings")
        self.setMinimumSize(520, 480)
        self.setStyleSheet(APP_QSS)
        self._config = config
        self._fields: Dict = {}

        # Query devices once at dialog open and build parallel name lists
        devices = _query_audio_devices()
        input_labels, self._input_names = _build_input_device_list(devices)
        output_labels, self._output_names = _build_output_device_list(devices)

        self._build_ui(input_labels, output_labels)
        self._load_values()

    # ── Build UI ──────────────────────────────────────────────────────────

    def _build_ui(self, input_labels: List[str], output_labels: List[str]) -> None:
        root = QVBoxLayout(self)

        tabs = QTabWidget()

        # ── LLM tab ───────────────────────────────────────────────────────
        llm_tab = QWidget()
        llm_layout = QFormLayout(llm_tab)
        self._fields["llm.enabled"] = QCheckBox("Enable LLM")
        llm_layout.addRow(self._fields["llm.enabled"])
        self._fields["llm.base_url"] = QLineEdit()
        llm_layout.addRow("Ollama URL:", self._fields["llm.base_url"])
        self._fields["llm.model"] = QLineEdit()
        llm_layout.addRow("Model:", self._fields["llm.model"])
        self._fields["llm.timeout_seconds"] = QSpinBox()
        self._fields["llm.timeout_seconds"].setRange(5, 300)
        llm_layout.addRow("Timeout (s):", self._fields["llm.timeout_seconds"])
        tabs.addTab(llm_tab, "LLM")

        # ── Audio tab ─────────────────────────────────────────────────────
        audio_tab = QWidget()
        audio_layout = QFormLayout(audio_tab)
        self._fields["audio.engine"] = QComboBox()
        self._fields["audio.engine"].addItems(["vosk", "faster_whisper"])
        audio_layout.addRow("STT Engine:", self._fields["audio.engine"])
        self._fields["audio.silence_threshold"] = QSpinBox()
        self._fields["audio.silence_threshold"].setRange(50, 5000)
        audio_layout.addRow("Silence threshold:", self._fields["audio.silence_threshold"])
        self._fields["audio.sample_rate"] = QSpinBox()
        self._fields["audio.sample_rate"].setRange(8000, 48000)
        audio_layout.addRow("Sample rate:", self._fields["audio.sample_rate"])

        # Input device dropdown — labels only, names tracked in self._input_names
        input_combo = QComboBox()
        input_combo.addItems(input_labels)
        self._fields["audio.input_device"] = input_combo
        audio_layout.addRow("Input Device:", input_combo)

        tabs.addTab(audio_tab, "Audio")

        # ── TTS tab ───────────────────────────────────────────────────────
        tts_tab = QWidget()
        tts_layout = QFormLayout(tts_tab)
        self._fields["tts.engine"] = QComboBox()
        self._fields["tts.engine"].addItems(["piper", "pyttsx3"])
        tts_layout.addRow("TTS Engine:", self._fields["tts.engine"])
        self._fields["tts.voice_rate"] = QSpinBox()
        self._fields["tts.voice_rate"].setRange(50, 400)
        tts_layout.addRow("Voice rate:", self._fields["tts.voice_rate"])

        # Output device dropdown — labels only, names tracked in self._output_names
        output_combo = QComboBox()
        output_combo.addItems(output_labels)
        self._fields["tts.output_device"] = output_combo
        tts_layout.addRow("Output Device:", output_combo)

        tabs.addTab(tts_tab, "TTS")

        # ── Personality tab ───────────────────────────────────────────────
        personality_tab = QWidget()
        personality_layout = QFormLayout(personality_tab)
        self._fields["personality.honorific"] = QLineEdit()
        personality_layout.addRow("Honorific:", self._fields["personality.honorific"])
        self._fields["personality.system_prompt"] = QTextEdit()
        self._fields["personality.system_prompt"].setMaximumHeight(160)
        personality_layout.addRow("System prompt:", self._fields["personality.system_prompt"])
        tabs.addTab(personality_tab, "Personality")

        # ── Memory tab ────────────────────────────────────────────────────
        memory_tab = QWidget()
        memory_layout = QFormLayout(memory_tab)
        self._fields["memory.enabled"] = QCheckBox("Enable memory/RAG")
        memory_layout.addRow(self._fields["memory.enabled"])
        self._fields["memory.top_k"] = QSpinBox()
        self._fields["memory.top_k"].setRange(1, 50)
        memory_layout.addRow("Top K results:", self._fields["memory.top_k"])
        self._fields["memory.max_conversation_turns"] = QSpinBox()
        self._fields["memory.max_conversation_turns"].setRange(5, 500)
        memory_layout.addRow("Max turns:", self._fields["memory.max_conversation_turns"])
        self._fields["memory.embedding_model"] = QLineEdit()
        memory_layout.addRow("Embedding model:", self._fields["memory.embedding_model"])
        tabs.addTab(memory_tab, "Memory")

        root.addWidget(tabs)

        # ── Buttons ───────────────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ── Load ──────────────────────────────────────────────────────────────

    def _load_values(self) -> None:
        cfg = self._config

        self._fields["llm.enabled"].setChecked(cfg.llm.enabled)
        self._fields["llm.base_url"].setText(cfg.llm.base_url)
        self._fields["llm.model"].setText(cfg.llm.model)
        self._fields["llm.timeout_seconds"].setValue(cfg.llm.timeout_seconds)

        self._fields["audio.engine"].setCurrentText(cfg.audio.engine)
        self._fields["audio.silence_threshold"].setValue(cfg.audio.silence_threshold)
        self._fields["audio.sample_rate"].setValue(cfg.audio.sample_rate)

        # Select saved input device by matching name in parallel list
        input_dev = getattr(cfg.audio, "input_device", None)
        self._set_combo_by_name(
            self._fields["audio.input_device"],
            self._input_names,
            input_dev,
        )

        self._fields["tts.engine"].setCurrentText(cfg.tts.engine)
        self._fields["tts.voice_rate"].setValue(cfg.tts.voice_rate)

        # Select saved output device by matching name in parallel list
        output_dev = getattr(cfg.tts, "output_device", None)
        self._set_combo_by_name(
            self._fields["tts.output_device"],
            self._output_names,
            output_dev,
        )

        self._fields["personality.honorific"].setText(cfg.personality.honorific)
        self._fields["personality.system_prompt"].setPlainText(cfg.personality.system_prompt)

        self._fields["memory.enabled"].setChecked(cfg.memory.enabled)
        self._fields["memory.top_k"].setValue(cfg.memory.top_k)
        self._fields["memory.max_conversation_turns"].setValue(cfg.memory.max_conversation_turns)
        self._fields["memory.embedding_model"].setText(cfg.memory.embedding_model)

    @staticmethod
    def _set_combo_by_name(
        combo: QComboBox,
        names: List[Optional[str]],
        target: Optional[str],
    ) -> None:
        """Set combo to the index whose entry in *names* matches *target* (None = default)."""
        try:
            combo.setCurrentIndex(names.index(target))
        except ValueError:
            combo.setCurrentIndex(0)  # fall back to System Default

    def _get_device_name(
        self,
        combo: QComboBox,
        names: List[Optional[str]],
    ) -> Optional[str]:
        """Return the device name for the currently selected combo item."""
        idx = combo.currentIndex()
        if 0 <= idx < len(names):
            return names[idx]
        return None  # default

    # ── Save ──────────────────────────────────────────────────────────────

    def _save(self) -> None:
        """Collect field values and write to config/{profile}.yaml."""
        data = {
            "llm": {
                "enabled": self._fields["llm.enabled"].isChecked(),
                "base_url": self._fields["llm.base_url"].text(),
                "model": self._fields["llm.model"].text(),
                "timeout_seconds": self._fields["llm.timeout_seconds"].value(),
            },
            "audio": {
                "engine": self._fields["audio.engine"].currentText(),
                "silence_threshold": self._fields["audio.silence_threshold"].value(),
                "sample_rate": self._fields["audio.sample_rate"].value(),
                "input_device": self._get_device_name(
                    self._fields["audio.input_device"], self._input_names
                ),
            },
            "tts": {
                "engine": self._fields["tts.engine"].currentText(),
                "voice_rate": self._fields["tts.voice_rate"].value(),
                "output_device": self._get_device_name(
                    self._fields["tts.output_device"], self._output_names
                ),
            },
            "personality": {
                "honorific": self._fields["personality.honorific"].text(),
                "system_prompt": self._fields["personality.system_prompt"].toPlainText(),
            },
            "memory": {
                "enabled": self._fields["memory.enabled"].isChecked(),
                "top_k": self._fields["memory.top_k"].value(),
                "max_conversation_turns": self._fields["memory.max_conversation_turns"].value(),
                "embedding_model": self._fields["memory.embedding_model"].text(),
            },
        }

        config_dir = Path(__file__).resolve().parent.parent / "config"
        config_dir.mkdir(exist_ok=True)
        profile = getattr(self._config, "profile", "dev")
        config_path = config_dir / f"{profile}.yaml"

        # Merge with existing file if present
        existing = {}
        if config_path.exists():
            with config_path.open("r", encoding="utf-8") as f:
                existing = yaml.safe_load(f) or {}

        for section, values in data.items():
            existing.setdefault(section, {}).update(values)

        with config_path.open("w", encoding="utf-8") as f:
            yaml.dump(existing, f, default_flow_style=False, allow_unicode=True)

        self.accept()
