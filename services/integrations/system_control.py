"""System control: lock PC, volume, open app. Uses safety allow-list."""
from __future__ import annotations

import re
import shlex
import subprocess
from typing import Any

from jarvis_core import load_config

# Only allow alphanumeric + underscore in command IDs
_CMD_ID_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def run_system_command(command_id: str) -> dict[str, Any]:
    """Run a command from the allowed list (e.g. lock_pc)."""
    if not command_id or not _CMD_ID_RE.match(command_id):
        return {"ok": False, "error": "Invalid command_id"}

    config = load_config()
    allowed = getattr(config.safety, "allowed_system_commands", {}) or {}
    cmd = allowed.get(command_id)
    if not cmd:
        return {"ok": False, "error": "Command not allowed"}
    try:
        # Split string into args list to avoid shell=True injection risk
        args = shlex.split(cmd)
        subprocess.Popen(args)
        return {"ok": True, "command_id": command_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}
