# ADR-0058: Remove innie fleet Module from grove

**Date:** 2026-03-29
**Status:** Accepted (pending Phase 1 stability confirmation)

## Context

`src/innie/fleet/` (~1500 lines) implements the fleet-gateway FastAPI server:
- `gateway.py` — agent registry, health monitoring loop, job proxying, trace aggregation
- `models.py` — Pydantic models (Agent, AgentHealth, FleetStats, JobCreateRequest)
- `health.py` — HealthMonitor background task
- `config.py` — YAML config loader

This module exists solely to power the fleet-gateway Docker container. With fleet-gateway retired (ADR-0057), this module has no callers. The `innie fleet start` CLI subcommand becomes a dead command.

The `innie.fleet.models` types (Agent, AgentHealth, FleetStats) are only used internally by `gateway.py` — no other innie-engine modules import them. No external repos import from `innie.fleet`.

## Decision

Remove `src/innie/fleet/` and the `fleet` CLI subcommand from grove.

**Removed:**
- `src/innie/fleet/` directory (gateway.py, models.py, health.py, config.py, __init__.py)
- `src/innie/commands/fleet.py` CLI command module
- Fleet subcommand registration in `src/innie/cli.py`

**Kept:**
- `INNIE_FLEET_URL` env var consumption in `serve/app.py` — agents still register with dashboard-api using this var. The client-side registration code (10 lines in app.py) is not fleet module code; it's serve startup code.

## Timing

Execute after ADR-0057 Phase 1 is stable for one week:
- dashboard-api confirmed as sole fleet coordinator
- Agent registrations landing in dashboard-api
- A2A jobs routing correctly through dashboard-api
- No regressions in dashboard fleet view

## Consequences

**Positive:**
- ~1500 lines removed from grove codebase
- `g fleet start` command gone — no dead commands in CLI
- innie-engine Docker image gets smaller (though fleet module has no large dependencies)
- grove's scope becomes cleaner: agent framework only, not fleet coordination infrastructure

**Neutral:**
- `innie fleet` / `g fleet` command removed — document in release notes

**Negative / risks:**
- Any undiscovered callers of `innie fleet start` would break. Audit confirmed zero external callers. fleet-gateway container is the only known consumer.

## Related

- ADR-0057: Fleet-gateway retirement (prerequisite)
- ADR-0054: Grove migration (Phase 4a/4b — package rename happens alongside or after this)
