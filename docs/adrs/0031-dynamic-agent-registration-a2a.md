# ADR-0031 — Dynamic Agent Registration and A2A Communication

**Status:** Accepted
**Date:** 2026-03
**Supersedes:** ADR-0008 (fleet gateway static config — the "Future" note is now resolved)

---

## Context

ADR-0008 established the fleet gateway as a lightweight HTTP registry for multi-machine coordination.
The original design required manually updating a `fleet.yaml` file on every machine whenever an agent
was added, moved, or changed ports. For a fleet of 4+ agents across 3 machines, that's O(agents ×
machines) manual config.

There was also no mechanism for agents to communicate *asynchronously* with each other. If Avery (on
the Mac Mini) needed Gilfoyle (on the home server) to check disk usage, the only option was a
synchronous HTTP call that blocked until Gilfoyle responded — or implementing bespoke fire-and-forget
logic in the caller.

Two problems to solve:

1. **Static config**: every fleet topology change requires manual edits on every machine
2. **No A2A**: agents can't delegate tasks to each other and receive results asynchronously

---

## Decision

### 1. Self-registration

Each `innie serve` instance registers itself with the fleet gateway on startup:

```
POST {INNIE_FLEET_URL}/api/agents/register
{ "agent": "avery", "endpoint": "http://100.92.176.74:8013" }
```

The gateway upserts the agent into its in-memory registry and persists registrations to
`~/.innie/fleet-registry.json` so they survive gateway restarts.

Each machine only needs one env var: `INNIE_FLEET_URL`. `INNIE_SERVE_HOST` declares the reachable IP
(important when a machine has multiple interfaces — LAN vs Tailscale).

### 2. `agents://` scheme for async A2A

Job results are routed via `reply_to`, which already supported `mattermost://` and `https://`.
We added `agents://<name>` as a first-class scheme.

When a job with `reply_to: agents://gilfoyle` completes:
1. The serve app resolves `gilfoyle` to an endpoint (fleet gateway first, env var fallback)
2. POSTs the result as a *new job prompt* to `{endpoint}/v1/jobs`
3. Gilfoyle's harness receives it as an inbound job — Claude reads it and routes the response

There is no dedicated inbound endpoint. Results arrive as job prompts. This is intentional: it means
every agent already knows how to receive them, and you get the full job lifecycle (queuing, logging,
reply-to chaining) for free.

### 3. Endpoint resolution order

`_resolve_agent_endpoint(name)` tries in order:
1. `GET {INNIE_FLEET_URL}/api/agents/{name}` — dynamic, always current
2. `INNIE_AGENT_{NAME}_URL` env var — static fallback for when fleet is unreachable

This means the system degrades gracefully. Each machine can also hard-code fallback URLs and work
without the fleet gateway at all.

---

## Alternatives Considered

### Static env vars per agent (the agent-harness approach)

The prior system used `AGENT_REMOTE_{NAME}_URL` env vars. Every machine needed a full map of all
other agents. Worked fine with 2-3 agents; breaks down at 4+ across 3+ machines.

**Rejected**: O(agents × machines) maintenance, no central source of truth.

### Static fleet.yaml (original innie approach)

`fleet.yaml` on the gateway machine with all agent URLs. An improvement over per-machine env vars but
still requires manual edit + restart for every topology change.

**Rejected**: still manual. Adding a new agent means editing the YAML and restarting the gateway.

### Dedicated reply inbox (message queue / webhook)

Give each agent a dedicated inbound endpoint that only accepts results, separate from the jobs API.

**Rejected**: more surface area, no benefit. The jobs API already does queuing, authentication,
logging, and reply-to chaining. Receiving a result as a job prompt gives you all of that for free.

### gRPC/WebSocket persistent connections

Strong typing and bidirectional streaming, but significant infrastructure overhead.

**Rejected**: innie targets personal/homelab use. HTTP fire-and-forget is sufficient for the use
case.

---

## Consequences

**Positive:**
- Adding a new agent = set `INNIE_FLEET_URL` and start `innie serve`. Nothing else.
- Agents know about each other without hardcoded config — Claude can route intelligently.
- `reply_to: agents://name` chains multi-step workflows across machines with no extra code.
- Fleet gateway restart doesn't lose registrations (persisted to JSON).
- Degrades gracefully — env var fallback works without the fleet gateway.

**Negative:**
- `INNIE_SERVE_HOST` must be set correctly on machines with multiple interfaces. If unset, falls back
  to `socket.gethostbyname(hostname)` which may return a LAN IP unreachable from other machines.
- Fire-and-forget delivery — no retry on failure. If the target agent is down when the result
  arrives, the result is lost.
- Registration is not authenticated. Any process that can reach the fleet gateway can register an
  agent. Acceptable for homelab; would need a shared secret for production use.

---

## Environment Variables

| Variable | Set on | Purpose |
|----------|--------|---------|
| `INNIE_FLEET_URL` | Every machine | Fleet gateway URL for registration + resolution |
| `INNIE_SERVE_HOST` | Every machine | This machine's reachable IP (Tailscale IP preferred) |
| `INNIE_API_TOKEN` | Every machine | Bearer token for inbound auth on `/v1/jobs` |
| `INNIE_AGENT_{NAME}_URL` | Fallback only | Direct URL when fleet gateway is unreachable |
| `INNIE_AGENT_{NAME}_TOKEN` | Optional | Bearer token for outbound A2A calls to that agent |

---

## Implementation

Three files, ~120 lines:

| File | Change |
|------|--------|
| `src/innie/fleet/gateway.py` | `POST /api/agents/register`; `_load_registry()` / `_save_registry()`; load persisted registry in lifespan |
| `src/innie/serve/app.py` | `_register_with_fleet()` in lifespan; `_resolve_agent_endpoint()`; `agents://` branch in `notify_reply_to()`; SSRF allowlist update; `GET /v1/jobs/{id}/events` |
| `src/innie/commands/serve.py` | Set `INNIE_SERVE_PORT` env var before uvicorn so the app can construct its own endpoint URL |
