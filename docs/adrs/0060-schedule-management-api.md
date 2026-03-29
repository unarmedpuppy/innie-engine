# ADR-0060: Schedule Management API

**Date:** 2026-03-29
**Status:** Accepted

---

## Context

Grove agents run scheduled jobs defined in `schedule.yaml`. These jobs — morning briefs, trading reports, heartbeats, digests — are the primary autonomous output of the fleet.

Until now, managing schedules required:
1. SSH to the agent machine (or SSH to the server for elm/birch)
2. Edit `~/.grove/agents/<name>/schedule.yaml` by hand
3. Restart the agent process to reload APScheduler

This friction meant schedule changes were rarely made and there was no visibility into job state from the homelab-ai dashboard.

The homelab-ai dashboard already proxied agent API calls for context, sessions, and skills. Schedule management was a natural extension of the same pattern.

---

## Decision

Add three schedule management endpoints to grove serve:

### `GET /v1/agent/schedule`

Returns all jobs from `schedule.yaml` plus their live APScheduler state (next run time, enabled status). Read-only, safe to call anytime.

### `PATCH /v1/schedule/{job_name}`

Updates a job's configuration. Allowed fields: `enabled`, `cron`, `interval_hours`, `prompt`, `model`, `permission_mode`.

Mechanics:
1. Read current `schedule.yaml`
2. Merge patch (only provided fields updated)
3. Write `schedule.yaml` back
4. Call `teardown_scheduler()` + `setup_scheduler(agent)` to reload APScheduler in-process

This is safe without a process restart because APScheduler is entirely in-process. No system cron, no external scheduler — just a Python object inside the uvicorn process.

### `POST /v1/schedule/{job_name}/trigger`

Fires a job immediately regardless of its schedule or enabled state. Useful for testing or manual one-off runs from the dashboard.

---

## Dashboard Integration

The homelab-ai dashboard-api (`gateway.py`) proxies all three endpoints through the standard agent endpoint resolution pattern. The dashboard `AgentScheduleTab` component:

- Lists all jobs with cadence, enabled state, next run time, prompt preview, and deliver-to channel
- Toggle button per job → calls `PATCH` with `{ enabled: !current }`; optimistic UI update
- Run Now button (enabled jobs only) → calls trigger endpoint
- Schedule tab is disabled for CLI agents (oak) and offline agents

---

## Alternatives Considered

### System cron / launchd jobs per agent

Rejected. Distributing schedule management across system cron on multiple machines makes the fleet harder to reason about. APScheduler in-process is simpler — one process owns its schedule, changes are atomic, no cron format inconsistencies across platforms.

### Full schedule CRUD (POST/DELETE job)

Deferred. The current use case is toggling and adjusting existing jobs, not creating new ones from the dashboard. Adding jobs requires careful schema validation and is better addressed when there's a concrete need. The `schedule.yaml` file remains the source of truth for job definition.

### Restart-required config reload

Rejected. Restarting the agent process interrupts any in-flight jobs and introduces unnecessary downtime. The `teardown_scheduler()` + `setup_scheduler(agent)` pattern cleanly reloads only the scheduler without touching the job queue, channels, or memory subsystem.

---

## Consequences

- Schedule changes are visible in the dashboard immediately
- Enabling/disabling a job takes one click without SSH
- `schedule.yaml` remains canonical — the API writes through to it, so state survives restarts
- The trigger endpoint enables testing scheduled jobs in development without waiting for the cron window
- Schedule tab is intentionally disabled for CLI agents since they have no persistent serve process

---

## Related

- ADR-0054: grove migration and rename
- ADR-0059: Phase 3 agent consolidation
- homelab-ai ADR: `docs/adrs/2026-03-29-schedule-management-dashboard.md`
- grove `docs/reference/api-server.md` — full endpoint reference
