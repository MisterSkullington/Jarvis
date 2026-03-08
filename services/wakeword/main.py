"""
Wakeword service: listens for wake word (e.g. "Jarvis") and publishes jarvis/audio/start on MQTT.
Uses openwakeword when available; otherwise supports manual trigger via MQTT (jarvis/audio/trigger).
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

# Add repo root for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import paho.mqtt.client as mqtt

from jarvis_core import load_config, configure_logging, make_mqtt_client

LOG = logging.getLogger(__name__)

TOPIC_AUDIO_START = "jarvis/audio/start"
TOPIC_TRIGGER = "jarvis/audio/trigger"
TOPIC_STATUS = "jarvis/status/wakeword"


def run_wakeword_engine(config, mqtt_client: mqtt.Client) -> None:
    """Run openwakeword detector if available; otherwise wait for manual trigger."""
    try:
        import openwakeword
        import sounddevice as sd
        import numpy as np
    except ImportError:
        LOG.warning("openwakeword or sounddevice not installed; using MQTT trigger only")
        return

    model = openwakeword.Model(wakeword_names=["jarvis"])
    sample_rate = config.audio.sample_rate
    block_ms = 256
    block_size = int(sample_rate * block_ms / 1000)

    def audio_callback(indata, frames, time_info, status):
        if status:
            LOG.debug("sounddevice status: %s", status)
        audio = (indata[:, 0] * 32767).astype(np.int16).tobytes()
        prediction = model.predict(audio)
        if prediction and any(v > (0.5 * config.wakeword.sensitivity) for v in prediction.values()):
            mqtt_client.publish(TOPIC_AUDIO_START, json.dumps({"source": "wakeword"}), qos=1)
            LOG.info("Wake word detected, published %s", TOPIC_AUDIO_START)

    with sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        blocksize=block_size,
        callback=audio_callback,
    ):
        LOG.info("Wake word engine listening (sensitivity=%.2f)", config.wakeword.sensitivity)
        while True:
            time.sleep(1)


def on_trigger(client: mqtt.Client, userdata, msg) -> None:
    """Manual trigger: republish as audio/start so STT begins."""
    client.publish(TOPIC_AUDIO_START, msg.payload or b"{}", qos=1)
    LOG.info("Manual trigger received, published %s", TOPIC_AUDIO_START)


def main() -> None:
    config = load_config()
    configure_logging(config.log_level, "wakeword")

    client = make_mqtt_client(config, "wakeword")
    client.connect(config.mqtt.host, config.mqtt.port, 60)
    client.subscribe(TOPIC_TRIGGER, qos=1)
    client.message_callback_add(TOPIC_TRIGGER, on_trigger)
    client.loop_start()

    client.publish(TOPIC_STATUS, json.dumps({"status": "ready"}), qos=0)

    try:
        if config.wakeword.enabled:
            try:
                run_wakeword_engine(config, client)
            except Exception as e:
                LOG.warning("Wake word engine failed (%s); using MQTT trigger only", e)
        LOG.info("Listening for MQTT trigger on %s", TOPIC_TRIGGER)
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
