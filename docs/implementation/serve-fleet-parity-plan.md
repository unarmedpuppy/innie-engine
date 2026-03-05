# Plan: innie serve + fleet parity with agent-harness

**Goal:** Make `innie serve` and `innie fleet` fully replace agent-harness and fleet-gateway,
with dynamic agent registration instead of per-agent env vars.
**Applies to:** repo state after commit `b792779`

---

## How A2A Works Today (agent-harness)

### The Problem A2A Solves

Agents run on different machines (Avery on Mac Mini, Gilfoyle on home server). When Avery
needs Gilfoyle to check disk usage, she can't SSH. Instead she submits a *job* to Gilfoyle's
harness with a `reply_to` address so the result finds its way back.

### The Current Flow

```
1. Avery wants Gilfoyle to do something

   POST http://100.80.223.7:8018/v1/jobs
   {
     "prompt": "Check disk usage on /media",
     "reply_to": "agents://avery"
   }

2. Gilfoyle's harness accepts immediately, runs async
   { "job_id": "job-abc123", "status": "pending" }

3. Job completes. Gilfoyle reads reply_to = "agents://avery"
   Looks up env var: AGENT_REMOTE_AVERY_URL = http://100.92.176.74:8013

   POST http://100.92.176.74:8013/v1/jobs
   { "prompt": "[Message from gilfoyle]\n\n/media: 847GB used of 2TB" }

4. Avery's harness receives this as a new job, Claude reads the message
   and routes it (Mattermost DM, iMessage, etc.)
```

### Key Points

- **`agents://avery`** = "POST the result to Avery's `/v1/jobs` as a new job"
- **No dedicated inbound endpoint** — results arrive as new job prompts
- **Fire-and-forget** — delivery never blocks or retries
- **Agent URL resolution** = manual env var per agent, per machine (the problem)
- The scheme is `agents://` — human-readable, no legacy baggage

---

## The Architecture Problem: Static Config Everywhere

Both agent-harness (env vars) and innie's current fleet (YAML file) require manual updates
on every machine whenever:
- An agent is added
- A Tailscale IP changes
- A port changes

With 4+ agents across 3 machines, this is O(agents × machines) maintenance.

---

## Proposed Architecture: Fleet Gateway as Registry

**One env var per machine.** Each `innie serve` instance registers itself with the fleet
gateway on startup. `agents://` resolution asks the fleet gateway instead of reading
local env vars.

```
Every machine only needs:
  INNIE_FLEET_URL=https://fleet-gateway.server.unarmedpuppy.com

On startup, innie serve posts:
  POST {INNIE_FLEET_URL}/api/agents/register
  { "agent": "avery", "endpoint": "http://100.92.176.74:8013" }

When routing agents://avery:
  GET {INNIE_FLEET_URL}/api/agents/avery  →  { "endpoint": "..." }
  POST {endpoint}/v1/jobs  { "prompt": "[from gilfoyle]..." }
```

Adding a new agent = start `innie serve` with `INNIE_FLEET_URL` set. Nothing else to configure.

### Fallback

If fleet gateway is unreachable, fall back to `INNIE_AGENT_{NAME}_URL` env var.
This means the system degrades gracefully and can work without the fleet gateway.

---

## Full Gap Analysis

### What innie has ✓

| Feature | Notes |
|---------|-------|
| `POST /v1/jobs` | Full implementation |
| `GET /v1/jobs/{id}` | Full with cost/tokens |
| `GET /v1/jobs` | List with status filter |
| `POST /v1/jobs/{id}/cancel` | With SIGTERM |
| `reply_to: mattermost://` | Mattermost post |
| `reply_to: https://` | Generic webhook |
| Fleet agent health monitoring | Polls endpoints |
| `POST /api/jobs` fleet proxy | Proxies to agent |
| Memory/context injection | SOUL + CONTEXT + search |
| Session resume | `session_id` param |
| Bearer token auth | `INNIE_API_TOKEN` env |

### What's missing ✗

| # | Feature | Blocking? | Effort |
|---|---------|-----------|--------|
| 1 | `reply_to: agents://` in `notify_reply_to` | **Yes** | ~20 lines |
| 2 | SSRF allowlist rejects `agents://` at creation | **Yes** | 1 line |
| 3 | `POST /api/agents/register` on fleet gateway | **Yes** | ~40 lines |
| 4 | Fleet gateway persists registrations | **Yes** | ~20 lines |
| 5 | `innie serve` registers itself on startup | **Yes** | ~20 lines |
| 6 | `GET /v1/jobs/{id}/events` SSE endpoint | No | ~25 lines |
| 7 | Job persistence across restarts | No | Medium |

Items 1–5 together are the complete dynamic A2A system.
Items 6–7 are quality-of-life, not blockers.

