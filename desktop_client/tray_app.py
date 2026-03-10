"""
tray_app.py — Jarvis system-tray icon + main window launcher.

Connects to MQTT, starts all backend services, launches the main window
with HUD + chat panel, and forwards live transcripts / responses.

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
    """Route MQTT messages into the HUD and chat panel."""
    main_win = userdata.get("main_window")
    hud      = main_win.hud_panel if main_win else None
    chat     = main_win.chat_panel if main_win else None
    try:
        payload = msg.payload.decode("utf-8")
        data    = json.loads(payload) if payload.startswith("{") else {}

        if msg.topic == TOPIC_STT_TEXT:
            text = data.get("text", payload)
            userdata["last_transcript"] = text
            if hud:
                hud.set_listening(False)
                hud.set_transcript(text, userdata.get("last_response", ""))
            if chat:
                chat.add_message("user", text)

        elif msg.topic == TOPIC_TTS_TEXT:
            text = data.get("text", payload)
            userdata["last_response"] = text
            if hud:
                hud.set_transcript(userdata.get("last_transcript", ""), text)
            if chat:
                chat.add_message("jarvis", text)

        elif msg.topic.startswith("jarvis/status/"):
            service = msg.topic.split("/")[-1].upper()
            online  = data.get("status", "online") == "online"
            if main_win:
                main_win.update_service_status({service: online})

    except Exception:
        pass


# ---------------------------------------------------------------------------
# PySide6 tray + main window
# ---------------------------------------------------------------------------

def run_pyside6(config, mqtt_client: mqtt.Client, userdata: dict) -> None:
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
    from PySide6.QtGui import QAction, QIcon, QPixmap, QColor
    from PySide6.QtCore import QTimer

    from desktop_client.main_window import JarvisMainWindow
    from desktop_client.service_manager import ServiceManager
    from desktop_client.settings_dialog import SettingsDialog

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # ── Service manager — start all backends ──────────────────────────────
    svc_mgr = ServiceManager()

    # ── Main window ───────────────────────────────────────────────────────
    main_win = JarvisMainWindow()
    userdata["main_window"] = main_win

    hud  = main_win.hud_panel
    chat = main_win.chat_panel

    # Wire service manager → main window status
    svc_mgr.service_status_changed.connect(main_win.update_service_status)

    # Wire HUD signals → MQTT
    def _on_listen():
        mqtt_client.publish(TOPIC_AUDIO_TRIGGER, "{}", qos=1)
        hud.set_listening(True)

    def _on_dnd(enabled: bool):
        mqtt_client.publish(TOPIC_DND, json.dumps({"enabled": enabled}), qos=0)

    hud.listen_requested.connect(_on_listen)
    hud.dnd_toggled.connect(_on_dnd)

    # Wire chat settings button → settings dialog
    def _open_settings():
        # Always reload from YAML so the dialog reflects the latest saved values,
        # not the stale in-memory config captured at startup.
        fresh_cfg = load_config()
        dlg = SettingsDialog(fresh_cfg, main_win)
        if dlg.exec():   # exec() returns 1 (Accepted) when user clicks Save
            # Restart STT and TTS so they pick up the new device settings from YAML.
            svc_mgr.restart_service("stt")
            svc_mgr.restart_service("tts")

    chat.settings_requested.connect(_open_settings)

    # Start backend services (this also starts the MQTT broker)
    profile = getattr(config, "profile", "dev")
    svc_mgr.start_all(profile)

    # Now the broker is up — connect MQTT
    mqtt_client.connect(config.mqtt.host, config.mqtt.port, 60)
    subscribe_and_track(mqtt_client, TOPIC_STT_TEXT, qos=0)
    subscribe_and_track(mqtt_client, TOPIC_TTS_TEXT, qos=0)
    subscribe_and_track(mqtt_client, TOPIC_STATUS, qos=0)
    mqtt_client.loop_start()

    # Update memory status in status bar
    mem_status = "enabled" if getattr(config, "memory", None) and config.memory.enabled else "disabled"
    main_win.status_bar.set_memory_status(mem_status)

    # ── Tray icon (small cyan square) ─────────────────────────────────────
    px = QPixmap(22, 22)
    px.fill(QColor(0, 212, 255))
    tray = QSystemTrayIcon(QIcon(px), app)
    tray.setToolTip("Jarvis")

    menu = QMenu()

    show_action = QAction("Show Window")
    show_action.triggered.connect(main_win.show)
    menu.addAction(show_action)

    hide_action = QAction("Hide Window")
    hide_action.triggered.connect(main_win.hide)
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

    def _on_quit():
        svc_mgr.stop_all()
        app.quit()

    quit_action = QAction("Quit")
    quit_action.triggered.connect(_on_quit)
    menu.addAction(quit_action)

    tray.setContextMenu(menu)
    tray.show()
    main_win.show()

    # Ensure services stop when the app exits
    app.aboutToQuit.connect(svc_mgr.stop_all)

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

    userdata: dict = {"last_transcript": "", "last_response": "", "main_window": None}

    client = make_mqtt_client(config, "tray")
    # Merge userdata with the reconnect tracking dict set by make_mqtt_client
    client.user_data_get().update(userdata)
    client.on_message = _on_message
    # NOTE: client.connect() is called inside run_pyside6() after the broker starts

    try:
        run_pyside6(config, client, userdata)
    except ImportError:
        LOG.warning("PySide6 not found — falling back to pystray (no HUD)")
        # Fallback: broker must already be running externally
        try:
            client.connect(config.mqtt.host, config.mqtt.port, 60)
            subscribe_and_track(client, TOPIC_STT_TEXT, qos=0)
            subscribe_and_track(client, TOPIC_TTS_TEXT, qos=0)
            subscribe_and_track(client, TOPIC_STATUS, qos=0)
            client.loop_start()
            run_pystray(config, client, userdata)
        except ImportError:
            LOG.warning("pystray not found either — running headless. Trigger via MQTT.")
            import time
            while True:
                time.sleep(60)
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
