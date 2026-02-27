"""
STT service: subscribes to jarvis/audio/start (or runs in continuous mode), records audio
with silence detection, transcribes with Vosk, and publishes JSON to jarvis/stt/text.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import paho.mqtt.client as mqtt
import sounddevice as sd

from jarvis_core import load_config, configure_logging

LOG = logging.getLogger(__name__)

TOPIC_AUDIO_START = "jarvis/audio/start"
TOPIC_STT_TEXT = "jarvis/stt/text"
TOPIC_STATUS = "jarvis/status/stt"

# Defaults if not in config
SILENCE_THRESHOLD = 500
SILENCE_DURATION_SEC = 1.5
MAX_RECORD_SEC = 15


def record_until_silence(
    sample_rate: int,
    channels: int,
    silence_threshold: int = SILENCE_THRESHOLD,
    silence_duration_sec: float = SILENCE_DURATION_SEC,
    max_sec: float = MAX_RECORD_SEC,
) -> bytes:
    """Record raw PCM int16 audio until silence or max length."""
    block = 1024
    silence_blocks = int(silence_duration_sec * sample_rate / block)
    frames = []
    silent_count = 0
    started = False
    total_samples = 0
    max_samples = int(max_sec * sample_rate)

    def callback(indata, frame_count, time_info, status):
        nonlocal started, silent_count, total_samples
        if status:
            LOG.debug("sounddevice: %s", status)
        chunk = indata.copy()
        frames.append(chunk)
        total_samples += frame_count
        audio_int = (chunk[:, 0] * 32767).astype(np.int16)
        volume = int(np.abs(audio_int).mean())
        if volume > silence_threshold:
            started = True
            silent_count = 0
        elif started:
            silent_count += 1

    with sd.InputStream(
        samplerate=sample_rate,
        channels=channels,
        dtype="float32",
        blocksize=block,
        callback=callback,
    ):
        while True:
            time.sleep(0.1)
            if started and (silent_count >= silence_blocks or total_samples >= max_samples):
                break
            if len(frames) > 0 and not started and total_samples >= int(2 * sample_rate):
                break

    if not frames:
        return b""
    audio_float = np.concatenate(frames, axis=0)
    audio_int16 = (audio_float[:, 0] * 32767).astype(np.int16)
    return audio_int16.tobytes()


def run_stt_loop(config, mqtt_client: mqtt.Client) -> None:
    """Load Vosk model and process audio when jarvis/audio/start is received."""
    try:
        import vosk
    except ImportError:
        LOG.error("vosk not installed; pip install vosk")
        return

    model_path = config.audio.vosk_model_path
    if not Path(model_path).exists():
        LOG.warning("Vosk model not found at %s; download from https://alphacephei.com/vosk/models", model_path)
        # Publish a placeholder so orchestrator can still run (e.g. text input)
        def on_start(client, userdata, msg):
            payload = {"text": "", "error": "vosk_model_not_found", "timestamp": time.time()}
            client.publish(TOPIC_STT_TEXT, json.dumps(payload), qos=1)
        mqtt_client.subscribe(TOPIC_AUDIO_START, qos=1)
        mqtt_client.message_callback_add(TOPIC_AUDIO_START, on_start)
        while True:
            time.sleep(60)
        return

    model = vosk.Model(model_path)
    sample_rate = config.audio.sample_rate
    rec = vosk.KaldiRecognizer(model, sample_rate)

    def on_audio_start(client: mqtt.Client, userdata, msg) -> None:
        LOG.info("Audio start received, recording...")
        try:
            raw = record_until_silence(sample_rate, config.audio.channels)
            if len(raw) < sample_rate:
                LOG.info("Recording too short, ignoring")
                return
            rec.AcceptWaveform(raw)
            result = json.loads(rec.FinalResult())
            text = (result.get("text") or "").strip()
            payload = {"text": text, "timestamp": time.time(), "confidence": 1.0}
            client.publish(TOPIC_STT_TEXT, json.dumps(payload), qos=1)
            LOG.info("Published STT: %s", text or "(empty)")
        except Exception as e:
            LOG.exception("STT failed: %s", e)
            client.publish(TOPIC_STT_TEXT, json.dumps({"text": "", "error": str(e), "timestamp": time.time()}), qos=1)

    mqtt_client.subscribe(TOPIC_AUDIO_START, qos=1)
    mqtt_client.message_callback_add(TOPIC_AUDIO_START, on_audio_start)
    mqtt_client.publish(TOPIC_STATUS, json.dumps({"status": "ready"}), qos=0)
    LOG.info("STT service ready; waiting for %s", TOPIC_AUDIO_START)
    while True:
        time.sleep(60)


def main() -> None:
    config = load_config()
    configure_logging(config.log_level, "stt")
    client = mqtt.Client(client_id=f"{config.mqtt.client_id_prefix}-stt")
    if config.mqtt.username:
        client.username_pw_set(config.mqtt.username, config.mqtt.password)
    client.connect(config.mqtt.host, config.mqtt.port, 60)
    client.loop_start()
    try:
        run_stt_loop(config, client)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
