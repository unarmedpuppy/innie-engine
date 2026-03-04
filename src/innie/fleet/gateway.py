"""Fleet gateway — FastAPI app for multi-machine agent coordination.

Provides:
  - Agent registry + health monitoring
  - Proxy to agent endpoints (context, jobs)
  - Fleet-wide job aggregation
  - Statistics
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from innie.fleet.config import load_fleet_config
from innie.fleet.health import HealthMonitor
from innie.fleet.models import (
    Agent,
    AgentStatus,
    JobCreateRequest,
    JobResponse,
)

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


# ── Helpers ─────────────────────────────────────────────────────────────────


def _get_online_agent(agent_id: str) -> Agent:
    agent = agents.get(agent_id)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    if agent.health.status == AgentStatus.OFFLINE:
        raise HTTPException(503, f"Agent '{agent_id}' is offline")
    return agent
