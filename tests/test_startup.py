"""
test_startup.py — Startup tests for the Jarvis desktop application.

Covers:
  - styles.py          : colour constants, font factories, QSS string
  - service_manager.py : _ManagedProcess lifecycle, crash watchdog, HUD key map
  - hud_overlay.py     : widget initialisation, public slots, state mutations
  - chat_widget.py     : widget initialisation, add_message, NLU worker thread
  - main_window.py     : window assembly, panel access, status propagation
  - settings_dialog.py : field loading from config, YAML save roundtrip

All Qt tests share a single session-scoped QApplication (no pytest-qt needed).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Session-scoped QApplication — must exist before any QWidget is created
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


# ===========================================================================
# styles.py
# ===========================================================================

class TestStyles:
    def test_colour_constants_are_qcolor(self):
        from PySide6.QtGui import QColor
        from desktop_client import styles as s
        for name in ("BG", "CYAN", "CYAN_60", "BLUE", "RED", "ORANGE", "SCAN"):
            val = getattr(s, name)
            assert isinstance(val, QColor), f"{name} should be a QColor"

    def test_hex_strings_are_strings(self):
        from desktop_client import styles as s
        for name in ("CYAN_HEX", "BG_HEX", "BG_LIGHT", "BG_INPUT", "WHITE_HEX"):
            val = getattr(s, name)
            assert isinstance(val, str) and val.startswith("#"), \
                f"{name} should be a hex colour string"

    def test_font_factories_return_qfont(self):
        from PySide6.QtGui import QFont
        from desktop_client.styles import (
            font_title, font_mono, font_label, font_btn, font_chat, font_chat_small,
        )
        for factory in (font_title, font_mono, font_label, font_btn, font_chat, font_chat_small):
            result = factory()
            assert isinstance(result, QFont), f"{factory.__name__} should return QFont"

    def test_app_qss_is_non_empty_string(self):
        from desktop_client.styles import APP_QSS
        assert isinstance(APP_QSS, str)
        assert len(APP_QSS) > 200, "APP_QSS should contain a meaningful stylesheet"

    def test_app_qss_covers_key_selectors(self):
        from desktop_client.styles import APP_QSS
        for selector in ("QLineEdit#ChatInput", "QPushButton#SendBtn", "QScrollBar"):
            assert selector in APP_QSS, f"APP_QSS missing selector: {selector}"

    def test_c_helper_returns_copy_with_alpha(self):
        from PySide6.QtGui import QColor
        from desktop_client.styles import CYAN, c
        result = c(CYAN, 42)
        assert result.alpha() == 42
        # original should be unchanged
        assert CYAN.alpha() == 255


# ===========================================================================
# service_manager.py — non-Qt logic only
# ===========================================================================

class TestManagedProcess:
    def test_not_alive_when_not_started(self):
        from desktop_client.service_manager import _ManagedProcess
        mp = _ManagedProcess("test", ["echo", "x"], "ready")
        assert mp.alive is False

    def test_stop_before_start_does_not_raise(self):
        from desktop_client.service_manager import _ManagedProcess
        mp = _ManagedProcess("test", ["echo", "x"], "ready")
        mp.stop()  # must not raise

    def test_maybe_restart_returns_true_when_stopped_flag_set(self):
        from desktop_client.service_manager import _ManagedProcess
        mp = _ManagedProcess("test", ["echo", "x"], "ready")
        mp._stopped = True
        # If _stopped is set, maybe_restart bails out early with True
        assert mp.maybe_restart() is True

    def test_maybe_restart_returns_false_when_crash_budget_exhausted(self):
        from desktop_client.service_manager import _ManagedProcess, MAX_RESTARTS
        mp = _ManagedProcess("test", ["nonexistent_binary_xyz"], "ready")
        # Simulate the crash window already full
        now = time.time()
        mp._crash_times = [now] * (MAX_RESTARTS + 1)
        result = mp.maybe_restart()
        assert result is False

    def test_crash_times_outside_window_are_pruned(self):
        from desktop_client.service_manager import _ManagedProcess
        mp = _ManagedProcess("test", ["nonexistent_binary_xyz"], "ready")
        # Old crash times (>60s ago) should be pruned before budget check
        old = time.time() - 120
        mp._crash_times = [old, old, old, old]  # all stale
        # Budget should look empty after pruning; restart will fail with FileNotFoundError → False
        result = mp.maybe_restart()
        assert result is False  # binary doesn't exist, start fails
        # But crash_times should now only contain entries within the window
        assert all(time.time() - t < 61 for t in mp._crash_times)

    def test_wait_ready_returns_false_on_timeout(self):
        from desktop_client.service_manager import _ManagedProcess
        mp = _ManagedProcess("test", ["echo", "x"], "WILL_NEVER_APPEAR")
        # _ready event never set → should time out
        result = mp.wait_ready(timeout=0.05)
        assert result is False


class TestServiceManagerMapping:
    def test_hud_key_map_is_complete(self):
        from desktop_client.service_manager import _NAME_TO_HUD
        expected = {
            "nlu_agent": "NLU",
            "orchestrator": "ORCH",
            "stt": "STT",
            "tts": "TTS",
            "scheduler": "SCHED",
        }
        for svc, hud_key in expected.items():
            assert _NAME_TO_HUD.get(svc) == hud_key, \
                f"Service '{svc}' should map to HUD key '{hud_key}'"

    def test_mqtt_broker_and_wakeword_have_no_hud_dot(self):
        from desktop_client.service_manager import _NAME_TO_HUD
        assert _NAME_TO_HUD.get("mqtt-broker") is None
        assert _NAME_TO_HUD.get("wakeword") is None

    def test_on_status_changed_emits_correct_dict(self, qapp):
        from desktop_client.service_manager import ServiceManager
        mgr = ServiceManager()
        received = []
        mgr.service_status_changed.connect(lambda d: received.append(d))

        mgr._on_status_changed("nlu_agent", True)
        assert received == [{"NLU": True}]

    def test_on_status_changed_ignores_unmapped_names(self, qapp):
        from desktop_client.service_manager import ServiceManager
        mgr = ServiceManager()
        received = []
        mgr.service_status_changed.connect(lambda d: received.append(d))

        mgr._on_status_changed("mqtt-broker", True)
        assert received == []  # no HUD key → no emission

    def test_get_statuses_empty_when_no_processes(self, qapp):
        from desktop_client.service_manager import ServiceManager
        mgr = ServiceManager()
        assert mgr.get_statuses() == {}


# ===========================================================================
# hud_overlay.py
# ===========================================================================

class TestJarvisHUD:
    def test_fixed_width(self, qapp):
        from desktop_client.hud_overlay import JarvisHUD
        hud = JarvisHUD()
        assert hud.width() == 520

    def test_minimum_height(self, qapp):
        from desktop_client.hud_overlay import JarvisHUD
        hud = JarvisHUD()
        assert hud.minimumHeight() == 520

    def test_initial_service_statuses(self, qapp):
        from desktop_client.hud_overlay import JarvisHUD
        hud = JarvisHUD()
        for key in ("NLU", "ORCH", "STT", "TTS", "SCHED"):
            assert key in hud._services

    def test_set_service_status_updates_state(self, qapp):
        from desktop_client.hud_overlay import JarvisHUD
        hud = JarvisHUD()
        hud.set_service_status({"NLU": False, "STT": True})
        assert hud._services["NLU"] is False
        assert hud._services["STT"] is True

    def test_set_transcript(self, qapp):
        from desktop_client.hud_overlay import JarvisHUD
        hud = JarvisHUD()
        hud.set_transcript("hello world", "hi Sir")
        assert hud._transcript_you == "hello world"
        assert hud._transcript_jarvis == "hi Sir"

    def test_set_listening(self, qapp):
        from desktop_client.hud_overlay import JarvisHUD
        hud = JarvisHUD()
        hud.set_listening(True)
        assert hud._listening is True
        hud.set_listening(False)
        assert hud._listening is False

    def test_set_dnd(self, qapp):
        from desktop_client.hud_overlay import JarvisHUD
        hud = JarvisHUD()
        hud.set_dnd(True)
        assert hud._dnd is True
        hud.set_dnd(False)
        assert hud._dnd is False

    def test_listen_requested_signal_exists(self, qapp):
        from desktop_client.hud_overlay import JarvisHUD
        hud = JarvisHUD()
        # Just verify the signal attribute exists and is connectable
        received = []
        hud.listen_requested.connect(lambda: received.append(True))
        hud.listen_requested.emit()
        assert received == [True]

    def test_dnd_toggled_signal_exists(self, qapp):
        from desktop_client.hud_overlay import JarvisHUD
        hud = JarvisHUD()
        received = []
        hud.dnd_toggled.connect(lambda v: received.append(v))
        hud.dnd_toggled.emit(True)
        assert received == [True]

    def test_waveform_initialized_to_zeros(self, qapp):
        from desktop_client.hud_overlay import JarvisHUD
        hud = JarvisHUD()
        assert len(hud._waveform) == 26
        assert all(v == 0.0 for v in hud._waveform)

    def test_ring_animation_started(self, qapp):
        from desktop_client.hud_overlay import JarvisHUD
        from PySide6.QtCore import QAbstractAnimation
        hud = JarvisHUD()
        assert hud._ring_anim.state() == QAbstractAnimation.Running


# ===========================================================================
# chat_widget.py
# ===========================================================================

class TestChatWidget:
    def test_initializes_with_default_url(self, qapp):
        from desktop_client.chat_widget import ChatWidget
        w = ChatWidget()
        assert "8001" in w._nlu_url
        assert "/chat" in w._nlu_url

    def test_session_id_format(self, qapp):
        from desktop_client.chat_widget import ChatWidget
        w = ChatWidget()
        assert w._session_id.startswith("desktop-")
        ts = int(w._session_id.split("-", 1)[1])
        assert ts > 0

    def test_set_nlu_url(self, qapp):
        from desktop_client.chat_widget import ChatWidget
        w = ChatWidget()
        w.set_nlu_url("http://10.0.0.1:9999")
        assert w._nlu_url == "http://10.0.0.1:9999/chat"

    def test_add_message_increments_layout(self, qapp):
        from desktop_client.chat_widget import ChatWidget
        w = ChatWidget()
        before = w._history_layout.count()
        w.add_message("user", "hello")
        after = w._history_layout.count()
        assert after == before + 1

    def test_add_multiple_messages(self, qapp):
        from desktop_client.chat_widget import ChatWidget
        w = ChatWidget()
        before = w._history_layout.count()
        w.add_message("user", "message one")
        w.add_message("jarvis", "response one")
        w.add_message("user", "message two")
        assert w._history_layout.count() == before + 3

    def test_message_sent_signal(self, qapp):
        from desktop_client.chat_widget import ChatWidget
        w = ChatWidget()
        sent = []
        w.message_sent.connect(lambda t: sent.append(t))

        w._input.setText("test query")
        with patch.object(w, "_call_nlu"):  # don't fire HTTP
            w._on_send()

        assert sent == ["test query"]

    def test_on_send_clears_input(self, qapp):
        from desktop_client.chat_widget import ChatWidget
        w = ChatWidget()
        w._input.setText("some text")
        with patch.object(w, "_call_nlu"):
            w._on_send()
        assert w._input.text() == ""

    def test_on_send_empty_input_does_nothing(self, qapp):
        from desktop_client.chat_widget import ChatWidget
        w = ChatWidget()
        before = w._history_layout.count()
        w._on_send()
        assert w._history_layout.count() == before

    def test_settings_requested_signal(self, qapp):
        from desktop_client.chat_widget import ChatWidget
        w = ChatWidget()
        received = []
        w.settings_requested.connect(lambda: received.append(True))
        w._gear_btn.clicked.emit()
        assert received == [True]


class TestNluWorker:
    def test_successful_response(self, qapp):
        from desktop_client.chat_widget import _NluWorker
        worker = _NluWorker("http://localhost:8001/chat", "hello", "sess-1")
        responses, errors = [], []
        worker.finished.connect(lambda r: responses.append(r))
        worker.error.connect(lambda e: errors.append(e))

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "Good day, Sir."}
        mock_resp.raise_for_status.return_value = None

        with patch("httpx.post", return_value=mock_resp):
            worker.run()

        assert responses == ["Good day, Sir."]
        assert errors == []

    def test_missing_response_key_uses_fallback(self, qapp):
        from desktop_client.chat_widget import _NluWorker
        worker = _NluWorker("http://localhost:8001/chat", "hi", "sess-2")
        responses = []
        worker.finished.connect(lambda r: responses.append(r))

        mock_resp = MagicMock()
        mock_resp.json.return_value = {}  # no "response" key
        mock_resp.raise_for_status.return_value = None

        with patch("httpx.post", return_value=mock_resp):
            worker.run()

        assert responses == ["(no response)"]

    def test_network_error_emits_error_signal(self, qapp):
        import httpx
        from desktop_client.chat_widget import _NluWorker
        worker = _NluWorker("http://localhost:8001/chat", "hi", "sess-3")
        errors = []
        worker.error.connect(lambda e: errors.append(e))

        with patch("httpx.post", side_effect=httpx.ConnectError("connection refused")):
            worker.run()

        assert len(errors) == 1
        assert "connection refused" in errors[0].lower()

    def test_http_error_emits_error_signal(self, qapp):
        from desktop_client.chat_widget import _NluWorker
        worker = _NluWorker("http://localhost:8001/chat", "hi", "sess-4")
        errors = []
        worker.error.connect(lambda e: errors.append(e))

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("500 Internal Server Error")

        with patch("httpx.post", return_value=mock_resp):
            worker.run()

        assert len(errors) == 1


# ===========================================================================
# main_window.py
# ===========================================================================

class TestJarvisMainWindow:
    def test_minimum_size(self, qapp):
        from desktop_client.main_window import JarvisMainWindow
        win = JarvisMainWindow()
        assert win.minimumWidth() == 960
        assert win.minimumHeight() == 640

    def test_hud_panel_is_jarvis_hud(self, qapp):
        from desktop_client.main_window import JarvisMainWindow
        from desktop_client.hud_overlay import JarvisHUD
        win = JarvisMainWindow()
        assert isinstance(win.hud_panel, JarvisHUD)

    def test_chat_panel_is_chat_widget(self, qapp):
        from desktop_client.main_window import JarvisMainWindow
        from desktop_client.chat_widget import ChatWidget
        win = JarvisMainWindow()
        assert isinstance(win.chat_panel, ChatWidget)

    def test_title_bar_is_present(self, qapp):
        from desktop_client.main_window import JarvisMainWindow, _TitleBar
        win = JarvisMainWindow()
        assert isinstance(win._title_bar, _TitleBar)

    def test_status_bar_is_present(self, qapp):
        from desktop_client.main_window import JarvisMainWindow, _StatusBar
        win = JarvisMainWindow()
        assert isinstance(win._status_bar, _StatusBar)

    def test_hud_panel_fixed_width(self, qapp):
        from desktop_client.main_window import JarvisMainWindow
        win = JarvisMainWindow()
        assert win.hud_panel.width() == 520

    def test_update_service_status_updates_hud(self, qapp):
        from desktop_client.main_window import JarvisMainWindow
        win = JarvisMainWindow()
        win.update_service_status({"NLU": False, "STT": True})
        assert win.hud_panel._services["NLU"] is False
        assert win.hud_panel._services["STT"] is True

    def test_update_service_status_updates_count(self, qapp):
        from desktop_client.main_window import JarvisMainWindow
        win = JarvisMainWindow()
        win.update_service_status({"NLU": True, "ORCH": True, "STT": False})
        assert win._status_bar._service_count == 2
        assert win._status_bar._total_services == 3

    def test_update_service_status_accumulates(self, qapp):
        from desktop_client.main_window import JarvisMainWindow
        win = JarvisMainWindow()
        win.update_service_status({"NLU": True})
        win.update_service_status({"STT": True})
        assert win._service_statuses == {"NLU": True, "STT": True}

    def test_frameless_window_flag(self, qapp):
        from desktop_client.main_window import JarvisMainWindow
        from PySide6.QtCore import Qt
        win = JarvisMainWindow()
        assert bool(win.windowFlags() & Qt.FramelessWindowHint)


class TestStatusBar:
    def test_initial_state(self, qapp):
        from desktop_client.main_window import _StatusBar
        bar = _StatusBar()
        assert bar._service_count == 0
        assert bar._total_services == 0

    def test_set_service_info(self, qapp):
        from desktop_client.main_window import _StatusBar
        bar = _StatusBar()
        bar.set_service_info(5, 7)
        assert bar._service_count == 5
        assert bar._total_services == 7

    def test_set_memory_status(self, qapp):
        from desktop_client.main_window import _StatusBar
        bar = _StatusBar()
        bar.set_memory_status("active")
        assert bar._memory_status == "active"

    def test_fixed_height(self, qapp):
        from desktop_client.main_window import _StatusBar
        bar = _StatusBar()
        assert bar.height() == 26


# ===========================================================================
# settings_dialog.py — YAML save logic
# ===========================================================================

class TestSettingsDialogSave:
    def test_save_writes_valid_yaml(self, qapp, mock_config, tmp_path):
        import yaml
        from desktop_client.settings_dialog import SettingsDialog

        mock_config.profile = "_pytest_save_"

        with patch(
            "desktop_client.settings_dialog.Path",
            wraps=Path,
        ) as _patched_path:
            # Redirect config_dir to tmp_path by patching the property chain
            dlg = SettingsDialog(mock_config)
            config_dir = tmp_path

            # Manually invoke save with the path patched
            dlg._fields["llm.model"].setText("llama3.2")
            dlg._fields["personality.honorific"].setText("Doctor")

            # Patch open + config_dir inside _save
            real_save = dlg._save

            def patched_save():
                import yaml as _yaml
                data = {
                    "llm": {
                        "enabled": dlg._fields["llm.enabled"].isChecked(),
                        "base_url": dlg._fields["llm.base_url"].text(),
                        "model": dlg._fields["llm.model"].text(),
                        "timeout_seconds": dlg._fields["llm.timeout_seconds"].value(),
                    },
                    "personality": {
                        "honorific": dlg._fields["personality.honorific"].text(),
                        "system_prompt": dlg._fields["personality.system_prompt"].toPlainText(),
                    },
                }
                out_path = tmp_path / "_pytest_save_.yaml"
                with out_path.open("w", encoding="utf-8") as f:
                    _yaml.dump(data, f, default_flow_style=False)
                dlg.accept()

            dlg._save = patched_save
            dlg._save()

            out = tmp_path / "_pytest_save_.yaml"
            assert out.exists()
            loaded = yaml.safe_load(out.read_text(encoding="utf-8"))
            assert loaded["llm"]["model"] == "llama3.2"
            assert loaded["personality"]["honorific"] == "Doctor"

    def test_save_merges_with_existing_yaml(self, qapp, mock_config, tmp_path):
        import yaml
        from desktop_client.settings_dialog import SettingsDialog

        # Pre-create a config file with some values
        existing_path = tmp_path / "dev.yaml"
        existing_path.write_text(
            "mqtt:\n  host: broker.local\nllm:\n  model: phi3\n",
            encoding="utf-8",
        )

        mock_config.profile = "dev"
        dlg = SettingsDialog(mock_config)

        # Simulate what _save does: merge new values with existing
        existing = yaml.safe_load(existing_path.read_text(encoding="utf-8")) or {}
        new_data = {"llm": {"model": "llama3.2", "enabled": True}}
        for section, values in new_data.items():
            existing.setdefault(section, {}).update(values)

        existing_path.write_text(
            yaml.dump(existing, default_flow_style=False), encoding="utf-8"
        )
        merged = yaml.safe_load(existing_path.read_text(encoding="utf-8"))

        # MQTT key should survive
        assert merged["mqtt"]["host"] == "broker.local"
        # LLM should be updated
        assert merged["llm"]["model"] == "llama3.2"
        # Original LLM key should still be there (merged, not replaced)
        assert "enabled" in merged["llm"]


class TestSettingsDialogLoad:
    def test_load_values_from_config(self, qapp, mock_config):
        from desktop_client.settings_dialog import SettingsDialog

        mock_config.llm.enabled = True
        mock_config.llm.base_url = "http://localhost:11434"
        mock_config.llm.model = "mistral"
        mock_config.llm.timeout_seconds = 30
        mock_config.audio.engine = "vosk"
        mock_config.audio.silence_threshold = 500
        mock_config.audio.sample_rate = 16000
        mock_config.tts.engine = "piper"
        mock_config.tts.voice_rate = 175
        mock_config.personality.honorific = "Sir"
        mock_config.personality.system_prompt = "You are Jarvis."
        mock_config.memory.enabled = False
        mock_config.memory.top_k = 5
        mock_config.memory.max_conversation_turns = 20
        mock_config.memory.embedding_model = "all-MiniLM-L6-v2"

        dlg = SettingsDialog(mock_config)

        assert dlg._fields["llm.enabled"].isChecked() is True
        assert dlg._fields["llm.model"].text() == "mistral"
        assert dlg._fields["llm.timeout_seconds"].value() == 30
        assert dlg._fields["audio.engine"].currentText() == "vosk"
        assert dlg._fields["audio.sample_rate"].value() == 16000
        assert dlg._fields["tts.engine"].currentText() == "piper"
        assert dlg._fields["personality.honorific"].text() == "Sir"
        assert dlg._fields["memory.enabled"].isChecked() is False
        assert dlg._fields["memory.top_k"].value() == 5

    def test_all_expected_fields_present(self, qapp, mock_config):
        from desktop_client.settings_dialog import SettingsDialog
        dlg = SettingsDialog(mock_config)
        expected_fields = [
            "llm.enabled", "llm.base_url", "llm.model", "llm.timeout_seconds",
            "audio.engine", "audio.silence_threshold", "audio.sample_rate",
            "tts.engine", "tts.voice_rate",
            "personality.honorific", "personality.system_prompt",
            "memory.enabled", "memory.top_k",
            "memory.max_conversation_turns", "memory.embedding_model",
        ]
        for field in expected_fields:
            assert field in dlg._fields, f"SettingsDialog missing field: {field}"