---

## Implementation Plan

### Change 1 — Fleet gateway: `POST /api/agents/register`

**File:** `src/innie/fleet/gateway.py`

Add a registration endpoint and persist registrations to a JSON file so they survive
gateway restarts.

```python
# New model
class AgentRegistration(BaseModel):
    agent: str          # "avery"
    endpoint: str       # "http://100.92.176.74:8013"
    capabilities: list[str] = []
    version: str = ""

# Persist to disk so gateway restarts don't lose registrations
REGISTRY_PATH = Path.home() / ".innie" / "fleet-registry.json"

def _load_registry() -> dict:
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text())
    return {}

def _save_registry(reg: dict) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2))

@app.post("/api/agents/register")
async def register_agent(reg: AgentRegistration):
    """Called by innie serve on startup to register itself."""
    # Upsert into the in-memory agent registry
    if reg.agent not in agents:
        agents[reg.agent] = Agent(
            id=reg.agent,
            name=reg.agent.capitalize(),
            description=f"Self-registered agent",
            endpoint=reg.endpoint,
            agent_type="server",
            expected_online=True,
            tags=reg.capabilities,
        )
    else:
        agents[reg.agent].endpoint = reg.endpoint

    # Persist so gateway restart doesn't lose registrations
    registry = _load_registry()
    registry[reg.agent] = {"endpoint": reg.endpoint, "capabilities": reg.capabilities}
    _save_registry(registry)

    logger.info(f"Agent registered: {reg.agent} @ {reg.endpoint}")
    return {"status": "registered", "agent": reg.agent}
```

Also load persisted registrations at startup (in `lifespan`):

```python
# In lifespan, after loading config:
for agent_id, data in _load_registry().items():
    if agent_id not in agents:
        agents[agent_id] = Agent(
            id=agent_id,
            name=agent_id.capitalize(),
            endpoint=data["endpoint"],
            agent_type="server",
            expected_online=True,
            tags=data.get("capabilities", []),
        )
```

---

### Change 2 — `innie serve`: self-register on startup

**File:** `src/innie/commands/serve.py`

```python
async def _register_with_fleet(agent: str, port: int) -> None:
    fleet_url = os.environ.get("INNIE_FLEET_URL", "")
    if not fleet_url:
        return
    # Determine our own endpoint — use Tailscale IP if available
    host = os.environ.get("INNIE_SERVE_HOST", "")
    if not host:
        import socket
        host = socket.gethostbyname(socket.gethostname())
    endpoint = f"http://{host}:{port}"
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{fleet_url}/api/agents/register",
                json={"agent": agent, "endpoint": endpoint},
                timeout=5.0,
            )
        logger.info(f"Registered with fleet gateway as {agent} @ {endpoint}")
    except Exception as e:
        logger.warning(f"Fleet registration failed (non-fatal): {e}")
```

Call this from the FastAPI `lifespan` startup of the serve app, or as a background task
immediately after the server starts accepting connections.

Also add `INNIE_SERVE_HOST` env var support so each machine can explicitly declare its
reachable IP (important when the machine has multiple interfaces):

```bash
# On Mac Mini
INNIE_SERVE_HOST=100.92.176.74  # Tailscale IP
INNIE_FLEET_URL=https://fleet-gateway.server.unarmedpuppy.com
innie serve
```

---

### Change 3 — `notify_reply_to`: add `agents://` resolution

**File:** `src/innie/serve/app.py`

Two sub-changes:

**3a — SSRF allowlist** (at job creation):
```python
# Before
if scheme not in {"mattermost", "https"}:

# After
if scheme not in {"mattermost", "https", "agents"}:
```

**3b — `notify_reply_to` handler:**
```python
elif job.reply_to.startswith("agents://"):
    target_agent = job.reply_to.removeprefix("agents://")
    endpoint = await _resolve_agent_endpoint(target_agent)
    if not endpoint:
        logger.warning(
            f"Cannot resolve agents://{target_agent} — "
            f"set INNIE_FLEET_URL or INNIE_AGENT_{target_agent.upper()}_URL"
        )
        return
    from_agent = job.agent or paths.active_agent()
    result_text = (job.result or job.error or "")[:40_000]
    new_prompt = f"[Message from {from_agent}]\n\n{result_text}"
    token = os.environ.get(f"INNIE_AGENT_{target_agent.upper()}_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{endpoint}/v1/jobs",
            json={"prompt": new_prompt},
            headers=headers,
            timeout=10.0,
        )
```

