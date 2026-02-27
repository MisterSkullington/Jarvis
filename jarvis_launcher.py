#!/usr/bin/env python3
"""
J.A.R.V.I.S. Launcher — starts all services with multiplexed log output.

Usage:
    python jarvis_launcher.py              # start core services
    python jarvis_launcher.py --all        # start all services including optional ones
    python jarvis_launcher.py --services nlu_agent orchestrator scheduler web_ui
"""
from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import threading
import time
from typing import Dict, List, Optional

CORE_SERVICES = [
    ("nlu_agent", "services.nlu_agent.main"),
    ("orchestrator", "services.orchestrator.main"),
    ("scheduler", "services.scheduler.main"),
    ("web_ui", "services.web_ui.main"),
]

OPTIONAL_SERVICES = [
    ("tts", "services.tts.main"),
    ("stt", "services.stt.main"),
    ("wakeword", "services.wakeword.main"),
    ("proactive", "services.proactive.main"),
    ("monitor", "services.monitor.main"),
]

COLOURS = {
    "nlu_agent": "\033[36m",
    "orchestrator": "\033[34m",
    "scheduler": "\033[33m",
    "web_ui": "\033[35m",
    "tts": "\033[32m",
    "stt": "\033[31m",
    "wakeword": "\033[37m",
    "proactive": "\033[96m",
    "monitor": "\033[93m",
}
RESET = "\033[0m"


class ServiceManager:
    def __init__(self):
        self._processes: Dict[str, subprocess.Popen] = {}
        self._running = True

    def start(self, name: str, module: str) -> None:
        colour = COLOURS.get(name, "")
        proc = subprocess.Popen(
            [sys.executable, "-m", module],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._processes[name] = proc
        tag = f"{colour}[{name:>12}]{RESET}"
        print(f"{tag} Started (PID {proc.pid})")

        def stream():
            try:
                for line in proc.stdout:
                    if self._running:
                        print(f"{tag} {line.rstrip()}")
            except Exception:
                pass
        t = threading.Thread(target=stream, daemon=True)
        t.start()

    def stop_all(self) -> None:
        self._running = False
        for name, proc in self._processes.items():
            print(f"Stopping {name} (PID {proc.pid})...")
            proc.terminate()
        for name, proc in self._processes.items():
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        print("All services stopped.")

    def wait(self) -> None:
        try:
            while self._running:
                for name, proc in list(self._processes.items()):
                    ret = proc.poll()
                    if ret is not None:
                        colour = COLOURS.get(name, "")
                        print(f"{colour}[{name:>12}]{RESET} Exited with code {ret}")
                        self._processes.pop(name, None)
                if not self._processes:
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down J.A.R.V.I.S....")
            self.stop_all()


def main():
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S. Service Launcher")
    parser.add_argument("--all", action="store_true", help="Start all services including optional")
    parser.add_argument("--services", nargs="+", help="Specific services to start")
    args = parser.parse_args()

    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║     J.A.R.V.I.S. Service Launcher        ║")
    print("  ║     Just A Rather Very Intelligent System  ║")
    print("  ╚══════════════════════════════════════════╝")
    print()

    all_services = dict(CORE_SERVICES + OPTIONAL_SERVICES)

    if args.services:
        to_start = [(name, all_services[name]) for name in args.services if name in all_services]
    elif args.all:
        to_start = CORE_SERVICES + OPTIONAL_SERVICES
    else:
        to_start = CORE_SERVICES

    manager = ServiceManager()

    def handle_signal(sig, frame):
        manager.stop_all()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    for name, module in to_start:
        manager.start(name, module)
        time.sleep(0.5)

    print(f"\n  {len(to_start)} services started. Press Ctrl+C to stop.\n")
    manager.wait()


if __name__ == "__main__":
    main()
