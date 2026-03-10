"""
TTS service: subscribes to jarvis/tts/text, converts to speech with Piper (primary) or pyttsx3 (fallback), and plays audio.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import paho.mqtt.client as mqtt
import sounddevice as sd

from jarvis_core import load_config, configure_logging, make_mqtt_client, subscribe_and_track

LOG = logging.getLogger(__name__)

TOPIC_TTS_INPUT = "jarvis/tts/text"
TOPIC_STATUS = "jarvis/status/tts"


def _play_raw_audio(raw_pcm: bytes, sample_rate: int = 22050, device: str | None = None) -> None:
    """Play raw int16 PCM audio via sounddevice (supports device selection)."""
    audio_f32 = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0
    sd.play(audio_f32, samplerate=sample_rate, device=device, blocking=True)


def speak_piper(text: str, config) -> bool:
    """Use Piper CLI if available. Returns True if successful."""
    exe = getattr(config.tts, "piper_executable", "piper") or "piper"
    model = getattr(config.tts, "piper_model", "en_US-libritts-high") or "en_US-libritts-high"
    output_device = getattr(config.tts, "output_device", None)
    try:
        proc = subprocess.run(
            [exe, "--model", model, "--output_raw"],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        if proc.returncode != 0 or not proc.stdout:
            return False
        # Play raw 22050 Hz 16-bit mono via sounddevice (supports device selection)
        _play_raw_audio(proc.stdout, sample_rate=22050, device=output_device)
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        LOG.debug("Piper TTS failed: %s", e)
        return False


def speak_pyttsx3(text: str, config) -> None:
    """Use pyttsx3 for offline TTS (works on Windows without extra binaries).

    Note: pyttsx3 uses the system default output device and does not support
    device selection natively.
    """
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty("rate", getattr(config.tts, "voice_rate", 180))
    engine.setProperty("volume", getattr(config.tts, "voice_volume", 1.0))
    engine.say(text)
    engine.runAndWait()


def on_tts_message(client: mqtt.Client, userdata, msg) -> None:
    config = userdata["config"]
    try:
        payload = msg.payload.decode("utf-8")
        # Allow JSON wrapper: {"text": "Hello"} or plain string
        try:
            data = json.loads(payload)
            text = data.get("text", payload)
        except json.JSONDecodeError:
            text = payload
        if not (text and text.strip()):
            return
        text = text.strip()
        LOG.info("TTS: %s", text[:80] + "..." if len(text) > 80 else text)
        if config.tts.engine == "piper" and speak_piper(text, config):
            pass
        else:
            speak_pyttsx3(text, config)
    except Exception as e:
        LOG.exception("TTS failed: %s", e)


def main() -> None:
    config = load_config()
    configure_logging(config.log_level, "tts")
    client = make_mqtt_client(config, "tts")
    # Merge our config into the userdata created by make_mqtt_client
    client._userdata["config"] = config  # noqa: SLF001
    client.connect(config.mqtt.host, config.mqtt.port, 60)
    subscribe_and_track(client, TOPIC_TTS_INPUT, qos=1)
    client.message_callback_add(TOPIC_TTS_INPUT, on_tts_message)
    client.publish(TOPIC_STATUS, json.dumps({"status": "ready"}), qos=0)
    LOG.info("TTS service ready; subscribed to %s (engine=%s)", TOPIC_TTS_INPUT, config.tts.engine)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        pass
    finally:
        LOG.info("TTS shutting down...")
        client.disconnect()


if __name__ == "__main__":
    main()
