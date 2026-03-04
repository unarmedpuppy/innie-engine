# ADR-0029 — Containerized Heartbeat Scheduler

**Status:** Accepted
**Date:** 2026-03
**Amends:** ADR-0018 (Dockerized Embedding Service) — extends docker-compose.yml with a second service

## Context

The heartbeat pipeline runs on a schedule — typically every 30 minutes — to process session logs and route insights to the knowledge base. Before this ADR, the only supported scheduling method was a host system cron entry (`innie heartbeat enable`), which registers:

```
*/30 * * * * innie heartbeat run --agent <name>
```

This works, but has two friction points:

1. **Host dependencies**: The cron job requires the `innie` CLI to be installed at the path the cron daemon finds, with the right `PATH`, and a cron daemon running. On macOS this is launchd-backed cron; on Linux it's systemd-cron or cronie. Getting environment variables right (especially `INNIE_HOME` for non-default locations) requires non-obvious cron config.

2. **Inconsistency with Docker-first setup**: When a user runs `docker compose up -d` for the embedding service, they now have an innie-aware Docker environment. Scheduling the heartbeat on the host while running other innie services in Docker is an inconsistent mental model.

The embedding service (ADR-0018) established that `docker-compose.yml` is composable — "add more services later." The heartbeat scheduler is the natural next service to add.

## Decision

Add a `heartbeat` service to `docker-compose.yml` that runs `innie heartbeat run` on a configurable interval using a simple bash loop. No cron daemon, no scheduler library.

```yaml
heartbeat:
  build:
    context: .
    dockerfile: services/scheduler/Dockerfile
  volumes:
    - ${INNIE_HOME:-~/.innie}:/root/.innie
  environment:
    - INNIE_HOME=/root/.innie
    - INNIE_AGENT=${INNIE_AGENT:-innie}
    - INNIE_HEARTBEAT_INTERVAL=${INNIE_HEARTBEAT_INTERVAL:-1800}
    - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
    - OPENAI_API_KEY=${OPENAI_API_KEY:-}
  env_file:
    - path: .env.heartbeat
      required: false
  restart: unless-stopped
  depends_on:
    embeddings:
      condition: service_healthy
```

The container mounts `~/.innie` directly. The host CLI and container share the same files — no sync layer, no copy. Sessions written by the Stop hook are picked up by the container on its next interval.

### Entrypoint design

```bash
#!/bin/bash
set -euo pipefail

INTERVAL=${INNIE_HEARTBEAT_INTERVAL:-1800}

run_heartbeat() {
    innie heartbeat run && echo "Done." || echo "Failed (will retry)."
}

run_heartbeat   # immediate run on container start

while true; do
    sleep "$INTERVAL"
    run_heartbeat
done
```

Key choices:
- Runs immediately on container start (no waiting for the first interval)
- `|| echo` on failure — the loop never exits on heartbeat errors
- All config via env vars — no config file inside the container

### Inference backend constraint

The container cannot exec host binaries. This means subprocess-based inference backends (`claude -p "..."`, `opencode run`) are not viable inside the container. Only HTTP inference backends work:

- `provider = "anthropic"` → `ANTHROPIC_API_KEY` passed as env var
- `provider = "external"` → any OpenAI-compatible URL reachable from inside Docker
  - Host Ollama: `http://host.docker.internal:11434/v1` (Mac/Windows)
  - Host Ollama on Linux: `http://172.17.0.1:11434/v1` or `--add-host=host.docker.internal:host-gateway`

Users with subprocess-based inference should continue using `innie heartbeat enable` (host cron).

### Credentials: `.env.heartbeat`

Secrets are kept out of `docker-compose.yml` via an optional `.env.heartbeat` file (gitignored). A `.env.heartbeat.example` template is committed. `env_file.required: false` means the compose file works without the file existing — env vars can be set in the shell instead.

### `depends_on: embeddings: service_healthy`

The heartbeat scheduler waits for the embedding service to pass its healthcheck before starting its first run. This ensures the re-indexing step (Phase 3 calls the embedding service after routing) has a healthy endpoint available on first run.

## Options Considered

### Option A: Host cron only (status quo)
Keep `innie heartbeat enable` as the only scheduling mechanism. Simple, but the inconsistency with Docker-first setup remains, and cron environment issues are a real friction point.

### Option B: Scheduler library (APScheduler, rq-scheduler)
Add a Python scheduler that supports cron expressions, jitter, backoff. More flexible but adds a dependency and complexity for what is essentially a sleep loop. Over-engineered for the use case.

### Option C: Dedicated scheduler daemon (`innie scheduler start`)
A long-running Python process managed by a LaunchAgent (macOS) or systemd unit (Linux). More native to each platform but requires platform-specific plumbing. The Docker container is simpler and more portable.

### Option D: Shell loop in Docker (selected)
No dependencies beyond `bash` (already in the slim image). The entrypoint is 15 lines. `restart: unless-stopped` handles crashes. The loop is transparent — `docker compose logs heartbeat` shows every run with timestamps. Easy to understand and debug.

## Consequences

**Positive:**
- `docker compose up -d` starts both embedding and heartbeat — one command for the full Docker stack
- No host cron configuration required for Docker users
- The `~/.innie` volume mount means zero sync overhead — host and container share the same files
- `restart: unless-stopped` makes it resilient without any custom process supervision
- First run on container start means no lost 30-minute window after a container restart

**Negative:**
- Only works with HTTP inference backends — subprocess-based inference (local claude, opencode) is not viable inside Docker
- Requires Docker (same constraint as the embedding service)
- `env_file.required: false` syntax requires Docker Compose v2.24+

**Neutral:**
- `innie heartbeat enable` (host cron) still works and is unchanged — the Docker scheduler is an alternative, not a replacement
- The scheduling precision is "approximately every N seconds" — sleep drift can accumulate over time, but this is acceptable for a background indexing job
