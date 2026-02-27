"""System control: lock PC, volume, open app. Uses safety allow-list."""
from __future__ import annotations

import subprocess
from typing import Any, Optional

from jarvis_core import load_config


def run_system_command(command_id: str) -> dict[str, Any]:
    """Run a command from the allowed list (e.g. lock_pc)."""
    config = load_config()
    allowed = getattr(config.safety, "allowed_system_commands", {}) or {}
    cmd = allowed.get(command_id)
    if not cmd:
        return {"ok": False, "error": "Command not allowed"}
    try:
        subprocess.Popen(cmd, shell=True)
        return {"ok": True, "command_id": command_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}
