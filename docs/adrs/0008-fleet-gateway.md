# ADR-0008 — Fleet Gateway for Multi-Machine Coordination

**Status:** Accepted
**Date:** 2026-02
**Context:** Coordinating multiple innie agents across machines

---

## Context

The original motivation for innie came from a homelab with multiple machines running AI agents. The need: agents on different machines should be able to discover each other, submit jobs to each other, and report health.

Prior art: the `agent-harness` project (which innie merges) had a jobs API (`POST /v1/jobs`) and a separate `fleet-gateway` service that aggregated multiple agents.

Options for multi-machine coordination:

1. **No fleet support** — users SSH between machines manually
2. **Shared database** — all agents read/write a central PostgreSQL
3. **Message queue** — Redis/RabbitMQ as communication backbone
4. **HTTP APIs** — each agent exposes HTTP; a gateway aggregates
5. **gRPC service mesh** — strongly typed but heavy

---

## Decision

**Lightweight HTTP gateway** with YAML-configured agent registry and background health polling.

- Each agent runs `innie serve` (FastAPI, default port 8013)
- A fleet gateway (`innie fleet start`) maintains a registry of agents
- Health monitor polls SERVER agents every N seconds (configurable)
- 3-strike degradation: 1-2 failures → DEGRADED, 3+ → OFFLINE
- Gateway proxies job creation and memory reads across agents
- CLI agents (local) are registered but not health-polled

---

## Rationale

**Against shared database:** Creates a hard dependency on a central server. If the database is down, all agents are down. Doesn't match the "each machine is independent" model.

**Against message queue:** Significant infrastructure overhead. Adds Redis/RabbitMQ as a dependency. Message queues are great for guaranteed delivery at scale, but innie targets personal/homelab use where simplicity matters more than guaranteed delivery.

**Against gRPC:** Heavy. Requires protobuf schema for every message type. HTTP is universal — any language, any tool can speak to it.

**For lightweight HTTP gateway:**
- Matches the existing agent-harness pattern (migration path is clear)
- Each agent is independently deployable — the fleet gateway is optional
- YAML config is human-readable and version-controllable
- 3-strike degradation avoids flapping — temporary network blips don't immediately mark agents offline
- The gateway itself is stateless (health state is in-memory) — restarting it is safe

**Why 3-strike threshold?** One failure might be a network blip. Two is suspicious. Three is a real problem. The threshold is configurable but 3 is the right default for a local network.

---

## Consequences

**Positive:**
- Fleet gateway is completely optional — single-machine users ignore it entirely
- Each agent is independently functional without the gateway
- Health status provides real-time visibility into fleet state
- Proxied job submission means callers don't need to know which machine a job runs on

**Negative:**
- In-memory health state means a gateway restart resets all statuses to UNKNOWN
- No guaranteed delivery — if a job submission fails, the caller must retry
- The gateway is a single point of failure for fleet-wide operations

**Neutral:**
- The fleet config YAML must be manually maintained when agents are added/removed
- Future: agent self-registration (agents POST to the gateway at startup) would eliminate manual config
