#!/usr/bin/env python3
"""
start_all.py — One-click launcher for all Jarvis services.

Usage:
    python scripts/start_all.py [--profile <name>] [--no-proactivity] [--no-vision]

Starts services in dependency order, tails their logs to stdout with coloured
prefixes, and shuts everything down cleanly on Ctrl+C.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

# ---------------------------------------------------------------------------
# ANSI colours (stripped on Windows if no ANSI support)
# ---------------------------------------------------------------------------

_COLOURS = [
    "\033[36m",   # cyan        — nlu_agent
    "\033[33m",   # yellow      — orchestrator
    "\033[32m",   # green       — stt
    "\033[35m",   # magenta     — tts
    "\033[34m",   # blue        — wakeword
    "\033[96m",   # bright cyan — scheduler
    "\033[93m",   # bright yellow — proactivity
    "\033[92m",   # bright green  — vision
]
_RESET = "\033[0m"

# Disable colour on Windows without ANSI support or when not a TTY
if not sys.stdout.isatty() or (sys.platform == "win32" and "ANSICON" not in os.environ
                                and os.environ.get("TERM_PROGRAM") not in ("vscode",)):
    _COLOURS = [""] * len(_COLOURS)
    _RESET = ""


# ---------------------------------------------------------------------------
# Service definitions
# ---------------------------------------------------------------------------

def _service_defs(profile: str, proactivity: bool, vision: bool) -> List[Dict]:
    """Return ordered list of service descriptor dicts."""
    profile_args = ["--profile", profile] if profile else []

    services = [
        {
            "name": "mqtt-broker",
            "cmd": [PYTHON, str(ROOT / "scripts" / "mqtt_broker.py")],
            "ready_marker": "Broker started on",
            "startup_wait": 3.5,
        },
        {
            "name": "nlu_agent",
            "cmd": [PYTHON, "-m", "services.nlu_agent.main"] + profile_args,
            "ready_marker": "Application startup complete",
            "startup_wait": 5.0,
        },
        {
            "name": "orchestrator",
            "cmd": [PYTHON, "-m", "services.orchestrator.main"] + profile_args,
            "ready_marker": "Orchestrator ready",
            "startup_wait": 2.0,
        },
        {
            "name": "scheduler",
            "cmd": [PYTHON, "-m", "services.scheduler.main"] + profile_args,
            "ready_marker": "Scheduler ready",
            "startup_wait": 2.0,
        },
        {
            "name": "tts",
            "cmd": [PYTHON, "-m", "services.tts.main"] + profile_args,
            "ready_marker": "TTS ready",
            "startup_wait": 2.0,
        },
        {
            "name": "stt",
            "cmd": [PYTHON, "-m", "services.stt.main"] + profile_args,
            "ready_marker": "STT ready",
            "startup_wait": 3.0,
        },
        {
            "name": "wakeword",
            "cmd": [PYTHON, "-m", "services.wakeword.main"] + profile_args,
            "ready_marker": "Wakeword ready",
            "startup_wait": 2.0,
        },
    ]

    if proactivity:
        services.append({
            "name": "proactivity",
            "cmd": [PYTHON, "-m", "services.proactivity.main"] + profile_args,
            "ready_marker": "Proactivity service ready",
            "startup_wait": 2.0,
        })

    if vision:
        services.append({
            "name": "vision",
            "cmd": [PYTHON, "-m", "services.vision.main"] + profile_args,
            "ready_marker": "Vision service ready",
            "startup_wait": 3.0,
        })

    return services


# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------

class ManagedProcess:
    """A subprocess with a log-tailing thread and a coloured prefix."""

    def __init__(self, name: str, cmd: List[str], colour: str, ready_marker: str):
        self.name = name
        self.cmd = cmd
        self.colour = colour
        self.ready_marker = ready_marker
        self.proc: Optional[subprocess.Popen] = None
        self._ready = threading.Event()
        self._log_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self.proc = subprocess.Popen(
            self.cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        self._log_thread = threading.Thread(
            target=self._tail_logs, daemon=True, name=f"log-{self.name}"
        )
        self._log_thread.start()

    def _tail_logs(self) -> None:
        prefix = f"{self.colour}[{self.name}]{_RESET} "
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            print(f"{prefix}{line}", flush=True)
            if self.ready_marker and self.ready_marker in line:
                self._ready.set()
        # Process ended — mark ready so callers don't hang
        self._ready.set()

    def wait_ready(self, timeout: float) -> bool:
        """Return True if ready marker was seen within timeout seconds."""
        return self._ready.wait(timeout=timeout)

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Start all Jarvis services.")
    parser.add_argument("--profile", default="", help="Config profile to load (e.g. 'home')")
    parser.add_argument("--no-proactivity", action="store_true", help="Skip proactivity service")
    parser.add_argument("--no-vision", action="store_true", help="Skip vision service")
    args = parser.parse_args()

    service_defs = _service_defs(
        profile=args.profile,
        proactivity=not args.no_proactivity,
        vision=not args.no_vision,
    )

    processes: List[ManagedProcess] = []
    colour_iter = iter(_COLOURS)

    print("=" * 60)
    print("  Jarvis — starting all services")
    print("=" * 60)

    for sdef in service_defs:
        colour = next(colour_iter, "")
        mp = ManagedProcess(
            name=sdef["name"],
            cmd=sdef["cmd"],
            colour=colour,
            ready_marker=sdef.get("ready_marker", ""),
        )
        print(f"{colour}[{sdef['name']}]{_RESET} Starting…")
        try:
            mp.start()
        except FileNotFoundError as exc:
            print(f"  ERROR: could not start {sdef['name']}: {exc}", file=sys.stderr)
            continue

        processes.append(mp)

        wait = sdef.get("startup_wait", 2.0)
        ready = mp.wait_ready(timeout=wait)
        if not ready:
            # Not necessarily bad — ready_marker may not be emitted yet
            print(f"{colour}[{sdef['name']}]{_RESET} (startup marker not seen within {wait}s — continuing)")

    print()
    print("All services launched. Press Ctrl+C to stop.")
    print()

    # -----------------------------------------------------------------------
    # Watch for any crashed processes and report; shutdown on Ctrl+C
    # -----------------------------------------------------------------------

    shutdown_event = threading.Event()

    def _on_signal(*_):
        shutdown_event.set()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    try:
        while not shutdown_event.is_set():
            for mp in processes:
                if not mp.alive:
                    rc = mp.proc.returncode
                    print(f"\n{mp.colour}[{mp.name}]{_RESET} Process exited unexpectedly (rc={rc}). "
                          "Shutting down all services.\n", file=sys.stderr)
                    shutdown_event.set()
                    break
            shutdown_event.wait(timeout=1.0)
    finally:
        print("\nShutting down…")
        for mp in reversed(processes):
            if mp.alive:
                print(f"  Stopping {mp.name}…")
                mp.stop()
        print("All services stopped. Goodbye, Sir.")


if __name__ == "__main__":
    main()
