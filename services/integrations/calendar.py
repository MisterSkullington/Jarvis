"""Calendar integration: local ICS file and optional Google Calendar via env."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List

from jarvis_core import load_config


def _parse_ics(path: Path) -> List[dict[str, Any]]:
    """Parse a local .ics file and return list of events with start, end, summary."""
    events = []
    if not path.exists():
        return events
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            current = {}
            for line in f:
                line = line.strip()
                if line == "BEGIN:VEVENT":
                    current = {}
                elif line == "END:VEVENT":
                    if current.get("summary"):
                        events.append(current)
                    current = {}
                elif line.startswith("SUMMARY:"):
                    current["summary"] = line[7:].replace("\\n", " ").strip()
                elif line.startswith("DTSTART"):
                    raw = line.split(":", 1)[-1].replace("Z", "+00:00")[:15]
                    if len(raw) >= 8:
                        current["start"] = raw  # YYYYMMDD or YYYYMMDDTHHMMSS
                elif line.startswith("DTEND"):
                    raw = line.split(":", 1)[-1].replace("Z", "+00:00")[:15]
                    if len(raw) >= 8:
                        current["end"] = raw
    except Exception:
        pass
    return events


def get_next_events(limit: int = 5) -> List[dict[str, Any]]:
    """
    Return next N calendar events. Set JARVIS_ICS_PATH to a local .ics file path.
    Optional: Google Calendar via OAuth (not implemented here; use gcal CLI or token in env).
    """
    ics_path = os.getenv("JARVIS_ICS_PATH", "").strip()
    if ics_path:
        path = Path(ics_path)
        events = _parse_ics(path)
        # Sort by start; optionally filter to future only
        events.sort(key=lambda e: e.get("start", ""))
        return events[:limit]
    return []
