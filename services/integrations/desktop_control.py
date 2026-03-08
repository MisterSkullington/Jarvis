"""
Desktop automation integration (Phase 4).

Provides open_application() and send_keys() with a safety allow-list
and rate limiting. Only apps in config.desktop.allowed_apps may be opened.

Requires: pip install "jarvis-assistant[desktop]"  (pyautogui, mss)
"""
from __future__ import annotations

import logging
import subprocess
import time
from typing import Any, Dict

LOG = logging.getLogger(__name__)

# Known Windows app launch commands
_APP_COMMANDS: Dict[str, str] = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "explorer": "explorer.exe",
    "chrome": "start chrome",
    "firefox": "start firefox",
    "edge": "start msedge",
    "cmd": "start cmd",
    "powershell": "start powershell",
    "word": "start winword",
    "excel": "start excel",
    "outlook": "start outlook",
    "spotify": "start spotify",
    "vlc": "start vlc",
}

_last_action_time: float = 0.0


def _rate_check(config) -> bool:
    """Return True if within rate limit, False if too soon."""
    global _last_action_time
    rl = getattr(getattr(config, "desktop", None), "rate_limit_seconds", 5)
    if time.time() - _last_action_time < rl:
        return False
    return True


def open_application(app_name: str, config) -> Dict[str, Any]:
    """
    Open an application by name.

    The app_name must be in config.desktop.allowed_apps (case-insensitive).
    Returns {"ok": bool, "message": str}.
    """
    if not getattr(getattr(config, "desktop", None), "enabled", False):
        return {"ok": False, "message": "Desktop automation is disabled in config."}

    allowed = [a.lower() for a in getattr(config.desktop, "allowed_apps", [])]
    name_lower = app_name.lower().strip()

    if name_lower not in allowed:
        return {
            "ok": False,
            "message": f"'{app_name}' is not in the desktop.allowed_apps list.",
        }

    if not _rate_check(config):
        return {"ok": False, "message": "Rate limited — please wait before another desktop action."}

    cmd = _APP_COMMANDS.get(name_lower, f"start {name_lower}")
    try:
        subprocess.Popen(cmd, shell=True)
        _last_action_time = time.time()
        LOG.info("Opened application: %s (cmd: %s)", app_name, cmd)
        return {"ok": True, "message": f"Opening {app_name}."}
    except Exception as exc:
        LOG.warning("Failed to open %s: %s", app_name, exc)
        return {"ok": False, "message": str(exc)}


def send_keys(keys: str, config) -> Dict[str, Any]:
    """
    Send keystrokes to the active window.

    keys is a pyautogui hotkey/typewrite string, e.g. "ctrl+c", "hello world".
    Returns {"ok": bool, "message": str}.

    SECURITY: only call this after explicit user consent. Never send passwords.
    """
    if not getattr(getattr(config, "desktop", None), "enabled", False):
        return {"ok": False, "message": "Desktop automation is disabled in config."}

    if not _rate_check(config):
        return {"ok": False, "message": "Rate limited — please wait before another desktop action."}

    try:
        import pyautogui
    except ImportError:
        return {
            "ok": False,
            "message": "pyautogui not installed. Run: pip install 'jarvis-assistant[desktop]'",
        }

    try:
        # Distinguish hotkeys (contain '+') from plain text typing
        if "+" in keys and len(keys) <= 20:
            parts = [p.strip() for p in keys.split("+")]
            pyautogui.hotkey(*parts)
        else:
            pyautogui.typewrite(keys, interval=0.05)
        _last_action_time = time.time()
        LOG.info("Sent keys: %s", keys[:40])
        return {"ok": True, "message": f"Sent keys: {keys[:40]}"}
    except Exception as exc:
        LOG.warning("send_keys failed: %s", exc)
        return {"ok": False, "message": str(exc)}
