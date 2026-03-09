"""
tray_app.py — Jarvis system-tray icon + HUD launcher.

Connects to MQTT, forwards live transcripts / responses to the HUD,
and exposes Listen, DND, and Quit actions from a minimal tray menu.

Falls back gracefully if PySide6 is missing (headless MQTT-only mode).
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import paho.mqtt.client as mqtt

from jarvis_core import load_config, configure_logging
from jarvis_core.mqtt_helpers import make_mqtt_client, subscribe_and_track

LOG = logging.getLogger(__name__)

TOPIC_AUDIO_TRIGGER = "jarvis/audio/trigger"
TOPIC_STT_TEXT      = "jarvis/stt/text"
TOPIC_TTS_TEXT      = "jarvis/tts/text"
TOPIC_STATUS        = "jarvis/status/#"
TOPIC_DND           = "jarvis/ui/dnd"


# ---------------------------------------------------------------------------
# MQTT helpers
# ---------------------------------------------------------------------------

def _on_message(client: mqtt.Client, userdata, msg) -> None:
    """Route MQTT messages into the HUD (if present) or a simple log."""
    hud     = userdata.get("hud")
    try:
        payload = msg.payload.decode("utf-8")
        data    = json.loads(payload) if payload.startswith("{") else {}

        if msg.topic == TOPIC_STT_TEXT:
            text = data.get("text", payload)
            userdata["last_transcript"] = text
            if hud:
                hud.set_listening(False)
                hud.set_transcript(text, userdata.get("last_response", ""))

        elif msg.topic == TOPIC_TTS_TEXT:
            text = data.get("text", payload)
            userdata["last_response"] = text
            if hud:
                hud.set_transcript(userdata.get("last_transcript", ""), text)

        elif msg.topic.startswith("jarvis/status/"):
            service = msg.topic.split("/")[-1].upper()
            online  = data.get("status", "online") == "online"
            if hud:
                hud.set_service_status({service: online})

    except Exception:
        pass


# ---------------------------------------------------------------------------
# PySide6 tray + HUD
# ---------------------------------------------------------------------------

def run_pyside6(config, mqtt_client: mqtt.Client, userdata: dict) -> None:
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
    from PySide6.QtGui import QAction, QIcon, QPixmap, QColor
    from PySide6.QtCore import QTimer

    from desktop_client.hud_overlay import JarvisHUD

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # ── HUD ─────────────────────────────────────────────────────────────────
    hud = JarvisHUD()
    userdata["hud"] = hud

    # Wire HUD signals → MQTT
    def _on_listen():
        mqtt_client.publish(TOPIC_AUDIO_TRIGGER, "{}", qos=1)
        hud.set_listening(True)

    def _on_dnd(enabled: bool):
        mqtt_client.publish(TOPIC_DND, json.dumps({"enabled": enabled}), qos=0)

    hud.listen_requested.connect(_on_listen)
    hud.dnd_toggled.connect(_on_dnd)

    # ── Tray icon (small cyan square — replace with a real .ico if desired) ──
    px = QPixmap(22, 22)
    px.fill(QColor(0, 212, 255))
    tray = QSystemTrayIcon(QIcon(px), app)
    tray.setToolTip("Jarvis")

    menu = QMenu()

    show_action = QAction("Show HUD")
    show_action.triggered.connect(hud.show)
    menu.addAction(show_action)

    hide_action = QAction("Hide HUD")
    hide_action.triggered.connect(hud.hide)
    menu.addAction(hide_action)

    menu.addSeparator()

    listen_action = QAction("Listen now")
    listen_action.triggered.connect(_on_listen)
    menu.addAction(listen_action)

    dnd_action = QAction("DND: off")
    def _toggle_dnd():
        hud._dnd = not hud._dnd
        hud.dnd_toggled.emit(hud._dnd)
        dnd_action.setText("DND: " + ("on" if hud._dnd else "off"))
    dnd_action.triggered.connect(_toggle_dnd)
    menu.addAction(dnd_action)

    menu.addSeparator()
    quit_action = QAction("Quit")
    quit_action.triggered.connect(app.quit)
    menu.addAction(quit_action)

    tray.setContextMenu(menu)
    tray.show()
    hud.show()  # Show HUD on startup

    # MQTT loop pumped from a QTimer so it doesn't block the event loop
    mqtt_timer = QTimer()
    mqtt_timer.timeout.connect(lambda: None)  # paho loop_start handles threading
    mqtt_timer.start(500)

    sys.exit(app.exec())


# ---------------------------------------------------------------------------
# pystray fallback (no HUD, just tray)
# ---------------------------------------------------------------------------

def run_pystray(config, mqtt_client: mqtt.Client, userdata: dict) -> None:
    import pystray
    from PIL import Image

    icon_img = Image.new("RGB", (64, 64), color=(0, 212, 255))

    def _on_listen(icon, item):
        mqtt_client.publish(TOPIC_AUDIO_TRIGGER, "{}", qos=1)

    def _on_quit(icon, item):
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Listen now", _on_listen),
        pystray.MenuItem("Quit", _on_quit),
    )
    icon = pystray.Icon("jarvis", icon_img, "Jarvis", menu)
    icon.run()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    config = load_config()
    configure_logging(config.log_level, "tray")

    userdata: dict = {"last_transcript": "", "last_response": "", "hud": None}

    client = make_mqtt_client(config, "tray")
    # Merge userdata with the reconnect tracking dict set by make_mqtt_client
    client.user_data_get().update(userdata)
    client.on_message = _on_message
    client.connect(config.mqtt.host, config.mqtt.port, 60)
    subscribe_and_track(client, TOPIC_STT_TEXT, qos=0)
    subscribe_and_track(client, TOPIC_TTS_TEXT, qos=0)
    subscribe_and_track(client, TOPIC_STATUS, qos=0)
    client.loop_start()

    try:
        run_pyside6(config, client, userdata)
    except ImportError:
        LOG.warning("PySide6 not found — falling back to pystray (no HUD)")
        try:
            run_pystray(config, client, userdata)
        except ImportError:
            LOG.warning("pystray not found either — running headless. Trigger via MQTT.")
            import time
            while True:
                time.sleep(60)
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
