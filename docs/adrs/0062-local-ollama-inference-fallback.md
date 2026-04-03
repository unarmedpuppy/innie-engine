# ADR-0062 — Local Ollama as Inference Fallback

**Status:** Accepted
**Date:** 2026-04

---

## Context

All grove agents use `ANTHROPIC_BASE_URL` pointing to the homelab `llm-router` for inference.
When the llm-router (or the homelab-ai stack) goes down, all agents fail immediately —
even for simple conversational responses — because Claude Code cannot resolve the model `auto`
against an unreachable endpoint.

The failure is complete: no degraded mode, no alerting, just silent errors to users.

---

## Decision

Introduce a local ollama instance on each machine as an always-on fallback inference provider.
Grove's existing circuit breaker (`ANTHROPIC_FALLBACK_BASE_URL`) is extended with:

1. **Built-in Anthropic→Ollama proxy** — `grove serve` exposes `/v1/messages` that translates
   Anthropic Messages API calls (text, streaming, tools) to Ollama's OpenAI-compatible format.
   No external proxy process required.

2. **`GROVE_FALLBACK_MODEL`** — when on fallback, the circuit breaker overrides the model
   passed to Claude Code so a valid local model name is used instead of `auto`.

3. **Mattermost notification** — when the circuit breaker trips or recovers, a DM is sent
   to Josh via `GROVE_FALLBACK_NOTIFY_MM_CHANNEL` so the outage is visible.

4. **`g ollama setup`** — one command per agent that installs ollama, selects a qwen2.5
   model sized to <20% of available VRAM/RAM, pulls it, and writes all required env vars.
   Serve port and MM channel are auto-detected from the launchd plist and channels.yaml.

---

## Model Selection

The setup command picks the largest model from this catalog that fits within 20% of available memory:

| Model | Approx. GB |
|---|---|
| qwen2.5:0.5b | 0.4 |
| qwen2.5:1.5b | 1.0 |
| qwen2.5:3b   | 2.0 |
| qwen2.5:7b   | 4.7 |
| qwen2.5:14b  | 9.0 |

---

## Multi-Agent Machines (e.g. Mac Mini with Oak + Ash)

- `GROVE_OLLAMA_MODEL` and `GROVE_FALLBACK_MODEL` → shared `~/.grove/.env` (one ollama install)
- `ANTHROPIC_FALLBACK_BASE_URL` → per-agent `.env` (each agent's own grove serve port)
- `GROVE_FALLBACK_NOTIFY_MM_CHANNEL` → per-agent `.env` (each bot has its own Josh DM)

Run `g ollama setup` once per agent. The second run skips ollama install and model pull.

---

## Env Vars

| Variable | Scope | Purpose |
|---|---|---|
| `GROVE_OLLAMA_MODEL` | shared | Ollama model name for the proxy |
| `GROVE_OLLAMA_URL` | shared | Ollama base URL (default: http://localhost:11434) |
| `GROVE_FALLBACK_MODEL` | shared | Model passed to `--model` when on fallback |
| `ANTHROPIC_FALLBACK_BASE_URL` | per-agent | Grove serve URL (proxy endpoint) |
| `GROVE_FALLBACK_NOTIFY_MM_CHANNEL` | per-agent | Mattermost channel for alerts |
| `GROVE_FALLBACK_CHECK_INTERVAL` | optional | Probe interval in seconds (default: 30) |

---

## Fallback Flow

```
llm-router down
    → grove probe fails (30s interval)
    → circuit breaker trips
    → ANTHROPIC_BASE_URL set to ANTHROPIC_FALLBACK_BASE_URL (grove serve port)
    → GROVE_FALLBACK_MODEL overrides model name
    → Claude Code → POST /v1/messages → grove serve proxy → ollama
    → MM DM: "⚠️ oak switched to local ollama fallback (qwen2.5:3b)"

llm-router recovers
    → probe succeeds
    → circuit breaker resets
    → traffic routes back to llm-router
    → MM DM: "✅ oak restored to primary inference"
```

---

## Consequences

- Agents remain functional (degraded) during llm-router outages
- Fallback model capability is significantly reduced vs. primary (small qwen vs. 32b)
- Tool calling works best-effort — small models may not follow tool schemas reliably
- Outages are now visible via Mattermost instead of silent
- One-time setup per machine per agent; no ongoing maintenance

---

## Implementation

grove v0.16.0–v0.16.4. See `src/grove/serve/proxy.py` and `src/grove/commands/ollama.py`.

**v0.16.4 fix:** `_probe_url` now requires a 2xx response (not just non-5xx). Previously, Traefik returning
404 for a down backend container would fool the probe into thinking the primary was healthy. Now: `/health`
must return 2xx, with fallback probe to `/v1/models` if `/health` returns 404.
