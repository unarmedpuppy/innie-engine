"""Fleet gateway — FastAPI app for multi-machine agent coordination.

Provides:
  - Agent registry + health monitoring
  - Proxy to agent endpoints (context, jobs)
  - Fleet-wide job aggregation
  - Statistics
"""

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from innie.fleet.config import load_fleet_config
from innie.fleet.health import HealthMonitor
from innie.fleet.models import (
    Agent,
    AgentStatus,
    JobCreateRequest,
    JobResponse,
)

REGISTRY_PATH = Path.home() / ".innie" / "fleet-registry.json"


class AgentRegistration(BaseModel):
    agent: str
    endpoint: str
    capabilities: list[str] = []
    version: str = ""


def _load_registry() -> dict:
    if REGISTRY_PATH.exists():
        try:
            return json.loads(REGISTRY_PATH.read_text())
        except Exception:
            pass
    return {}


def _save_registry(reg: dict) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2))

logger = logging.getLogger(__name__)

_fleet_bearer = HTTPBearer(auto_error=False)


async def _require_fleet_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_fleet_bearer),
) -> None:
    token = os.environ.get("INNIE_FLEET_TOKEN", "")
    if not token or request.url.path == "/health":
        return
    if credentials is None or credentials.credentials != token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


# Module-level state
health_monitor: HealthMonitor | None = None
agents: dict[str, Agent] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global health_monitor, agents

    config = load_fleet_config()

    # Build agent registry from config
    for agent_id, agent_cfg in config.agents.items():
        agents[agent_id] = Agent(
            id=agent_id,
            name=agent_cfg.name,
            description=agent_cfg.description,
            endpoint=agent_cfg.endpoint,
            agent_type=agent_cfg.agent_type,
            expected_online=agent_cfg.expected_online,
            tags=agent_cfg.tags,
            tailscale_dns=agent_cfg.tailscale_dns,
        )

    # Load dynamically registered agents (persisted across gateway restarts)
    for agent_id, data in _load_registry().items():
        if agent_id not in agents:
            agents[agent_id] = Agent(
                id=agent_id,
                name=agent_id.capitalize(),
                description="Self-registered agent",
                endpoint=data["endpoint"],
                agent_type="server",
                expected_online=True,
                tags=data.get("capabilities", []),
            )

    # Start health monitor
    health_monitor = HealthMonitor(
        agents=agents,
        interval=config.health_check.interval_seconds,
        timeout=config.health_check.timeout_seconds,
        failure_threshold=config.health_check.failure_threshold,
    )
    await health_monitor.start()
    logger.info(f"Fleet gateway started with {len(agents)} agents")

    yield

    await health_monitor.stop()


