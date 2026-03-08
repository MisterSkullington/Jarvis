#!/usr/bin/env python3
"""Thin wrapper that starts the amqtt MQTT broker with the project broker config."""
import asyncio
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] :: %(levelname)s - %(message)s")

CONFIG = {
    "listeners": {
        "default": {
            "type": "tcp",
            "bind": "0.0.0.0:1883",
        }
    },
    "auth": {"allow-anonymous": True},
}


async def _run() -> None:
    from amqtt.broker import Broker
    broker = Broker(CONFIG)
    await broker.start()
    print("Broker started on 0.0.0.0:1883", flush=True)
    # Run until cancelled
    try:
        await asyncio.get_event_loop().create_future()
    except (asyncio.CancelledError, KeyboardInterrupt):
        await broker.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass
