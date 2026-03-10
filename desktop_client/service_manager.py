"""
service_manager.py — Manages Jarvis backend service processes from the desktop app.

Launches mqtt-broker, nlu_agent, orchestrator, scheduler, tts, stt, wakeword
as subprocesses with crash watchdog and auto-restart (reuses logic from start_all.py).
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QThread, Signal

# Project root — go up from desktop_client/ to the repo root
ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

MAX_RESTARTS = 3
RESTART_WINDOW_SEC = 60


# ---------------------------------------------------------------------------
# ManagedProcess — same logic as scripts/start_all.py
# ---------------------------------------------------------------------------

class _ManagedProcess:
    """A subprocess with log tailing and auto-restart."""

    def __init__(self, name: str, cmd: List[str], ready_marker: str,
                 startup_wait: float = 2.0):
        self.name = name
        self.cmd = cmd
        self.ready_marker = ready_marker
        self.startup_wait = startup_wait
        self.proc: Optional[subprocess.Popen] = None
        self._ready = threading.Event()
        self._log_thread: Optional[threading.Thread] = None
        self._crash_times: List[float] = []
        self._stopped = False
        self._log_callback = None  # set by ServiceManager

    def start(self) -> None:
        self._stopped = False
        self._ready.clear()
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
            target=self._tail_logs, daemon=True, name=f"log-{self.name}",
        )
        self._log_thread.start()

    def _tail_logs(self) -> None:
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            if self._log_callback:
                self._log_callback(self.name, line)
            if self.ready_marker and self.ready_marker in line:
                self._ready.set()
        self._ready.set()

    def wait_ready(self, timeout: float) -> bool:
        return self._ready.wait(timeout=timeout)

    def stop(self) -> None:
        self._stopped = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def maybe_restart(self) -> bool:
        if self._stopped or self.alive:
            return True
        now = time.time()
        self._crash_times = [t for t in self._crash_times if now - t < RESTART_WINDOW_SEC]
        self._crash_times.append(now)
        if len(self._crash_times) > MAX_RESTARTS:
            return False
        try:
            self.start()
            self.wait_ready(self.startup_wait)
        except FileNotFoundError:
            return False
        return True

    def restart(self) -> None:
        """Stop the process (if running) and start it again with a fresh state."""
        self.stop()
        time.sleep(0.3)           # brief gap so the OS releases the port/device
        self._stopped = False
        self._crash_times = []    # reset crash counter so watchdog doesn't throttle it
        try:
            self.start()
            self.wait_ready(self.startup_wait)
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Watchdog thread — monitors processes and emits Qt signals
# ---------------------------------------------------------------------------

class _WatchdogWorker(QObject):
    """Runs in a QThread, polls process health every 2s."""

    status_changed = Signal(str, bool)   # (service_name, alive)
    log_line       = Signal(str, str)    # (service_name, line)

    def __init__(self, processes: List[_ManagedProcess]):
        super().__init__()
        self._processes = processes
        self._running = True
        self._prev_status: Dict[str, bool] = {}

    def run(self) -> None:
        # Wire log callbacks
        for mp in self._processes:
            mp._log_callback = lambda name, line: self.log_line.emit(name, line)

        while self._running:
            for mp in self._processes:
                alive = mp.alive
                prev = self._prev_status.get(mp.name)
                if prev is None or prev != alive:
                    self._prev_status[mp.name] = alive
                    self.status_changed.emit(mp.name, alive)

                if not alive and not mp._stopped:
                    mp.maybe_restart()

            time.sleep(2.0)

    def stop(self) -> None:
        self._running = False


# ---------------------------------------------------------------------------
# ServiceManager — public API for the desktop app
# ---------------------------------------------------------------------------

# Map short display names to service matrix keys used by the HUD
_NAME_TO_HUD = {
    "mqtt-broker": None,  # no HUD dot for the broker
    "nlu_agent":   "NLU",
    "orchestrator": "ORCH",
    "stt":         "STT",
    "tts":         "TTS",
    "scheduler":   "SCHED",
    "wakeword":    None,
}


class ServiceManager(QObject):
    """
    Manages all Jarvis backend services as subprocesses.

    Usage::

        mgr = ServiceManager()
        mgr.service_status_changed.connect(hud.set_service_status)
        mgr.start_all("dev")
        # ... later ...
        mgr.stop_all()
    """

    service_status_changed = Signal(dict)   # {HUD_KEY: bool, ...}
    log_line               = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._processes: List[_ManagedProcess] = []
        self._thread: Optional[QThread] = None
        self._worker: Optional[_WatchdogWorker] = None

    def start_all(self, profile: str = "dev") -> None:
        """Launch all backend services in dependency order."""
        profile_args = ["--profile", profile] if profile else []

        service_defs = [
            ("mqtt-broker", [PYTHON, str(ROOT / "scripts" / "mqtt_broker.py")],
             "Broker started on", 3.5),
            ("nlu_agent", [PYTHON, "-m", "services.nlu_agent.main"] + profile_args,
             "Application startup complete", 5.0),
            ("orchestrator", [PYTHON, "-m", "services.orchestrator.main"] + profile_args,
             "Orchestrator ready", 2.0),
            ("scheduler", [PYTHON, "-m", "services.scheduler.main"] + profile_args,
             "Scheduler ready", 2.0),
            ("tts", [PYTHON, "-m", "services.tts.main"] + profile_args,
             "TTS ready", 2.0),
            ("stt", [PYTHON, "-m", "services.stt.main"] + profile_args,
             "STT ready", 3.0),
            ("wakeword", [PYTHON, "-m", "services.wakeword.main"] + profile_args,
             "Wakeword ready", 2.0),
        ]

        for name, cmd, marker, wait in service_defs:
            mp = _ManagedProcess(name, cmd, marker, wait)
            try:
                mp.start()
                mp.wait_ready(wait)
            except FileNotFoundError:
                continue
            self._processes.append(mp)

        # Start watchdog thread
        self._thread = QThread()
        self._worker = _WatchdogWorker(self._processes)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.status_changed.connect(self._on_status_changed)
        self._worker.log_line.connect(self.log_line.emit)

        self._thread.start()

    def stop_all(self) -> None:
        """Gracefully stop all services in reverse order."""
        if self._worker:
            self._worker.stop()
        if self._thread:
            self._thread.quit()
            self._thread.wait(5000)

        for mp in reversed(self._processes):
            if mp.alive:
                mp.stop()
        self._processes.clear()

    def get_statuses(self) -> Dict[str, bool]:
        """Return current service statuses as HUD-compatible dict."""
        result: Dict[str, bool] = {}
        for mp in self._processes:
            hud_key = _NAME_TO_HUD.get(mp.name)
            if hud_key:
                result[hud_key] = mp.alive
        return result

    def restart_service(self, name: str) -> bool:
        """
        Restart a single named service so it picks up new config from YAML.
        Returns True if the service was found, False otherwise.
        """
        for mp in self._processes:
            if mp.name == name:
                mp.restart()
                return True
        return False

    def _on_status_changed(self, name: str, alive: bool) -> None:
        hud_key = _NAME_TO_HUD.get(name)
        if hud_key:
            self.service_status_changed.emit({hud_key: alive})
