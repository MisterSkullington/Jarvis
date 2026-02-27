# Jarvis – Local-First Voice Assistant

Jarvis is a modular, privacy-first voice assistant designed to run primarily on your Windows PC with optional offloading to a home server. It provides:

- Local speech-to-text (STT) and text-to-speech (TTS)
- Intent understanding via a local LLM (Ollama) and rules
- A central orchestrator that coordinates tools and integrations
- Smart-home control (Home Assistant / MQTT), web APIs, and calendar support
- Reminders, timers, and scheduled actions

This repository implements the architecture described in the **Local-First Jarvis Architecture Plan**.

## Repository Structure

- `infra/` – Docker & infra services (MQTT broker, Ollama, etc.)
- `jarvis_core/` – Shared configuration and logging utilities
- `services/` – Individual microservices:
  - `wakeword/` – Wake-word detection on your PC
  - `stt/` – Speech-to-text
  - `tts/` – Text-to-speech
  - `orchestrator/` – Central brain and routing
  - `nlu_agent/` – Intent parsing + LLM-backed agent
  - `scheduler/` – Reminders and scheduled tasks
  - `integrations/` – Smart home, web APIs, calendar, system control
- `desktop_client/` – Windows tray / desktop helper client
- `config/` – Example configuration files and profiles

## Quickstart

1. **Install Python dependencies**

   ```bash
   pip install -e .
   ```

2. **Copy and edit configuration**

   ```bash
   mkdir -p config
   copy config\\jarvis.example.yaml config\\dev.yaml
   ```

   Update `config/dev.yaml` with your MQTT broker address, Home Assistant token, and any API keys.

3. **Start infra (optional but recommended on a home server)**

   From the `infra/` directory:

   ```bash
   docker compose up -d
   ```

4. **Run core services**

   In separate terminals:

   ```bash
   python -m services.wakeword.main
   python -m services.stt.main
   python -m services.tts.main
   python -m services.nlu_agent.main
   python -m services.orchestrator.main
   python -m services.scheduler.main
   ```

5. **Test the flow**

   - Say the wake word (e.g. “Jarvis”) near your microphone.
   - Speak a command such as “Turn on the living room lights” or “Remind me to stand up in 10 minutes”.
   - Jarvis should transcribe, route the intent, call integrations, and reply via TTS.

## Configuration

See `config/jarvis.example.yaml` for all supported options. You can maintain multiple profiles such as `dev.yaml` and `prod.yaml` and select them via environment variables.

## Security & Privacy

- All core components (STT, TTS, LLM, MQTT, Home Assistant) are intended to run on your own hardware.
- Secrets (API keys, tokens) should be stored in environment variables or `.env` files that you **do not** commit to source control.

## Status

This is a work-in-progress implementation intended as a strong foundation for a personal Jarvis-style assistant. You can extend or swap any service (e.g., different STT/LLM engines) without changing the overall architecture.

