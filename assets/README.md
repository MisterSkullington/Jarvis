# Assets

## Voice Reference for XTTS

Place a WAV file named `jarvis_voice_reference.wav` in this directory to enable
voice cloning with Coqui XTTS v2.

Requirements:
- 6–15 seconds of clear speech (no background noise)
- 16-bit, 22050 Hz or higher sample rate
- A calm, British-accented male voice works best for the JARVIS character

The TTS config field `tts.xtts_speaker_wav` points here by default.
If no reference file is found, XTTS falls back to its default voice.
