# Fleet Coordination

The fleet gateway lets multiple innie agents across machines discover each other, check health, and proxy jobs. It's optional — single-machine setups don't need it.

---

## Agent Types

| Type | Description |
|---|---|
| `SERVER` | Runs `innie serve`, has HTTP API, health-polled |
| `CLI` | Local agent, invoked via subprocess, not polled |

---

## Fleet YAML Config

```yaml
# ~/.innie/fleet.yaml or ./fleet.yaml

health_check:
  interval_seconds: 30      # How often to poll SERVER agents
  timeout_seconds: 10       # Per-request timeout
  failure_threshold: 3      # Failures before marking OFFLINE

agents:
  local:
    type: CLI
    description: "Local Claude Code instance"

  home-server:
    type: SERVER
    url: http://192.168.1.100:8013
    description: "Home server agent"

  work-laptop:
    type: SERVER
    url: http://192.168.1.200:8013
    description: "Work laptop agent"
```

Config location resolution order:
1. `INNIE_FLEET_CONFIG` env var
2. `./fleet.yaml`
3. `~/.innie/fleet.yaml`

---

## Health Monitoring

**File:** `src/innie/fleet/health.py`

The background health monitor polls all `SERVER` agents at `interval_seconds`:

```
Agent status states:
  UNKNOWN   ← initial state / not yet polled
  ONLINE    ← last poll succeeded
  DEGRADED  ← 1-2 consecutive failures
  OFFLINE   ← 3+ consecutive failures (failure_threshold)
```

Each agent tracks:

```python
@dataclass
class AgentHealth:
    status: AgentStatus
    last_check: float | None
    last_success: float | None
    consecutive_failures: int
    latency_ms: float | None
    error: str | None
```

Polling is async (`asyncio` + `httpx`). All agents are polled concurrently. Results update the in-memory registry.

---

## Gateway API

**File:** `src/innie/fleet/gateway.py`

The fleet gateway exposes:

| Endpoint | Description |
|---|---|
| `GET /api/agents` | List all agents with health status |
| `GET /api/agents/{id}` | Single agent detail |
| `POST /api/agents/{id}/health` | Force health check |
| `GET /api/agents/{id}/context` | Proxy to agent's `GET /v1/memory/context` |
| `POST /api/jobs` | Create job on specific agent (proxied) |
| `GET /api/jobs` | List jobs across all online agents |
| `GET /api/jobs/{id}` | Get job status (auto-routes to correct agent) |
| `POST /api/jobs/{id}/cancel` | Cancel job |
| `GET /api/stats` | Fleet-wide statistics |
| `GET /api/traces` | List trace sessions across all agents |
| `GET /api/traces/stats` | Aggregated trace stats across fleet |
| `GET /api/traces/{session_id}` | Find trace session on any machine |

Job routing: the gateway maintains a `{job_id: agent_id}` mapping so it can route status/cancel requests without the caller needing to know which agent the job is on.

---

## Fleet Statistics

`GET /api/stats` returns:

```json
{
  "total_agents": 3,
  "online": 2,
  "degraded": 0,
  "offline": 1,
  "cli_agents": 1,
  "server_agents": 2,
  "average_latency_ms": 45.2
}
```

---

## CLI Reference

```bash
innie fleet start                         # Start fleet gateway
innie fleet start --port 8020 --config ./fleet.yaml

innie fleet agents                        # Show agent status table
innie fleet stats                         # Show fleet statistics
```

---

## Multi-Machine Pattern

Typical homelab setup:

```
Mac Mini (Claude Code CLI)
    │
    │ runs innie fleet start --port 8020
    │
    ▼
Fleet Gateway :8020
    │
    ├─── Home Server :8013  (innie serve)
    │         ├── /v1/jobs
    │         ├── /v1/memory/context
    │         └── /health
    │
    └─── Work Laptop :8013  (innie serve, Tailscale)
              ├── /v1/jobs
              └── /health
```

The fleet gateway acts as a single control plane. Any agent can submit a job to any other agent by name rather than knowing the URL.
