# ADR-0032 — Agent-Harness to innie-engine Migration Strategy

**Status:** Accepted
**Date:** 2026-03
**Related:** ADR-0031 (dynamic fleet registration + A2A)

---

## Context

The homelab runs four agents across three machines. Until this migration, all agents use
`agent-harness` (Node.js) as their jobs API runtime. The goals of migrating to innie-engine:

- Unified toolchain: one codebase handles persistent memory, context injection, fleet coordination,
  and the jobs API
- Dynamic fleet registration (ADR-0031): agents self-register instead of requiring static YAML on
  every machine
- `agents://` A2A: agents can delegate work to each other asynchronously

Before migration the fleet topology was:

| Agent | Machine | How it runs | Port |
|-------|---------|-------------|------|
| Gilfoyle | Home server | Native systemd (agent-harness) | 8018 |
| Ralph | Home server | Docker container (`agent-harness`) | 8013 |
| Avery | Mac Mini | LaunchAgent (agent-harness) | 8013 |
| Colin | Mac Mini | LaunchAgent (agent-harness) | 8014 |

The fleet-gateway was a separate Docker container with a static `fleet.yaml`.

---

## The Ralph Problem

Ralph runs inside the `agent-harness` Docker container. The container name doubles as the Docker
network hostname — n8n workflows and other services POST to `http://agent-harness:8013/v1/jobs`.

This means Ralph **cannot** be migrated the same way as native agents (create a profile directory on
the host, start a systemd service). The profile directory would live on the host but the process
runs inside the container and sees a different filesystem.

Options considered:

**Option A — Move Ralph to native systemd (like Gilfoyle)**
Breaks the intentional sandbox. Ralph has full host access. Rejected.

**Option B — Migrate Ralph as part of the initial rollout**
Would require building a new Docker image before any other agent can migrate. Blocks the entire
rollout on a significant engineering task. Rejected as a dependency.

**Option C — Keep Ralph on agent-harness temporarily, migrate separately**
Ralph continues working unchanged. Other agents migrate independently. Ralph gets migrated when a
proper Docker image is built. Accepted.

**Option D — New Docker image with innie-engine baked in (`innie-ralph`)**
The correct long-term answer. Requires: Dockerfile (Node.js + Python + Claude CLI + innie),
Gitea Actions CI pipeline, Harbor push, home-server compose update. This is tracked as `innie-015`.

---

## Decision

**Phased migration, Ralph last.**

1. Gilfoyle migrates first (native systemd, straightforward)
2. innie-fleet replaces the fleet-gateway container (native systemd, Traefik re-route)
3. Avery + Colin migrate on the Mac Mini (LaunchAgent)
4. Ralph migrates last via a purpose-built Docker image (`innie-015`)

Each phase is independent and can be rolled back by stopping the new service and leaving the old one
running. Old agent-harness and new innie serve run in parallel until confidence is established.

---

## n8n Workflow Compatibility

innie serve exposes the same API surface as agent-harness:

| Endpoint | agent-harness | innie serve |
|----------|--------------|-------------|
| `POST /v1/jobs` | ✓ | ✓ |
| `GET /v1/jobs/{id}` | ✓ | ✓ |
| `GET /v1/jobs` | ✓ | ✓ |
| `POST /v1/jobs/{id}/cancel` | ✓ | ✓ |
| `GET /health` | ✓ | ✓ |
| `GET /v1/memory/context` | — | ✓ (new) |
| `GET /v1/jobs/{id}/events` | — | ✓ (new) |

**For Ralph's Docker migration:** if the new container keeps the Docker service name `agent-harness`
on the same Docker network, n8n workflows require zero changes. The hostname, port, and API shape
are all identical. This is the recommended path.

If the service is renamed to `innie-ralph` for clarity, every n8n HTTP Request node that references
`http://agent-harness:8013` must be updated. That audit is part of `innie-015`.

---

## fleet.yaml Seed During Transition

While agents are being migrated, the new innie-fleet gateway uses a static `fleet.yaml` seed to
ensure all agents appear in the registry from day one — before they start self-registering. This
prevents a gap where some agents aren't discoverable during the phased rollout.

Once all agents are running innie serve with `INNIE_FLEET_URL` set, self-registration takes over and
the fleet.yaml entries become redundant (but harmless to keep as fallback).

Ralph's fleet.yaml entry persists indefinitely until `innie-015` is complete, since the agent-harness
container does not self-register.

---

## Rollout Order and Task References

| Phase | Task | Blocking |
|-------|------|---------|
| 1 — Gilfoyle → innie serve (systemd) | `innie-009` | Phase 2 |
| 2a — innie-fleet systemd on server | `innie-010` | Phase 2b |
| 2b — Traefik re-route fleet-gateway domain | `infra-007` | Phase 2c |
| 2c — Stop old fleet-gateway container | `innie-011` | — |
| 3 — Mac Mini: avery + colin | `innie-012` | — |
| 4 — Stop old Gilfoyle agent-harness | `innie-013` | Phase 1 stable 24h |
| 5 — A2A end-to-end verification | `innie-014` | All phases |
| Ralph containerization | `innie-015` | Independent (P3) |

---

## Consequences

**Positive:**
- Each phase is independently reversible — stopping innie serve falls back to agent-harness
  immediately
- n8n workflows are unaffected during and after migration (same API, same hostname if Docker service
  name is preserved for Ralph)
- After full migration, agent-harness and fleet-gateway are eliminated — one fewer Node.js service,
  one fewer Docker container on the server
- Ralph's Docker sandbox is preserved through the migration

**Negative:**
- Ralph is on a different toolchain from the other agents until `innie-015` is complete. It cannot
  self-register, cannot use `agents://` as a reply_to target reliably (depends on fleet.yaml seed),
  and does not get innie memory features
- Parallel running period means two things answering on port 8018 (Gilfoyle) is impossible — the
  systemd service wins the port; old agent-harness must be moved to a different port or stopped
  before innie-gilfoyle starts
- `innie-015` is non-trivial: the Docker image needs Node.js + Python + Claude CLI + innie, which
  is a large image. Build times and image size need attention

**Neutral:**
- OpenClaw on the Mac Mini is unaffected — it uses the jobs API the same way it always has
- The static fleet.yaml seed means the fleet gateway shows all agents correctly even before
  self-registration is active
