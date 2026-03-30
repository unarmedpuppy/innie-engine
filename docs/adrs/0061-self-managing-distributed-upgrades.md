# ADR-0061: Self-Managing Distributed Upgrades

**Date:** 2026-03-29
**Status:** Accepted

## Context

The grove fleet spans multiple machines (Mac Mini, home server, gaming PC) running agents under different supervisors (launchd on macOS, systemd on Linux). Every grove version upgrade required:

1. SSH into each machine (or open a terminal session)
2. Run `uv tool install --force '...grove.git[serve]'`
3. Manually restart the service (`launchctl unload/load` or `systemctl restart`)

This is unsustainable as the fleet grows. There is also no way to trigger a fleet-wide upgrade without touching every machine.

Additionally, `/v1/agent/restart` was macOS-only, making it useless on the home server where elm runs under systemd.

## Decision

### 1. Cross-platform `/v1/agent/restart`

The existing `_detect_service_info()` already knows the correct restart command per platform:
- macOS: `launchctl kickstart -k gui/<uid>/ai.grove.serve.<agent>`
- Linux: `sudo systemctl restart grove-<agent>.service`

The restart endpoint now calls this helper rather than hardcoding launchctl. The old `_trigger_launchd_restart` function is replaced with `_trigger_service_restart(restart_cmd)`.

### 2. `/v1/agent/upgrade` endpoint

A new endpoint chains install + restart:
1. Reads `install_cmd` and `restart_cmd` from `_detect_service_info()`
2. Runs install as a blocking subprocess (up to 5 min timeout)
3. On success, triggers restart via the platform-appropriate command
4. Returns immediately — upgrade runs in the background

The install command is derived from `dist-info/direct_url.json`, so it reinstalls from the same source (Gitea SSH URL) that the agent was originally installed from. No explicit configuration needed.

### 3. Built-in `check_for_upgrade` scheduler action

When `heartbeat.auto_update = true` in `config.toml`, a built-in hourly job:
1. Derives the Gitea tags API URL from the grove dist-info install URL
2. Queries for available version tags (GITEA_TOKEN used if set in env)
3. Compares latest tag against `grove.__version__`
4. If a newer version exists, POSTs to `http://127.0.0.1:{port}/v1/agent/upgrade`

The version check URL can be overridden via `GROVE_UPGRADE_CHECK_URL` env var. The check is a no-op if no URL can be derived and no override is set.

### 4. `g fleet upgrade [agent]`

A new CLI command that hits `/v1/agent/upgrade` on every agent registered in the fleet gateway (or a specific named agent). Fleet gateway provides the `direct_url` for each agent. Auth via `GROVE_AGENT_{NAME}_TOKEN` env vars.

## Resulting Workflow

**Shipping a new version:**
```bash
git tag v0.x.y && git push origin v0.x.y
# → agents running with auto_update=true detect new tag within 1 hour, upgrade and restart
```

**On-demand fleet upgrade:**
```bash
g fleet upgrade          # all agents
g fleet upgrade elm      # specific agent
```

**Fleet health check:**
```bash
g fleet status           # version + health table for all agents
```

## One-time Manual Step (existing deployments)

Agents must have their plists/service files reloaded once to switch from `INNIE_HOME=~/.innie` to `GROVE_HOME=~/.grove`. After that, no manual restarts are needed. This is unavoidable for existing deployments.

## Alternatives Considered

**Watchtower-style container**: Would require dockerizing grove serve. Rejected — grove is a uv tool, not a container; adding Docker overhead is wrong for this use case.

**Push-based upgrade via A2A job**: A central agent could submit upgrade jobs to all agents. Rejected in favor of pull-based auto-check — simpler, no coordinator needed.

**systemd-based auto-update units**: Could use `systemd.timer` with a custom unit. Rejected — grove already has a scheduler; duplicating in systemd adds operational complexity.

**Explicit `GROVE_UPGRADE_URL` required**: Could require explicit config. Rejected — URL can be derived from dist-info, making zero-config the default.

## Consequences

- Zero-touch upgrades once `heartbeat.auto_update = true` and plists are reloaded
- `/v1/agent/restart` works on both macOS and Linux
- `g fleet status` gives a unified health view across all machines
- `g fleet upgrade` enables on-demand fleet-wide upgrades from any machine
- Version drift across agents is self-correcting within 1 hour
- `GITEA_TOKEN` in agent `.env` is optional but speeds up unauthenticated rate limiting on the tags API
