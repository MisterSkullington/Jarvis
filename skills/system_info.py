"""
System info skill: reports CPU, memory, and disk usage.
Intent: "system_status"
"""
from __future__ import annotations

SKILL_NAME = "system_info"
INTENTS = ["system_status"]


def handle_system_status(text, entities, config, mqtt_client, user):
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return (
            f"System status, {user.preferred_address}: "
            f"CPU at {cpu}%, memory at {mem.percent}% "
            f"({mem.used // (1024**3)}GB of {mem.total // (1024**3)}GB), "
            f"disk at {disk.percent}% used."
        )
    except ImportError:
        return f"I'm unable to check system resources at the moment, {user.preferred_address}."


def register(registry):
    registry["system_status"] = handle_system_status
