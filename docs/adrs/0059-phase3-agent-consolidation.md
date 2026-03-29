# ADR-0059: Phase 3 Agent Consolidation — Retire Colin/Jobin, Keep Ralph

**Date:** 2026-03-29
**Status:** Accepted
**Supersedes:** ADR-0054 Phase 3 (revised decision on ralph)

---

## Context

The consolidation plan (ADR-0054, Phase 3) originally proposed retiring ralph and moving its jobs to Avery. After auditing ralph's actual runtime state and job topology, that assumption was wrong.

**Agents audited:**
- **Ralph** — Docker container on home server, port 8025. Two scheduled jobs: `daily_digest_poc` (weekdays 10am) and `task_loop` (every 4h). Both jobs require server-native access (Gitea SSH, server workspace, Docker network).
- **Colin** — Mac Mini agent. All plists already `.disabled`. No active traffic. Duplicate of Oak's role.
- **Jobin** — Mac Mini agent. Already inactive. No scheduled jobs, no active channels.
- **`innie` (default agent dir)** — Stale default from initial setup. Not a real agent.

**Ralph specifics:**
- Docker volumes: `ralph-innie-data`, `ralph-claude-config`, `ralph-ssh`, `ralph-workspace`
- Inference: Claude Max OAuth (stored in volume, not API key)
- Scheduled jobs use Gitea SSH access and server workspace — cannot run on Avery (Mac Mini, no server workspace)
- Was pointing at retired fleet-gateway (`http://fleet-gateway:8080`) — needed fix

**No systemd service for ralph** — the consolidation plan's mention of `innie-ralph.service` was speculative. Ralph was always Docker-only.

---

## Decision

### Ralph: Keep as Docker container

Ralph stays. It is the only agent with direct server workspace access and Gitea SSH keys. The jobs it runs cannot be delegated to Avery without introducing unnecessary A2A complexity. The value of having a server-native autonomous executor outweighs the complexity cost.

**Changes made:**
- `INNIE_FLEET_URL`: `http://fleet-gateway:8080` → `https://dashboard-api.server.unarmedpuppy.com`
- Added `ANTHROPIC_BASE_URL` and `ANTHROPIC_API_KEY` env vars to docker-compose.yml (per ADR-0055)

### Colin: Retired

- Disabled plists deleted from `~/Library/LaunchAgents/`
- Agent directory moved to `~/.innie/agents/.retired/colin/`

### Jobin: Retired

- Agent directory moved to `~/.innie/agents/.retired/jobin/`

### `innie` default agent dir: Archived

- Moved to `~/.innie/agents/.retired/innie/`

---

## Consequences

- Active agent roster: **oak, avery, gilfoyle, ralph, hal** — matches fleet registry
- `~/.innie/agents/` contains only active agents (no stale dirs)
- Ralph's docker-compose.yml now registers with dashboard-api correctly
- Ralph needs v0.14.7 upgrade and `ANTHROPIC_API_KEY` env var on next server deploy
- The CONSOLIDATION-PLAN.md "ralph and colin RETIRED" target state is revised: ralph stays

---

## Server Actions Required

Send to Gilfoyle:
1. Add `ANTHROPIC_API_KEY=sk-ant-api03-46fde211cd3942371bba4ac0f3508ef3` to ralph's `.env` at `/innie-data/.env` (inside container volume, or via docker exec)
2. Upgrade ralph to v0.14.7: `docker compose pull && docker compose up -d`
3. Confirm `GET /health` returns `"version": "0.14.7"`
