# ADR-0041 — Semver Versioning and Fleet Health Control Plane

**Status:** Accepted
**Date:** 2026-03-11
**Context:** Fleet observability and agent lifecycle management

---

## Context

As the fleet grows (oak, avery, colin on Mac Mini; gilfoyle, ralph on the server), two problems emerged:

1. **No version visibility** — no way to know which version of innie-engine each agent is running. Hardcoded `"0.2.0"` strings littered the codebase with no single source of truth.

2. **Shallow health data** — the fleet dashboard showed online/offline/degraded but nothing about *why* an agent was degraded. Channel connectivity, heartbeat status, and model provider reachability were invisible.

3. **No remote control** — agents had to be restarted manually via SSH or launchctl from the machine they ran on.

---

## Decision

### 1. Single Version Source of Truth

`pyproject.toml` is the canonical version. All code reads it via `importlib.metadata`:

```python
from importlib.metadata import version
__version__ = version("innie-engine")
```

`src/innie/__init__.py` exports `__version__`. All FastAPI apps (`serve/app.py`, `fleet/gateway.py`) import it:

```python
from innie import __version__
app = FastAPI(version=__version__, ...)
```

No version string is ever hardcoded again.

### 2. Semver on Every Commit

Convention: bump the version before every commit that changes behavior, adds features, or fixes bugs. The bump script makes this a one-liner:

```bash
scripts/bump.sh patch   # 0.3.0 → 0.3.1 (bug fix, small change)
scripts/bump.sh minor   # 0.3.1 → 0.4.0 (new feature)
scripts/bump.sh major   # 0.4.0 → 1.0.0 (breaking change)
```

The script updates `pyproject.toml` and stages it. You write the commit message. The version travels with every install.

After bumping: `uv tool install --editable ~/workspace/innie-engine[serve]` picks up the new version. The agent reports it in `/health` immediately.

### 3. Rich `/health` Endpoint

The agent's `/health` response now includes:

```json
{
  "status": "healthy",
  "agent": "oak",
  "version": "0.3.0",
  "uptime_seconds": 3600,
  "host": "mac-mini",
  "jobs": {"completed": 5, "running": 1},
  "channels": [
    {"name": "mattermost", "enabled": true, "connected": true, "base_url": "https://..."},
    {"name": "bluebubbles", "enabled": false, "connected": false}
  ],
  "heartbeat": {
    "last_run": "2026-03-11T14:00:00",
    "status": "ok"
  },
  "model_provider": {
    "provider": "anthropic",
    "reachable": true,
    "latency_ms": 234.1
  },
  "timestamp": "2026-03-11T17:00:00"
}
```

**Channel health** — `channels/loader.py` tracks which channels were configured and started. Mattermost health is live-checked by inspecting the background task state (`.done()`, `.exception()`).

**Heartbeat health** — reads `~/.innie/agents/<name>/state/heartbeat-state.json` for last run time and status.

**Model provider health** — probes `https://api.anthropic.com` (or local LLM router if provider is local) with a 3-second HEAD request. Measures latency. Does not make an authenticated API call.

**Host** — `socket.gethostname()` so the fleet knows which physical machine each agent lives on.

### 4. Fleet Models — Rich `AgentHealth`

`fleet/models.py` gains structured sub-models:

```python
class ChannelHealth(BaseModel):
    name: str
    enabled: bool
    connected: bool
    base_url: str | None
    error: str | None

class HeartbeatHealth(BaseModel):
    last_run: str | None
    status: str | None

class ProviderHealth(BaseModel):
    provider: str | None
    reachable: bool
    latency_ms: float | None
    error: str | None

class AgentHealth(BaseModel):
    # ... existing fields ...
    version: str | None
    host: str | None
    uptime_seconds: int | None
    channels: list[ChannelHealth]
    heartbeat: HeartbeatHealth
    model_provider: ProviderHealth
```

The fleet health monitor (`fleet/health.py`) parses all these fields from the `/health` response on each poll cycle.

### 5. Remote Restart

**Agent side** — `POST /v1/agent/restart`:
- Returns `{"status": "restarting"}` immediately (fire-and-forget)
- Triggers `launchctl kickstart -k gui/<uid>/ai.innie.serve.<agent>` after a 300ms delay to let the response flush
- launchd kills the old process and starts a fresh one
- Currently macOS/launchd only — Docker environments handled separately

**Fleet side** — `POST /api/agents/{agent_id}/restart`:
- Proxies to the agent's restart endpoint
- Handles timeout gracefully (agent may die before responding)
- Fleet dashboard can surface a "Restart" button per agent

---

## Implementation Files

| File | Change |
|------|--------|
| `pyproject.toml` | Version bumped to `0.3.0` |
| `src/innie/__init__.py` | Uses `importlib.metadata.version()` |
| `src/innie/serve/app.py` | Imports `__version__`, enriched `/health`, adds `POST /v1/agent/restart` |
| `src/innie/channels/loader.py` | Tracks channel health state, exposes `get_channel_health()` |
| `src/innie/fleet/models.py` | Adds `ChannelHealth`, `HeartbeatHealth`, `ProviderHealth` sub-models |
| `src/innie/fleet/health.py` | Parses rich `/health` response into `AgentHealth` |
| `src/innie/fleet/gateway.py` | Imports `__version__`, adds `POST /api/agents/{id}/restart` |
| `scripts/bump.sh` | New — semver bump tool |

---

## Consequences

**Good:**
- Fleet dashboard can show version drift — if oak is on 0.3.1 and avery is on 0.3.0, that's visible
- Channel failures (Mattermost task died) surface immediately in fleet health
- Heartbeat staleness visible without SSH-ing to the machine
- Model provider outages detectable from the fleet view
- One-click restart from fleet rather than manual launchctl

**Constraints:**
- Model provider probe adds ~3s to every `/health` call if the provider is unreachable. This is bounded by the 3s timeout but means health checks take longer when things are broken
- Restart only works for launchd-managed agents (macOS). Docker/server agents need a separate mechanism (out of scope for this ADR)
- `host` is `socket.gethostname()` — consistent within a machine but not guaranteed to be the human-readable name. Set `INNIE_HOST` env var in the plist to override if needed

---

## Related

- ADR-0035 — Two-tier secret management
- ADR-0040 — Channel config and auth fallback
- `scripts/bump.sh` — version bump tool
- `AGENTS.md` — deployment instructions
