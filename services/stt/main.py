"""
STT service: subscribes to jarvis/audio/start, records audio with silence detection,
transcribes with Vosk (default) or faster-whisper, publishes JSON to jarvis/stt/text.

Config: audio.engine = "vosk" | "faster_whisper"
        audio.silence_threshold = 500  (amplitude threshold for VAD)
"""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import paho.mqtt.client as mqtt
import sounddevice as sd

from jarvis_core import load_config, configure_logging, make_mqtt_client, subscribe_and_track

LOG = logging.getLogger(__name__)

TOPIC_AUDIO_START = "jarvis/audio/start"
TOPIC_STT_TEXT = "jarvis/stt/text"
TOPIC_STATUS = "jarvis/status/stt"

# Defaults (overridable via config.audio.silence_threshold)
_DEFAULT_SILENCE_THRESHOLD = 500
SILENCE_DURATION_SEC = 1.5
MAX_RECORD_SEC = 15

# Guard to prevent overlapping recordings
_recording_lock = threading.Lock()


def record_until_silence(
    sample_rate: int,
    channels: int,
    silence_threshold: int = _DEFAULT_SILENCE_THRESHOLD,
    silence_duration_sec: float = SILENCE_DURATION_SEC,
    max_sec: float = MAX_RECORD_SEC,
    device: str | None = None,
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
        device=device,
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


# ---------------------------------------------------------------------------
# Vosk engine
# ---------------------------------------------------------------------------

def run_vosk_loop(config, mqtt_client: mqtt.Client) -> None:
    """Load Vosk model and process audio on jarvis/audio/start."""
    try:
        import vosk
    except ImportError:
        LOG.error("vosk not installed; pip install vosk")
        return

    model_path = config.audio.vosk_model_path
    if not Path(model_path).exists():
        LOG.warning("Vosk model not found at %s; download from https://alphacephei.com/vosk/models", model_path)

        def on_start_stub(client, userdata, msg):
            payload = {"text": "", "error": "vosk_model_not_found", "timestamp": time.time()}
            client.publish(TOPIC_STT_TEXT, json.dumps(payload), qos=1)

        subscribe_and_track(mqtt_client, TOPIC_AUDIO_START, qos=1)
        mqtt_client.message_callback_add(TOPIC_AUDIO_START, on_start_stub)
        while True:
            time.sleep(60)
        return

    model = vosk.Model(model_path)
    sample_rate = config.audio.sample_rate
    silence_threshold = getattr(config.audio, "silence_threshold", _DEFAULT_SILENCE_THRESHOLD)
    input_device = getattr(config.audio, "input_device", None)
    rec = vosk.KaldiRecognizer(model, sample_rate)

    def _do_record_vosk(client: mqtt.Client) -> None:
        """Run recording + transcription in a worker thread."""
        if not _recording_lock.acquire(blocking=False):
            LOG.debug("Already recording, skipping overlapping request")
            return
        try:
            LOG.info("Audio start received (vosk), recording...")
            raw = record_until_silence(
                sample_rate, config.audio.channels,
                silence_threshold=silence_threshold,
                device=input_device,
            )
            if len(raw) < sample_rate:
                LOG.info("Recording too short, ignoring")
                return
            rec.AcceptWaveform(raw)
            result = json.loads(rec.FinalResult())
            text = (result.get("text") or "").strip()
            payload = {"text": text, "timestamp": time.time(), "confidence": 1.0}
            client.publish(TOPIC_STT_TEXT, json.dumps(payload), qos=1)
            LOG.info("Published STT (vosk): %s", text or "(empty)")
        except Exception as e:
            LOG.exception("Vosk STT failed: %s", e)
            client.publish(TOPIC_STT_TEXT, json.dumps({"text": "", "error": str(e), "timestamp": time.time()}), qos=1)
        finally:
            _recording_lock.release()

    def on_audio_start(client: mqtt.Client, userdata, msg) -> None:
        # Run in separate thread so MQTT callbacks are not blocked
        threading.Thread(target=_do_record_vosk, args=(client,), daemon=True).start()

    subscribe_and_track(mqtt_client, TOPIC_AUDIO_START, qos=1)
    mqtt_client.message_callback_add(TOPIC_AUDIO_START, on_audio_start)
    mqtt_client.publish(TOPIC_STATUS, json.dumps({"status": "ready", "engine": "vosk"}), qos=0)
    LOG.info("STT (vosk) ready; waiting for %s", TOPIC_AUDIO_START)
    while True:
        time.sleep(60)


# ---------------------------------------------------------------------------
# Faster-Whisper engine
# ---------------------------------------------------------------------------

def run_faster_whisper_loop(config, mqtt_client: mqtt.Client) -> None:
    """Load faster-whisper model and process audio on jarvis/audio/start."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        LOG.error("faster-whisper not installed; pip install 'jarvis-assistant[stt-fast]'")
        LOG.info("Falling back to Vosk...")
        run_vosk_loop(config, mqtt_client)
        return

    model_size = config.audio.whisper_model  # tiny | base | small | medium | large
    LOG.info("Loading faster-whisper model: %s ...", model_size)
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute = "float16" if device == "cuda" else "int8"
    except ImportError:
        device, compute = "cpu", "int8"

    model = WhisperModel(model_size, device=device, compute_type=compute)
    sample_rate = config.audio.sample_rate
    silence_threshold = getattr(config.audio, "silence_threshold", _DEFAULT_SILENCE_THRESHOLD)
    input_device = getattr(config.audio, "input_device", None)

    def _do_record_whisper(client: mqtt.Client) -> None:
        """Run recording + transcription in a worker thread."""
        if not _recording_lock.acquire(blocking=False):
            LOG.debug("Already recording, skipping overlapping request")
            return
        try:
            LOG.info("Audio start received (faster-whisper), recording...")
            raw = record_until_silence(
                sample_rate, config.audio.channels,
                silence_threshold=silence_threshold,
                device=input_device,
            )
            if len(raw) < sample_rate:
                LOG.info("Recording too short, ignoring")
                return
            audio_f32 = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            segments, info = model.transcribe(audio_f32, beam_size=5, language="en")
            text = " ".join(seg.text.strip() for seg in segments).strip()
            confidence = round(getattr(info, "language_probability", 1.0), 3)
            payload = {"text": text, "timestamp": time.time(), "confidence": confidence}
            client.publish(TOPIC_STT_TEXT, json.dumps(payload), qos=1)
            LOG.info("Published STT (faster-whisper): %s", text or "(empty)")
        except Exception as e:
            LOG.exception("faster-whisper STT failed: %s", e)
            client.publish(TOPIC_STT_TEXT, json.dumps({"text": "", "error": str(e), "timestamp": time.time()}), qos=1)
        finally:
            _recording_lock.release()

    def on_audio_start(client: mqtt.Client, userdata, msg) -> None:
        # Run in separate thread so MQTT callbacks are not blocked
        threading.Thread(target=_do_record_whisper, args=(client,), daemon=True).start()

    subscribe_and_track(mqtt_client, TOPIC_AUDIO_START, qos=1)
    mqtt_client.message_callback_add(TOPIC_AUDIO_START, on_audio_start)
    mqtt_client.publish(
        TOPIC_STATUS,
        json.dumps({"status": "ready", "engine": "faster_whisper", "model": model_size}),
        qos=0,
    )
    LOG.info("STT (faster-whisper/%s) ready; waiting for %s", model_size, TOPIC_AUDIO_START)
    while True:
        time.sleep(60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_stt_loop(config, mqtt_client: mqtt.Client) -> None:
    """Dispatch to the configured STT engine."""
    engine = getattr(config.audio, "engine", "vosk").lower()
    if engine == "faster_whisper":
        run_faster_whisper_loop(config, mqtt_client)
    else:
        run_vosk_loop(config, mqtt_client)


def main() -> None:
    config = load_config()
    configure_logging(config.log_level, "stt")
    client = make_mqtt_client(config, "stt")
    client.connect(config.mqtt.host, config.mqtt.port, 60)
    client.loop_start()
    try:
        run_stt_loop(config, client)
    except KeyboardInterrupt:
        pass
    finally:
        LOG.info("STT shutting down...")
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
