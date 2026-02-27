"""
Windows tray app for Jarvis: status, last transcript/response, mute mic, trigger listen, Do Not Disturb.
Uses PySide6 (or fallback to pystray + minimal UI). Communicates via MQTT.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import paho.mqtt.client as mqtt

from jarvis_core import load_config, configure_logging

LOG = logging.getLogger(__name__)

TOPIC_AUDIO_TRIGGER = "jarvis/audio/trigger"
TOPIC_STT_TEXT = "jarvis/stt/text"
TOPIC_TTS_TEXT = "jarvis/tts/text"
TOPIC_STATUS = "jarvis/status/#"
TOPIC_DND = "jarvis/ui/dnd"  # do not disturb

_last_transcript = ""
_last_response = ""
_dnd = False


def on_message(client: mqtt.Client, userdata, msg) -> None:
    global _last_transcript, _last_response
    try:
        payload = msg.payload.decode("utf-8")
        if msg.topic == TOPIC_STT_TEXT:
            data = json.loads(payload) if payload.startswith("{") else {}
            _last_transcript = data.get("text", payload)
        elif msg.topic == TOPIC_TTS_TEXT:
            data = json.loads(payload) if payload.startswith("{") else {}
            _last_response = data.get("text", payload)
    except Exception:
        pass


def run_tray_pyside6(config) -> None:
    """Use PySide6 for system tray and menu."""
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
    from PySide6.QtGui import QAction, QIcon
    from PySide6.QtCore import QTimer

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    tray = QSystemTrayIcon(app)
    try:
        tray.setIcon(QIcon())  # optional: set a .ico
    except Exception:
        pass
    tray.setToolTip("Jarvis")

    menu = QMenu()
    status_action = QAction("Status: connected")
    menu.addAction(status_action)
    menu.addSeparator()
    trigger_action = QAction("Listen now")
    def trigger():
        _client.publish(TOPIC_AUDIO_TRIGGER, "{}", qos=1)
    trigger_action.triggered.connect(trigger)
    menu.addAction(trigger_action)
    dnd_action = QAction("Do not disturb: off")
    def toggle_dnd():
        global _dnd
        _dnd = not _dnd
        _client.publish(TOPIC_DND, json.dumps({"enabled": _dnd}), qos=0)
        dnd_action.setText("Do not disturb: " + ("on" if _dnd else "off"))
    dnd_action.triggered.connect(toggle_dnd)
    menu.addAction(dnd_action)
    menu.addSeparator()
    last_t = QAction("Last: (none)")
    last_t.setEnabled(False)
    menu.addAction(last_t)
    last_r = QAction("Response: (none)")
    last_r.setEnabled(False)
    menu.addAction(last_r)

    def update_tip():
        last_t.setText(("Last: " + _last_transcript[:40] + "…") if len(_last_transcript) > 40 else ("Last: " + (_last_transcript or "(none)")))
        last_r.setText(("Response: " + _last_response[:40] + "…") if len(_last_response) > 40 else ("Response: " + (_last_response or "(none)")))
    timer = QTimer()
    timer.timeout.connect(update_tip)
    timer.start(2000)

    menu.addSeparator()
    quit_action = QAction("Quit")
    quit_action.triggered.connect(app.quit)
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.show()
    sys.exit(app.exec())


def run_tray_pystray(config) -> None:
    """Fallback: pystray icon with simple menu (no transcript display)."""
    import pystray
    from PIL import Image
    icon_image = Image.new("RGB", (64, 64), color="blue")
    def on_trigger(icon, item):
        _client.publish(TOPIC_AUDIO_TRIGGER, "{}", qos=1)
    def on_quit(icon, item):
        icon.stop()
    menu = pystray.Menu(
        pystray.MenuItem("Listen now", on_trigger),
        pystray.MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon("jarvis", icon_image, "Jarvis", menu)
    icon.run()


_client: mqtt.Client = None


def main() -> None:
    global _client
    config = load_config()
    configure_logging(config.log_level, "tray")
    _client = mqtt.Client(client_id=f"{config.mqtt.client_id_prefix}-tray")
    if config.mqtt.username:
        _client.username_pw_set(config.mqtt.username, config.mqtt.password)
    _client.on_message = on_message
    _client.connect(config.mqtt.host, config.mqtt.port, 60)
    _client.subscribe(TOPIC_STT_TEXT, qos=0)
    _client.subscribe(TOPIC_TTS_TEXT, qos=0)
    _client.subscribe(TOPIC_STATUS, qos=0)
    _client.loop_start()
    try:
        run_tray_pyside6(config)
    except ImportError:
        try:
            run_tray_pystray(config)
        except ImportError:
            LOG.warning("Install PySide6 or pystray for tray UI. Running headless; trigger via MQTT jarvis/audio/trigger")
            while True:
                import time
                time.sleep(60)
    finally:
        _client.loop_stop()
        _client.disconnect()


if __name__ == "__main__":
    main()
