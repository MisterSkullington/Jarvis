# J.A.R.V.I.S. – Local-First Voice Assistant

> *Just A Rather Very Intelligent System*

A modular, privacy-first voice assistant inspired by the MCU's J.A.R.V.I.S., designed to run on your own hardware. It provides a calm, British-accented AI personality with smart-home control, web search, proactive briefings, and a holographic-style web dashboard.

## Features

- **JARVIS Personality** — Witty, formal, addresses you as "sir" (configurable). Full system prompt and persona for LLM interactions.
- **Voice** — Coqui XTTS v2 (neural voice cloning), Piper (fast offline), or pyttsx3 (fallback). British accent via voice reference audio.
- **Web HUD** — Blue holographic dashboard with arc reactor animation, real-time transcripts, service status, activity log, and text input.
- **Smart Home** — Home Assistant integration: lights, climate/thermostat, locks, scenes, and media player.
- **Web Search** — DuckDuckGo integration for real-time information retrieval.
- **Proactive Briefings** — Scheduled morning briefings with weather, calendar, and reminders.
- **Conversation Memory** — Persistent SQLite-backed conversation history across sessions.
- **Plugin System** — Drop-in skill modules in `skills/` for custom capabilities.
- **NLU** — Rule-based intent parsing with LLM fallback (Ollama). Supports 15+ intents.
- **Reminders & Timers** — APScheduler with SQLite persistence.
- **Calendar** — Local ICS file parsing (Google Calendar OAuth optional).
- **System Monitoring** — Service health tracking with offline alerts.

## Architecture

```
User ──▶ Wakeword ──▶ STT ──▶ Orchestrator ──▶ NLU Agent ──▶ Integrations
                                    │                              │
                                    ▼                              ▼
                              TTS ◀── Scheduler          Home Assistant / Web APIs
                                    │
                                    ▼
                              Web HUD (browser)
```

All services communicate over **MQTT** (Eclipse Mosquitto). The orchestrator is the central brain.

## Repository Structure

- `jarvis_core/` — Shared config, logging, persona, MQTT helpers
- `services/` — Microservices:
  - `nlu_agent/` — Intent parsing + LLM agent (FastAPI on :8001)
  - `orchestrator/` — Central brain, intent dispatch (metrics on :8002)
  - `tts/` — Text-to-speech (XTTS / Piper / pyttsx3)
  - `stt/` — Speech-to-text (Vosk)
  - `wakeword/` — Wake word detection (openwakeword)
  - `scheduler/` — Reminders and timers (APScheduler + SQLite)
  - `web_ui/` — Web HUD dashboard (FastAPI + WebSocket on :8080)
  - `memory/` — Persistent conversation memory (SQLite)
  - `proactive/` — Scheduled briefings and calendar alerts
  - `monitor/` — Service health monitoring
  - `integrations/` — Home Assistant, weather, news, calendar, web search, system control
- `skills/` — Plugin skill modules (e.g. `system_info.py`)
- `desktop_client/` — Windows tray app (PySide6 / pystray)
- `config/` — YAML configuration profiles
- `infra/` — Docker Compose (Mosquitto MQTT, optional Ollama LLM)
- `assets/` — Voice reference audio for XTTS

## Quickstart

1. **Install Python dependencies**

   ```bash
   pip install -e ".[dev]"
   ```

2. **Copy and edit configuration**

   ```bash
   cp config/jarvis.example.yaml config/dev.yaml
   cp .env.example .env
   # Edit config/dev.yaml and .env with your settings
   ```

3. **Start infrastructure**

   ```bash
   docker compose -f infra/docker-compose.yml up -d
   ```

4. **Start all services**

   ```bash
   python jarvis_launcher.py          # core services (NLU, orchestrator, scheduler, web UI)
   python jarvis_launcher.py --all    # all services including TTS, STT, proactive, monitor
   ```

   Or start individually:
   ```bash
   python -m services.nlu_agent.main
   python -m services.orchestrator.main
   python -m services.scheduler.main
   python -m services.web_ui.main
   ```

5. **Open the HUD**

   Navigate to `http://localhost:8080` in your browser.

6. **Test the flow**

   Type a command in the HUD, or publish via MQTT:
   ```bash
   mosquitto_pub -t jarvis/stt/text -m '{"text": "hello jarvis"}'
   ```

## Configuration

See `config/jarvis.example.yaml` for all options. Key sections:

- `user` — Your name, preferred address ("sir", "ma'am", etc.), location
- `llm` — Ollama model and endpoint
- `tts` — Engine selection (xtts, piper, pyttsx3) and voice settings
- `mqtt` — Broker connection
- `home_assistant` — HA base URL and token
- `proactive` — Morning briefing schedule, calendar alert timing
- `memory` — Conversation database path
- `web_ui` — HUD host and port

Environment variables: see `.env.example` for API keys and overrides.

## Creating Skills

Drop a Python file in `skills/`:

```python
SKILL_NAME = "my_skill"

def handle_my_intent(text, entities, config, mqtt_client, user):
    return f"Hello from my skill, {user.preferred_address}."

def register(registry):
    registry["my_intent"] = handle_my_intent
```

Add a matching intent pattern in `services/nlu_agent/main.py` RULES list.

## Security & Privacy

- All components run on your own hardware — no cloud dependencies.
- Secrets belong in `.env` (gitignored) or environment variables.
- MQTT broker defaults to `allow_anonymous true`; configure auth for production.
