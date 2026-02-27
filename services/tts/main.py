"""
TTS service: subscribes to jarvis/tts/text, converts to speech.

Engine priority:
  1. Coqui XTTS v2 — high-quality neural voice with optional voice cloning
  2. Piper — fast offline TTS via CLI
  3. pyttsx3 — fallback offline TTS (espeak on Linux, SAPI5 on Windows)
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import paho.mqtt.client as mqtt

from jarvis_core import load_config, configure_logging

LOG = logging.getLogger(__name__)

TOPIC_TTS_INPUT = "jarvis/tts/text"
TOPIC_TTS_STOP = "jarvis/tts/stop"
TOPIC_STATUS = "jarvis/status/tts"
TOPIC_UI_STATE = "jarvis/ui/state"

_xtts_model = None
_xtts_lock = threading.Lock()
_speaking = threading.Event()


def _load_xtts(config):
    """Lazy-load Coqui XTTS model (heavy, done once)."""
    global _xtts_model
    with _xtts_lock:
        if _xtts_model is not None:
            return _xtts_model
        try:
            from TTS.api import TTS
            model_name = getattr(config.tts, "xtts_model", "tts_models/multilingual/multi-dataset/xtts_v2")
            LOG.info("Loading XTTS model: %s (this may take a moment...)", model_name)
            _xtts_model = TTS(model_name)
            LOG.info("XTTS model loaded successfully")
            return _xtts_model
        except ImportError:
            LOG.warning("Coqui TTS package not installed (pip install TTS). Falling back.")
            return None
        except Exception as e:
            LOG.warning("Failed to load XTTS model: %s. Falling back.", e)
            return None


def speak_xtts(text: str, config) -> bool:
    """Generate speech with Coqui XTTS and play it. Returns True on success."""
    tts = _load_xtts(config)
    if tts is None:
        return False
    speaker_wav = getattr(config.tts, "xtts_speaker_wav", "")
    language = getattr(config.tts, "xtts_language", "en")
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            out_path = f.name
        if speaker_wav and Path(speaker_wav).exists():
            tts.tts_to_file(
                text=text,
                file_path=out_path,
                speaker_wav=speaker_wav,
                language=language,
            )
        else:
            tts.tts_to_file(text=text, file_path=out_path)
        _play_audio_file(out_path)
        return True
    except Exception as e:
        LOG.warning("XTTS synthesis failed: %s", e)
        return False
    finally:
        try:
            Path(out_path).unlink(missing_ok=True)
        except Exception:
            pass


def speak_piper(text: str, config) -> bool:
    """Use Piper CLI if available. Returns True if successful."""
    exe = getattr(config.tts, "piper_executable", "piper") or "piper"
    model = getattr(config.tts, "piper_model", "en_US-libritts-high") or "en_US-libritts-high"
    try:
        proc = subprocess.run(
            [exe, "--model", model, "--output_raw"],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        if proc.returncode != 0 or not proc.stdout:
            return False
        with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as f:
            f.write(proc.stdout)
            path = f.name
        try:
            subprocess.run(
                ["ffplay", "-nodisp", "-autoexit", "-f", "s16le", "-ar", "22050", "-ac", "1", path],
                capture_output=True, timeout=60,
            )
        except FileNotFoundError:
            try:
                subprocess.run(
                    ["aplay", "-f", "S16_LE", "-r", "22050", "-c", "1", path],
                    capture_output=True, timeout=60,
                )
            except FileNotFoundError:
                LOG.warning("No ffplay/aplay found; Piper audio generated but not played")
        finally:
            Path(path).unlink(missing_ok=True)
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        LOG.debug("Piper TTS failed: %s", e)
        return False


def speak_pyttsx3(text: str, config) -> None:
    """Use pyttsx3 for offline TTS (works on Windows without extra binaries)."""
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty("rate", getattr(config.tts, "voice_rate", 180))
    engine.setProperty("volume", getattr(config.tts, "voice_volume", 1.0))
    engine.say(text)
    engine.runAndWait()


def _play_audio_file(path: str) -> None:
    """Play a WAV file using available system tools."""
    players = [
        ["ffplay", "-nodisp", "-autoexit", path],
        ["aplay", path],
        ["paplay", path],
    ]
    for cmd in players:
        try:
            subprocess.run(cmd, capture_output=True, timeout=60)
            return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    LOG.warning("No audio player found to play %s", path)


def on_tts_message(client: mqtt.Client, userdata, msg) -> None:
    config = userdata["config"]
    try:
        payload = msg.payload.decode("utf-8")
        try:
            data = json.loads(payload)
            text = data.get("text", payload)
        except json.JSONDecodeError:
            text = payload
        if not (text and text.strip()):
            return
        text = text.strip()
        LOG.info("TTS: %s", text[:80] + "..." if len(text) > 80 else text)

        try:
            client.publish(
                TOPIC_UI_STATE,
                json.dumps({"state": "speaking", "text": text[:200]}),
                qos=0,
            )
        except Exception:
            pass

        _speaking.set()
        engine = getattr(config.tts, "engine", "pyttsx3")

        spoken = False
        if engine == "xtts":
            spoken = speak_xtts(text, config)
        if not spoken and engine in ("piper", "xtts"):
            spoken = speak_piper(text, config)
        if not spoken:
            speak_pyttsx3(text, config)

        _speaking.clear()

        try:
            client.publish(
                TOPIC_UI_STATE,
                json.dumps({"state": "idle"}),
                qos=0,
            )
        except Exception:
            pass
    except Exception as e:
        _speaking.clear()
        LOG.exception("TTS failed: %s", e)


def on_tts_stop(client: mqtt.Client, userdata, msg) -> None:
    """Handle stop/interrupt requests."""
    LOG.info("TTS stop requested")
    _speaking.clear()


def main() -> None:
    config = load_config()
    configure_logging(config.log_level, "tts")
    client = mqtt.Client(client_id=f"{config.mqtt.client_id_prefix}-tts")
    if config.mqtt.username:
        client.username_pw_set(config.mqtt.username, config.mqtt.password)
    client.user_data_set({"config": config})
    client.connect(config.mqtt.host, config.mqtt.port, 60)
    client.subscribe(TOPIC_TTS_INPUT, qos=1)
    client.subscribe(TOPIC_TTS_STOP, qos=1)
    client.message_callback_add(TOPIC_TTS_INPUT, on_tts_message)
    client.message_callback_add(TOPIC_TTS_STOP, on_tts_stop)
    client.publish(TOPIC_STATUS, json.dumps({"status": "ready"}), qos=0)
    engine = getattr(config.tts, "engine", "pyttsx3")
    LOG.info("J.A.R.V.I.S. TTS service ready (engine=%s)", engine)
    client.loop_forever()


if __name__ == "__main__":
    main()