**3c — `_resolve_agent_endpoint()` helper** (fleet-first, env var fallback):
```python
async def _resolve_agent_endpoint(agent_name: str) -> str:
    """Resolve an agent name to its /v1/jobs endpoint URL.

    Resolution order:
    1. Ask fleet gateway (if INNIE_FLEET_URL is set)
    2. Fall back to INNIE_AGENT_{NAME}_URL env var
    3. Return empty string (caller logs warning)
    """
    # Try fleet gateway first
    fleet_url = os.environ.get("INNIE_FLEET_URL", "")
    if fleet_url:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{fleet_url}/api/agents/{agent_name}",
                    timeout=3.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    # Agent model has endpoint field
                    endpoint = data.get("endpoint", "")
                    if endpoint:
                        return endpoint.rstrip("/")
        except Exception:
            pass  # Fall through to env var

    # Env var fallback
    env_key = f"INNIE_AGENT_{agent_name.upper()}_URL"
    return os.environ.get(env_key, "").rstrip("/")
```

---

### Change 4 — `GET /v1/jobs/{id}/events` (non-blocking)

**File:** `src/innie/serve/app.py`

```python
@app.get("/v1/jobs/{job_id}/events")
async def get_job_events(
    job_id: str,
    stream: bool = False,
    types: str | None = None,
    _auth=Depends(_require_auth),
):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    events = list(job.events or [])
    if types:
        allowed = set(types.split(","))
        events = [e for e in events if e.get("type") in allowed]

    return {
        "job_id": job_id,
        "status": job.status,
        "events": events,
        "count": len(events),
    }
```

SSE streaming (Option B, later) can be added here without breaking the interface.

---

## Environment Variables Reference

| Var | Where set | Purpose |
|-----|-----------|---------|
| `INNIE_FLEET_URL` | Every machine | Fleet gateway URL for registration + resolution |
| `INNIE_SERVE_HOST` | Every machine | This machine's reachable IP (Tailscale IP) |
| `INNIE_API_TOKEN` | Every machine | Bearer token for `/v1/jobs` auth |
| `INNIE_AGENT_{NAME}_URL` | Fallback only | Direct agent URL if fleet gateway is down |
| `INNIE_AGENT_{NAME}_TOKEN` | Optional | Per-agent bearer token for A2A calls |
| `MATTERMOST_BASE_URL` | Agent machines | For `mattermost://` reply_to |
| `MATTERMOST_BOT_TOKEN` | Agent machines | Mattermost bot auth |

---

## Rollout Sequence

Once implemented and pushed:

### Step 1 — Home server (Gilfoyle does this)
```bash
uv tool install --force git+ssh://gitea.server.unarmedpuppy.com:2223/homelab/innie-engine.git

# Set env vars (add to ~/.bashrc or systemd unit)
export INNIE_FLEET_URL=https://fleet-gateway.server.unarmedpuppy.com
export INNIE_SERVE_HOST=100.80.223.7    # Tailscale IP
export INNIE_API_TOKEN=<token>
export MATTERMOST_BASE_URL=https://mattermost.server.unarmedpuppy.com
export MATTERMOST_BOT_TOKEN=<token>

# Start innie serve for ralph (port 8013, existing)
INNIE_AGENT=ralph innie serve --port 8013

# Start innie serve for gilfoyle (port 8018, existing)
INNIE_AGENT=gilfoyle innie serve --port 8018

# Start innie fleet as the gateway (replacing fleet-gateway container)
innie fleet start
```

### Step 2 — Mac Mini (Avery)
```bash
export INNIE_FLEET_URL=https://fleet-gateway.server.unarmedpuppy.com
export INNIE_SERVE_HOST=100.92.176.74
export INNIE_API_TOKEN=<token>
INNIE_AGENT=avery innie serve --port 8013
```

### Step 3 — Josh's Mac (jobin)
```bash
export INNIE_FLEET_URL=https://fleet-gateway.server.unarmedpuppy.com
export INNIE_SERVE_HOST=<josh-mac-tailscale-ip>
INNIE_AGENT=jobin innie serve
```

### Step 4 — Verify
```bash
# Fleet should show all agents registered and online
curl https://fleet-gateway.server.unarmedpuppy.com/api/agents

# Test A2A: submit job with openclaw reply_to
curl -X POST http://100.92.176.74:8013/v1/jobs \
  -d '{"prompt":"ping","reply_to":"agents://gilfoyle"}'

# Gilfoyle should receive a new job
curl http://100.80.223.7:8018/v1/jobs
```

---

## Files to Change

| File | Changes |
|------|---------|
| `src/innie/fleet/gateway.py` | `POST /api/agents/register`, load persisted registry on startup |
| `src/innie/serve/app.py` | `agents://` in `notify_reply_to`, SSRF allowlist, `_resolve_agent_endpoint()`, `GET /v1/jobs/{id}/events` |
| `src/innie/commands/serve.py` | Self-register with fleet on startup |

Three files. ~120 lines total.