app = FastAPI(
    title="innie-fleet",
    description="Fleet gateway for multi-machine agent coordination",
    version="0.2.0",
    lifespan=lifespan,
    dependencies=[Depends(_require_fleet_auth)],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROXY_TIMEOUT = 30.0


# ── Health ──────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    online = sum(1 for a in agents.values() if a.health.status == AgentStatus.ONLINE)
    return {
        "status": "healthy",
        "agents_monitored": len(agents),
        "agents_online": online,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── Agent endpoints ─────────────────────────────────────────────────────────


@app.get("/api/agents")
async def list_agents(
    status: AgentStatus | None = None,
    tag: str | None = None,
):
    filtered = list(agents.values())
    if status:
        filtered = [a for a in filtered if a.health.status == status]
    if tag:
        filtered = [a for a in filtered if tag in a.tags]
    return {"agents": [a.model_dump() for a in filtered]}


@app.get("/api/agents/stats")
async def agent_stats():
    if health_monitor:
        return health_monitor.get_stats().model_dump()
    return {}


@app.get("/api/agents/{agent_id}")
async def get_agent(agent_id: str):
    agent = agents.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    return agent.model_dump()


@app.post("/api/agents/register")
async def register_agent(reg: AgentRegistration):
    """Called by innie serve on startup to register itself with the fleet."""
    if reg.agent not in agents:
        agents[reg.agent] = Agent(
            id=reg.agent,
            name=reg.agent.capitalize(),
            description="Self-registered agent",
            endpoint=reg.endpoint,
            agent_type="server",
            expected_online=True,
            tags=reg.capabilities,
        )
    else:
        agents[reg.agent].endpoint = reg.endpoint
        if reg.capabilities:
            agents[reg.agent].tags = reg.capabilities

    registry = _load_registry()
    registry[reg.agent] = {"endpoint": reg.endpoint, "capabilities": reg.capabilities}
    _save_registry(registry)

    logger.info(f"Agent registered: {reg.agent} @ {reg.endpoint}")
    return {"status": "registered", "agent": reg.agent}


@app.post("/api/agents/{agent_id}/check")
async def force_check(agent_id: str):
    if agent_id not in agents:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    if health_monitor:
        await health_monitor.check_now(agent_id)
    agent = agents[agent_id]
    return {"agent_id": agent_id, "health": agent.health.model_dump()}


# ── Agent context (memory) ──────────────────────────────────────────────────


@app.get("/api/agents/{agent_id}/context")
async def get_agent_context(agent_id: str):
    agent = _get_online_agent(agent_id)
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{agent.endpoint}/v1/memory/context",
                timeout=PROXY_TIMEOUT,
            )
            return resp.json()
        except Exception as e:
            raise HTTPException(502, f"Failed to reach agent: {e}")


@app.put("/api/agents/{agent_id}/context")
async def update_agent_context(agent_id: str, body: dict):
    agent = _get_online_agent(agent_id)
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.put(
                f"{agent.endpoint}/v1/memory/context",
                json=body,
                timeout=PROXY_TIMEOUT,
            )
            return resp.json()
        except Exception as e:
            raise HTTPException(502, f"Failed to reach agent: {e}")


# ── Jobs ────────────────────────────────────────────────────────────────────


@app.post("/api/jobs")
async def create_job(request: JobCreateRequest):
    agent = _get_online_agent(request.agent_id)

    payload = {
        "prompt": request.prompt,
        "model": request.model,
        "working_directory": request.working_directory,
        "system_prompt": request.system_prompt,
        "include_memory": request.include_memory,
        "session_id": request.session_id,
        "permission_mode": request.permission_mode,
        "reply_to": request.reply_to,
        "agent": request.agent_id,
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{agent.endpoint}/v1/jobs",
                json=payload,
                timeout=PROXY_TIMEOUT,
            )
            data = resp.json()
            return JobResponse(
                job_id=data.get("job_id", ""),
                agent_id=request.agent_id,
                status=data.get("status", "pending"),
                message=data.get("message"),
                poll_url=data.get("poll_url"),
            )
        except Exception as e:
            raise HTTPException(502, f"Failed to submit job: {e}")


@app.get("/api/jobs")
async def list_jobs(
    agent_id: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    """List jobs, optionally filtered by agent and status."""
    all_jobs = []

    targets = [agents[agent_id]] if agent_id and agent_id in agents else list(agents.values())
    targets = [a for a in targets if a.health.status == AgentStatus.ONLINE]

    async with httpx.AsyncClient() as client:
        for agent in targets:
            try:
                params = {"limit": limit}
                if status:
                    params["status"] = status
                resp = await client.get(
                    f"{agent.endpoint}/v1/jobs",
                    params=params,
                    timeout=PROXY_TIMEOUT,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for job in data.get("jobs", []):
                        job["agent_id"] = agent.id
                        all_jobs.append(job)
            except Exception:
                continue

    all_jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return {"jobs": all_jobs[:limit], "total": len(all_jobs)}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, agent_id: str | None = None):
    """Get job status. Searches all online agents if agent_id not provided."""
    targets = (
        [agents[agent_id]]
        if agent_id and agent_id in agents
        else [a for a in agents.values() if a.health.status == AgentStatus.ONLINE]
    )

    async with httpx.AsyncClient() as client:
        for agent in targets:
            try:
                resp = await client.get(
                    f"{agent.endpoint}/v1/jobs/{job_id}",
                    timeout=PROXY_TIMEOUT,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    data["agent_id"] = agent.id
                    return data
            except Exception:
                continue

    raise HTTPException(404, f"Job '{job_id}' not found")


@app.delete("/api/jobs/{job_id}")
async def cancel_job(job_id: str, agent_id: str | None = None):
    """Cancel a running job."""
    targets = (
        [agents[agent_id]]
        if agent_id and agent_id in agents
        else [a for a in agents.values() if a.health.status == AgentStatus.ONLINE]
    )

    async with httpx.AsyncClient() as client:
        for agent in targets:
            try:
                resp = await client.post(
                    f"{agent.endpoint}/v1/jobs/{job_id}/cancel",
                    timeout=PROXY_TIMEOUT,
                )
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                continue

    raise HTTPException(404, f"Job '{job_id}' not found or not cancellable")


# ── Traces ─────────────────────────────────────────────────────────────────


@app.get("/api/traces")
async def list_traces(
    agent_id: str | None = None,
    days: int = Query(7, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
):
    """Aggregate traces across all online agents."""
    all_traces = []
    targets = [agents[agent_id]] if agent_id and agent_id in agents else list(agents.values())
    targets = [a for a in targets if a.health.status == AgentStatus.ONLINE]

    async with httpx.AsyncClient() as client:
        for agent in targets:
            try:
                resp = await client.get(
                    f"{agent.endpoint}/v1/traces",
                    params={"days": days, "limit": limit},
                    timeout=PROXY_TIMEOUT,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for session in data.get("sessions", []):
                        session["agent_id"] = agent.id
                        all_traces.append(session)
            except Exception:
                continue

    all_traces.sort(key=lambda t: t.get("start_time", 0), reverse=True)
    return {"sessions": all_traces[:limit], "total": len(all_traces)}


@app.get("/api/traces/stats")
async def trace_stats(
    agent_id: str | None = None,
    days: int = Query(30, ge=1, le=365),
):
    """Aggregate trace statistics across the fleet."""
    combined: dict = {
        "total_sessions": 0,
        "total_spans": 0,
        "total_cost_usd": 0.0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "tool_usage": {},
        "sessions_by_agent": {},
        "sessions_by_machine": {},
    }

    targets = [agents[agent_id]] if agent_id and agent_id in agents else list(agents.values())
    targets = [a for a in targets if a.health.status == AgentStatus.ONLINE]

    async with httpx.AsyncClient() as client:
        for agent in targets:
            try:
                resp = await client.get(
                    f"{agent.endpoint}/v1/traces/stats",
                    params={"days": days},
                    timeout=PROXY_TIMEOUT,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    combined["total_sessions"] += data.get("total_sessions", 0)
                    combined["total_spans"] += data.get("total_spans", 0)
                    combined["total_cost_usd"] += data.get("total_cost_usd", 0)
                    combined["total_input_tokens"] += data.get("total_input_tokens", 0)
                    combined["total_output_tokens"] += data.get("total_output_tokens", 0)

                    for tool, count in data.get("tool_usage", {}).items():
                        combined["tool_usage"][tool] = combined["tool_usage"].get(tool, 0) + count

                    for ag, count in data.get("sessions_by_agent", {}).items():
                        combined["sessions_by_agent"][ag] = (
                            combined["sessions_by_agent"].get(ag, 0) + count
                        )

                    combined["sessions_by_machine"][agent.id] = data.get("total_sessions", 0)
            except Exception:
                continue

    return combined


@app.get("/api/traces/{session_id}")
async def get_trace(session_id: str, agent_id: str | None = None):
    """Get trace detail. Searches all online agents if agent_id not provided."""
    targets = (
        [agents[agent_id]]
        if agent_id and agent_id in agents
        else [a for a in agents.values() if a.health.status == AgentStatus.ONLINE]
    )

    async with httpx.AsyncClient() as client:
        for agent in targets:
            try:
                resp = await client.get(
                    f"{agent.endpoint}/v1/traces/{session_id}",
                    timeout=PROXY_TIMEOUT,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    data["agent_id"] = agent.id
                    return data
            except Exception:
                continue

    raise HTTPException(404, f"Trace '{session_id}' not found")


# ── Agent audit proxy ───────────────────────────────────────────────────────


@app.get("/api/agents/{agent_id}/audit")
async def get_agent_audit(agent_id: str):
    """Proxy /v1/agent/audit from the agent's serve instance."""
    agent = agents.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{agent.endpoint}/v1/agent/audit",
                timeout=PROXY_TIMEOUT,
            )
            data = resp.json()
            data["_agent_id"] = agent_id
            data["_status"] = agent.health.status
            return data
        except Exception as e:
            # Return partial data so dashboard still renders
            return {
                "_agent_id": agent_id,
                "_status": "offline",
                "_error": str(e),
                "info": {"agent": agent_id, "role": agent.description, "uptime_seconds": None},
                "skills": [],
                "schedule": [],
                "identity": {"soul": None, "context": None},
            }


@app.get("/api/agents/{agent_id}/avatar")
async def get_agent_avatar(agent_id: str):
    """Proxy agent avatar image from the agent's serve instance."""
    from fastapi.responses import Response
    agent = agents.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{agent.endpoint}/v1/agent/avatar", timeout=5.0)
            if resp.status_code == 200:
                return Response(content=resp.content, media_type=resp.headers.get("content-type", "image/png"))
        except Exception:
            pass
    raise HTTPException(404, "No avatar")


@app.post("/api/agents/{agent_id}/schedule/{job_name}/trigger")
async def trigger_agent_schedule_job(agent_id: str, job_name: str):
    """Proxy schedule job trigger to the agent's serve instance."""
    agent = _get_online_agent(agent_id)
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{agent.endpoint}/v1/schedule/{job_name}/trigger",
                timeout=PROXY_TIMEOUT,
            )
            return resp.json()
        except Exception as e:
            raise HTTPException(502, f"Failed to trigger job: {e}")


# ── Dashboard ────────────────────────────────────────────────────────────────


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>innie fleet</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0f0f12;color:#e2e2e7;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:14px;padding:24px}
h1{font-size:20px;font-weight:600;color:#fff;margin-bottom:4px}
.subtitle{color:#6b7280;font-size:13px;margin-bottom:28px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:16px}
.card{background:#17171c;border:1px solid #2a2a35;border-radius:10px;overflow:hidden}
.card-header{display:flex;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid #2a2a35}
.dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.dot.online{background:#22c55e}.dot.offline{background:#ef4444}.dot.degraded{background:#f59e0b}.dot.unknown{background:#6b7280}
.agent-name{font-weight:600;font-size:15px;color:#fff}
.agent-role{font-size:12px;color:#6b7280;margin-top:1px}
.uptime{margin-left:auto;font-size:12px;color:#6b7280}
.avatar{width:36px;height:36px;border-radius:50%;object-fit:cover;flex-shrink:0;background:#2a2a35}
.avatar-placeholder{width:36px;height:36px;border-radius:50%;background:#2a2a35;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:600;color:#6b7280}
.card-body{padding:14px 16px}
.section{margin-bottom:14px}
.section:last-child{margin-bottom:0}
.section-label{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#4b5563;margin-bottom:6px;font-weight:600}
.skill-list{display:flex;flex-direction:column;gap:3px}
.skill{font-size:12px;color:#9ca3af}
.skill strong{color:#d1d5db;margin-right:4px}
.sched-list{display:flex;flex-direction:column;gap:4px}
.sched-item{font-size:12px;padding:4px 8px;background:#1e1e26;border-radius:5px;color:#9ca3af}
.sched-item.enabled{border-left:2px solid #22c55e}.sched-item.disabled{border-left:2px solid #374151;opacity:.5}
.sched-name{font-weight:600;color:#d1d5db;margin-right:6px}
.sched-trigger-btn{float:right;font-size:11px;padding:1px 7px;background:#1d4ed8;color:#bfdbfe;border:none;border-radius:3px;cursor:pointer}
.sched-trigger-btn:hover{background:#2563eb}
.context-preview{font-size:12px;color:#6b7280;white-space:pre-wrap;max-height:90px;overflow:hidden;line-height:1.5}
.collapsible-header{display:flex;align-items:center;justify-content:space-between;cursor:pointer;user-select:none}
.collapsible-header:hover .section-label{color:#9ca3af}
.collapse-toggle{font-size:11px;color:#374151;transition:transform .15s}
.collapse-toggle.open{transform:rotate(90deg)}
.collapsible-body{overflow:hidden;transition:max-height .2s ease}
.collapsible-body.closed{max-height:0}
.error{color:#f87171;font-size:12px;padding:8px;background:#1c1111;border-radius:5px}
.loading{color:#4b5563;font-size:13px;padding:8px}
.meta-pill{display:inline-block;font-size:11px;background:#1e2030;color:#818cf8;padding:1px 6px;border-radius:3px;margin-left:4px}
.meta-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.meta-item{font-size:12px;color:#9ca3af}.meta-item strong{color:#d1d5db;margin-right:4px}
.dns-link{font-size:12px;color:#60a5fa;text-decoration:none;font-family:monospace}.dns-link:hover{text-decoration:underline}
</style>
</head>
<body>
<h1>innie fleet</h1>
<p class="subtitle" id="subtitle">Loading agents…</p>
<div class="grid" id="grid"></div>
<script>
const BASE = '';
async function load() {
  const r = await fetch(BASE + '/api/agents');
  const {agents} = await r.json();
  document.getElementById('subtitle').textContent =
    agents.length + ' agent' + (agents.length !== 1 ? 's' : '') + ' registered';
  const grid = document.getElementById('grid');
  grid.innerHTML = '';
  for (const a of agents) {
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = '<div class="card-body loading">Loading ' + a.id + '…</div>';
    grid.appendChild(card);
    fetchAudit(a, card);
  }
}
async function fetchAudit(a, card) {
  try {
    const r = await fetch(BASE + '/api/agents/' + a.id + '/audit');
    const d = await r.json();
    renderCard(a, d, card);
  } catch(e) {
    card.innerHTML = '<div class="card-body error">Failed to load ' + a.id + ': ' + e + '</div>';
  }
}
function fmtUptime(s) {
  if (!s) return '';
  if (s < 60) return s + 's';
  if (s < 3600) return Math.floor(s/60) + 'm';
  return Math.floor(s/3600) + 'h ' + Math.floor((s%3600)/60) + 'm';
}
function fmtCron(j) {
  if (j.cron) return j.cron;
  if (j.interval_hours) return 'every ' + j.interval_hours + 'h';
  if (j.action) return j.action;
  return '?';
}
function renderCard(a, d, card) {
  const info = d.info || {};
  const status = d._status || a.health?.status || 'unknown';
  const sched = d.schedule || [];
  const ctx = (d.identity && d.identity.context) || '';
  const ctxPreview = ctx.split('\\n').filter(l => l.trim() && !l.startsWith('#')).slice(0,6).join('\\n');
  const model = info.model || null;
  const provider = info.provider || null;
  const dns = a.tailscale_dns || null;
  const metaHtml = (model || dns) ?
    '<div class="section"><div class="meta-row">' +
    (model ? '<span class="meta-item"><strong>' + (provider || 'model') + '</strong>' + model + '</span>' : '') +
    (dns ? '<a class="dns-link" href="http://' + dns + '" target="_blank">' + dns + '</a>' : '') +
    '</div></div>' : '';
  const schedId = 'sched-' + a.id;
  const schedCount = sched.filter(j => j.enabled).length;
  const schedLabel = sched.length === 0 ? 'Schedule' :
    'Schedule <span style="color:#374151;font-weight:400">(' + schedCount + '/' + sched.length + ' active)</span>';
  const schedInner = sched.length === 0 ? '<span style="color:#4b5563">none</span>' :
    '<div class="sched-list">' + sched.map(j =>
      '<div class="sched-item ' + (j.enabled ? 'enabled' : 'disabled') + '">' +
      '<button class="sched-trigger-btn" onclick="trigger(\\'' + a.id + '\\',\\'' + j.name + '\\',this)" ' + (j.enabled ? '' : 'disabled') + '>run</button>' +
      '<span class="sched-name">' + j.name + '</span>' +
      '<span style="color:#4b5563">' + fmtCron(j) + '</span>' +
      (j.next_run ? '<br><span style="font-size:11px;color:#374151">next: ' + j.next_run.substring(0,16).replace('T',' ') + '</span>' : '') +
      '</div>'
    ).join('') + '</div>';
  const schedHtml =
    '<div class="collapsible-header" onclick="toggleSched(\\'' + schedId + '\\')">' +
    '<div class="section-label">' + schedLabel + '</div>' +
    (sched.length > 0 ? '<span class="collapse-toggle" id="tog-' + schedId + '">▶</span>' : '') +
    '</div>' +
    '<div class="collapsible-body closed" id="' + schedId + '">' + schedInner + '</div>';
  const avatarHtml = '<img class="avatar" src="' + BASE + '/api/agents/' + a.id + '/avatar" ' +
    'onerror="this.outerHTML=\'<div class=\\"avatar-placeholder\\">' + (info.agent || a.id).charAt(0).toUpperCase() + '</div>\'">';
  card.innerHTML =
    '<div class="card-header">' +
    avatarHtml +
    '<div style="flex:1;min-width:0"><div class="agent-name">' + (info.agent || a.id) + '</div>' +
    '<div class="agent-role">' + (info.role || a.description || '') + '</div></div>' +
    '<div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px">' +
    '<div class="uptime">' + (status === 'online' ? fmtUptime(info.uptime_seconds) : status) + '</div>' +
    '<div class="dot ' + status + '"></div>' +
    '</div>' +
    '</div>' +
    '<div class="card-body">' +
    (d._error ? '<div class="error">' + d._error + '</div>' : '') +
    metaHtml +
    '<div class="section">' + schedHtml + '</div>' +
    (ctxPreview ? '<div class="section"><div class="section-label">Open items</div><div class="context-preview">' + ctxPreview + '</div></div>' : '') +
    '</div>';
}
function toggleSched(id) {
  const body = document.getElementById(id);
  const tog = document.getElementById('tog-' + id);
  if (!body) return;
  const isOpen = !body.classList.contains('closed');
  if (isOpen) {
    body.style.maxHeight = body.scrollHeight + 'px';
    requestAnimationFrame(() => { body.style.maxHeight = '0'; body.classList.add('closed'); });
    if (tog) tog.classList.remove('open');
  } else {
    body.classList.remove('closed');
    body.style.maxHeight = body.scrollHeight + 'px';
    setTimeout(() => { body.style.maxHeight = 'none'; }, 200);
    if (tog) tog.classList.add('open');
  }
}
async function trigger(agentId, jobName, btn) {
  btn.disabled = true;
  btn.textContent = '…';
  try {
    const r = await fetch(BASE + '/api/agents/' + agentId + '/schedule/' + jobName + '/trigger', {method:'POST'});
    const d = await r.json();
    btn.textContent = d.status === 'triggered' ? '✓' : 'err';
  } catch(e) {
    btn.textContent = 'err';
  }
  setTimeout(() => { btn.disabled = false; btn.textContent = 'run'; }, 3000);
}
load();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard():
    return HTMLResponse(_DASHBOARD_HTML)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _get_online_agent(agent_id: str) -> Agent:
    agent = agents.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    if agent.health.status == AgentStatus.OFFLINE:
        raise HTTPException(503, f"Agent '{agent_id}' is offline")
    return agent
