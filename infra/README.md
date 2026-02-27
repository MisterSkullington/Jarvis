# Jarvis Infrastructure

This directory contains Docker Compose definitions for running Jarvis backing services.

## Services

- **mosquitto** – MQTT broker (ports 1883 TCP, 9001 WebSockets). Always started.
- **ollama** – Local LLM server (port 11434). Started only with profile `llm`.

## Quick start

From the repository root:

```bash
docker compose -f infra/docker-compose.yml up -d
```

This starts only the Mosquitto broker. To also start Ollama (e.g. on a home server):

```bash
docker compose -f infra/docker-compose.yml --profile llm up -d
```

## Mosquitto

- Config: `infra/mosquitto/mosquitto.conf`
- Data and logs are stored in Docker volumes.
- Default setup uses `allow_anonymous true`. For production, set up a password file and set `allow_anonymous false` in `mosquitto.conf`.

## Ollama

- After starting the `ollama` service, pull a model inside the container:

  ```bash
  docker exec jarvis-ollama ollama run phi3
  ```

- Or use a smaller model: `ollama run tinyllama`
- Jarvis NLU agent expects Ollama at `http://localhost:11434` when running on the same host; when Ollama runs on a server, set `JARVIS_LLM_BASE_URL` or configure `llm.base_url` in `config/dev.yaml` to point to that host.

## Connecting from Windows PC

Point your Jarvis config at the server’s IP if the broker runs there:

- In `config/dev.yaml` set `mqtt.host` to the server hostname or IP.
- Ensure firewall allows TCP 1883 (and 9001 if using MQTT over WebSockets).
