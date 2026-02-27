# AGENTS.md

## Cursor Cloud specific instructions

### Overview

J.A.R.V.I.S. is a modular Python voice assistant with a microservices architecture communicating over MQTT. See `README.md` for full architecture.

### Services

| Service | Command | Port/Protocol |
|---|---|---|
| MQTT Broker (Mosquitto) | `sudo docker compose -f infra/docker-compose.yml up -d` | TCP 1883, WS 9001 |
| NLU Agent (FastAPI) | `python3 -m services.nlu_agent.main` | HTTP :8001 |
| Orchestrator | `python3 -m services.orchestrator.main` | MQTT + HTTP :8002 (metrics) |
| Scheduler | `python3 -m services.scheduler.main` | MQTT + SQLite |
| Web HUD | `python3 -m services.web_ui.main` | HTTP :8080 + WebSocket |
| Proactive | `python3 -m services.proactive.main` | MQTT (morning briefings) |
| Monitor | `python3 -m services.monitor.main` | MQTT (health checks) |
| STT | `python3 -m services.stt.main` | MQTT (requires audio hardware) |
| TTS | `python3 -m services.tts.main` | MQTT (requires espeak on Linux) |
| Wakeword | `python3 -m services.wakeword.main` | MQTT (requires audio hardware) |

Use `python3 jarvis_launcher.py` to start core services, or `--all` for all services.

### Key caveats for Cloud agents

- **Docker must be running** before starting Mosquitto. Start dockerd first: `sudo dockerd &>/tmp/dockerd.log &` then wait a few seconds.
- **STT and Wakeword services require audio hardware** (microphone via `sounddevice`). These cannot run in headless Cloud VMs. To test the pipeline end-to-end without audio, publish JSON directly to the `jarvis/stt/text` MQTT topic.
- **TTS with pyttsx3** requires `espeak` (`sudo apt-get install -y espeak`). The `config/dev.yaml` should set `tts.engine: pyttsx3` since Piper/XTTS may not be available.
- **Ollama (LLM)** is optional. Set `llm.enabled: false` in `config/dev.yaml` to skip it. NLU falls back to rule-based parsing which covers all core intents.
- **config/dev.yaml** is the active config (copied from `config/jarvis.example.yaml`). It is gitignored; the example file is the checked-in reference.
- All services must be run from the **repository root** (`/workspace`), as they use `sys.path.insert` relative to `__file__`.
- **Port 8002 conflict**: If the orchestrator fails to start metrics, check for leftover processes on port 8002.

### Lint / Test / Build

- **Lint**: `ruff check .` and `black --check .` (pre-existing findings exist in the repo)
- **Type check**: `mypy jarvis_core/ services/` (configured with `ignore_missing_imports = true`)
- **No automated test suite** exists yet. Testing is done by running services and publishing MQTT messages.
- **Install deps**: `pip install -e ".[dev]"` from the repo root.

### Simulating end-to-end flow without audio

```python
import paho.mqtt.client as mqtt, json, time
# Subscribe to jarvis/tts/text for responses
# Publish to jarvis/stt/text with JSON: {"text": "hello jarvis"}
```

### Plugin/skill system

Skills are Python modules in `skills/`. Each skill registers intent handlers via a `register(registry)` function. See `skills/__init__.py` for the interface and `skills/system_info.py` for an example.
