# ADR-0057: Retire fleet-gateway — dashboard-api as Sole Fleet Coordinator

**Date:** 2026-03-29
**Status:** Accepted

## Context

Two parallel fleet coordinators have been running independently without awareness of each other:

**fleet-gateway** (home-server repo, standalone Docker container):
- Runs `innie fleet start` (innie-engine image)
- Loads `fleet.yaml` for agent seed config
- Health-monitors all agents every 30s
- Exposes `/api/agents`, `/api/jobs`
- Used only by Oak (me) for A2A job submission

**dashboard-api** (homelab-ai repo):
- Loads its own `config.yaml` for agent registry (was stale since pre-grove)
- Health-monitors the same agents every 30s — independently
- Exposes `/api/agents`, `/api/jobs`, `/traces` (unique: trace ingestion, session history)
- Used by the homelab-ai dashboard frontend
- All grove agents already register with it via `INNIE_FLEET_URL`
- Already receives trace events from Claude Code hooks

These systems never communicated. Both maintained separate health state. Both ran background polling loops against the same endpoints. The dashboard never used fleet-gateway; fleet-gateway had no trace capability. Running both was redundant by construction.

Additionally, `fleet-gateway` depended on bind-mounts to override its own Docker image at runtime:
```yaml
volumes:
  - ./gateway.py:/usr/.../innie/fleet/gateway.py:ro
  - ./models.py:/usr/.../innie/fleet/models.py:ro
```

This caused fleet code to drift from the innie-engine source of truth. A model name bug (`claude-sonnet-4-20250514`) required fixing in two separate files across two repos on the same day.

## Decision

**Retire fleet-gateway. Make dashboard-api the sole fleet coordinator.**

dashboard-api is the correct home for fleet coordination because:
- It already receives agent registrations and trace events (agents were always pointing to it)
- It has trace ingestion (SQLite) — a unique capability fleet-gateway never had
- It's part of homelab-ai's deployment pipeline (proper image build + deploy)
- The dashboard frontend already polls it — no routing change needed
- `INNIE_FLEET_URL` in grove agents already points to dashboard-api

### Changes

**home-server/apps/fleet-gateway/** — deleted entirely:
- `docker-compose.yml` removed (container no longer runs)
- `fleet.yaml` removed (config moves to dashboard-api/config.yaml)
- `gateway.py`, `models.py` — already deleted in cleanup (bind-mount overrides)

**dashboard-api/config.yaml** — updated to 5-agent fleet:
- Remove: colin (retiring), jobin (never ran)
- Fix ralph endpoint: `http://ralph:8013` → `http://host.docker.internal:8025`
- Fix oak `expected_online: false` → `true`
- Add hal with correct Tailscale endpoint

**Plist env vars** — updated on Mac Mini:
- `INNIE_FLEET_URL`: `fleet-gateway.server.unarmedpuppy.com` → `dashboard-api.server.unarmedpuppy.com`

**A2A job submission** — URL updated:
- `https://fleet-gateway.server.unarmedpuppy.com/api/jobs` → `https://dashboard-api.server.unarmedpuppy.com/api/jobs`

### innie fleet module (follow-up)

The `src/innie/fleet/` module (~1500 lines) exists solely to power the fleet-gateway container. With the container retired, this module has no users. It will be removed in a follow-up PR (ADR-0058) after Phase 1 is confirmed stable for one week.

## Consequences

**Positive:**
- One fleet coordinator instead of two — no duplicate health polling, no state drift
- Trace ingestion and agent health in one service (was split across two)
- Bind-mount override pattern eliminated — fleet code changes go through normal image pipeline
- `fleet-gateway.server.unarmedpuppy.com` domain retired — one fewer Traefik route
- ~50 lines of config removed from home-server repo
- A2A job submission and dashboard data come from the same service

**Neutral:**
- `fleet-gateway.server.unarmedpuppy.com` will 404 after retirement — nothing external depends on it
- Existing job IDs submitted to fleet-gateway are not migrated (job history doesn't persist across restarts anyway)

**Negative / risks:**
- dashboard-api config.yaml and fleet.yaml were separate files — now only config.yaml exists. Future agent changes require updating homelab-ai repo instead of home-server repo. Mitigation: documented in GROVE.md.

## Migration Sequence

1. ✅ Clean fleet.yaml (remove colin, fix ralph endpoint, remove bind-mounts) — done 2026-03-29 v1.0.1826
2. ⏳ Update dashboard-api/config.yaml — in progress
3. ⏳ Update `INNIE_FLEET_URL` in plists → dashboard-api URL
4. ⏳ Delete `apps/fleet-gateway/` from home-server
5. ⏳ Remove `innie fleet` module from innie-engine (ADR-0058)

## Related

- ADR-0054: Grove migration (fleet-gateway retirement was always part of Phase 4b)
- ADR-0058: Remove innie fleet module (follow-up cleanup)
- `~/workspace/upgrade-agent/CONSOLIDATION-PLAN.md` — full multi-phase plan
