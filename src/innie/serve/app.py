"""FastAPI application for innie serve — jobs API, chat completions, memory CRUD.

Usage:
    innie serve [--port 8013] [--host 0.0.0.0]
"""

import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from innie.core import paths
from innie.core.context import build_session_context
from innie.serve.claude import collect_stream, graceful_kill, stream_claude_events
from innie.serve.job_store import JobStore
from innie.serve.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    Job,
    JobCreateRequest,
    JobCreateResponse,
    JobStatus,
    JobStatusResponse,
    MemoryContextResponse,
    Message,
    Usage,
)

logger = logging.getLogger(__name__)

SYNC_TIMEOUT = int(os.environ.get("INNIE_SYNC_TIMEOUT", 1800))
ASYNC_TIMEOUT = int(os.environ.get("INNIE_ASYNC_TIMEOUT", 7200))

_bearer = HTTPBearer(auto_error=False)


async def _require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    token = os.environ.get("INNIE_API_TOKEN", "")
    if not token or request.url.path == "/health":
        return
    if credentials is None or credentials.credentials != token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


async def _register_with_fleet() -> None:
    """Register this serve instance with the fleet gateway on startup."""
    fleet_url = os.environ.get("INNIE_FLEET_URL", "")
    if not fleet_url:
        return
    agent = paths.active_agent()
    if not agent:
        return
    host = os.environ.get("INNIE_SERVE_HOST", "")
    if not host:
        import socket
        try:
            host = socket.gethostbyname(socket.gethostname())
        except Exception:
            return
    port = int(os.environ.get("INNIE_SERVE_PORT", "8013"))
    endpoint = f"http://{host}:{port}"
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{fleet_url}/api/agents/register",
                json={"agent": agent, "endpoint": endpoint},
                timeout=5.0,
            )
        logger.info(f"Registered with fleet gateway as {agent} @ {endpoint}")
    except Exception as e:
        logger.warning(f"Fleet registration failed (non-fatal): {e}")


async def _resolve_agent_endpoint(agent_name: str) -> str:
    """Resolve agent name to endpoint URL. Fleet gateway first, env var fallback."""
    fleet_url = os.environ.get("INNIE_FLEET_URL", "")
    if fleet_url:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{fleet_url}/api/agents/{agent_name}",
                    timeout=3.0,
                )
                if resp.status_code == 200:
                    endpoint = resp.json().get("endpoint", "")
                    if endpoint:
                        return endpoint.rstrip("/")
        except Exception:
            pass
    env_key = f"INNIE_AGENT_{agent_name.upper()}_URL"
    return os.environ.get(env_key, "").rstrip("/")


def _ensure_dirs() -> None:
    """Ensure standard innie directory structure exists."""
    agent = paths.active_agent()
    for d in [
        paths.shared_skills_dir(),
        paths.data_dir(agent),
        paths.state_dir(agent),
        paths.sessions_dir(agent),
    ]:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


def _ensure_skills_symlink() -> None:
    """Ensure ~/.claude/skills symlinks to the shared innie skills directory."""
    shared = paths.shared_skills_dir()
    claude_skills = Path.home() / ".claude" / "skills"
    if claude_skills.is_symlink() and claude_skills.resolve() == shared.resolve():
        return
    try:
        claude_skills.parent.mkdir(parents=True, exist_ok=True)
        if claude_skills.exists() or claude_skills.is_symlink():
            claude_skills.unlink()
        claude_skills.symlink_to(shared)
        logger.info(f"Linked ~/.claude/skills -> {shared}")
    except Exception as e:
        logger.warning(f"Could not link ~/.claude/skills: {e}")


def _ensure_git_identity() -> None:
    """Apply git identity from profile.yaml if configured."""
    import subprocess
    import yaml

    profile_path = paths.profile_file()
    if not profile_path.exists():
        return
    try:
        with profile_path.open() as f:
            profile = yaml.safe_load(f) or {}
        git = profile.get("git", {})
        name = git.get("name")
        email = git.get("email")
        if name:
            subprocess.run(["git", "config", "--global", "user.name", name], check=True, capture_output=True)
        if email:
            subprocess.run(["git", "config", "--global", "user.email", email], check=True, capture_output=True)
        if name or email:
            logger.info(f"Git identity set: {name} <{email}>")
    except Exception as e:
        logger.warning(f"Could not set git identity: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global jobs
    jobs = _init_job_store()
    _ensure_dirs()
    _ensure_skills_symlink()
    _ensure_git_identity()
    await _register_with_fleet()
    from innie.channels.loader import start_channels, stop_channels
    from innie.serve.scheduler import setup_scheduler, teardown_scheduler
    await start_channels(app)
    agent = paths.active_agent()
    if agent:
        setup_scheduler(agent)
    yield
    await stop_channels()
    teardown_scheduler()


app = FastAPI(
    title="innie-engine",
    description="Persistent memory and identity for AI coding assistants",
    version="0.2.0",
    lifespan=lifespan,
    dependencies=[Depends(_require_auth)],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Persistent job store — initialised in lifespan so agent name is resolved
jobs: JobStore | None = None
active_pids: dict[str, int] = {}
_serve_start_time: float = time.time()


def _init_job_store() -> JobStore:
    agent = paths.active_agent()
    db_path = paths.state_dir(agent) / "jobs.db"
    return JobStore(db_path)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _resolve_context(agent: str | None, include_memory: bool) -> str | None:
    """Build context for injection into Claude CLI."""
    try:
        if include_memory:
            return build_session_context(agent_name=agent)
        # Lightweight: just user profile
        user_file = paths.user_file()
        if user_file.exists():
            return user_file.read_text().strip()
    except Exception as e:
        logger.warning(f"Context resolution failed: {e}")
    return None


def _resolve_working_dir(requested: str | None) -> str:
    home = str(paths.home())
    return requested or os.environ.get("HOME", home)


def _format_messages(messages: list[Message]) -> str:
    parts = []
    for msg in messages:
        role = msg.role.capitalize()
        if role == "System":
            parts.insert(0, f"[System Context]\n{msg.content}\n")
        else:
            parts.append(f"{role}: {msg.content}")
    return "\n\n".join(parts)


# ── Reply-to routing ─────────────────────────────────────────────────────────


async def notify_reply_to(job: Job) -> None:
    """Route job result to reply_to destination (fire-and-forget)."""
    if not job.reply_to:
        return
    try:
        payload = {
            "event": "job_complete",
            "job_id": job.id,
            "from_agent": job.agent or paths.active_agent(),
            "status": job.status,
            "result": (job.result or "")[:40000],
            "error": job.error,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if job.reply_to.startswith("mattermost://"):
            channel_id = job.reply_to.removeprefix("mattermost://")
            mm_url = os.environ.get("MATTERMOST_BASE_URL", "")
            mm_token = os.environ.get("MATTERMOST_BOT_TOKEN", "")
            if mm_url and mm_token:
                ok = job.status == JobStatus.COMPLETED
                text = (job.result or "")[:3000]
                agent = job.agent or paths.active_agent()
                msg = f"**[{agent}]** {'done' if ok else 'failed'}\n{text}"
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"{mm_url}/api/v4/posts",
                        headers={"Authorization": f"Bearer {mm_token}"},
                        json={"channel_id": channel_id, "message": msg},
                        timeout=5.0,
                    )

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

        elif job.reply_to.startswith(("https://", "http://")):
            async with httpx.AsyncClient() as client:
                await client.post(job.reply_to, json=payload, timeout=5.0)

        else:
            logger.warning(f"Unknown reply_to scheme: {job.reply_to}")

    except Exception as e:
        logger.warning(f"reply_to failed for job {job.id}: {e}")


# ── Job execution ────────────────────────────────────────────────────────────


async def execute_job(job_id: str) -> None:
    """Execute a job in the background."""
    job = jobs.get(job_id)
    if not job:
        return

    job.status = JobStatus.RUNNING
    job.started_at = datetime.utcnow().isoformat()
    jobs.update(job)

    working_dir = _resolve_working_dir(job.working_directory)
    context = _resolve_context(job.agent, job.include_memory)
    perm = job.permission_mode or "yolo"

    # Inject semantic search if available
    try:
        from innie.core.search import search_for_context

        mem_ctx = search_for_context(working_dir, job.agent)
        if mem_ctx:
            context = (context or "") + f"\n\n{mem_ctx}"
    except Exception:
        pass

    try:
        result = await collect_stream(
            prompt=job.prompt,
            model=job.model,
            system_prompt=context,
            permission_mode=perm,
            session_id=job.session_id,
            working_directory=working_dir,
            timeout=ASYNC_TIMEOUT,
        )

        job.status = JobStatus.COMPLETED
        job.result = result.text
        job.session_id = result.session_id
        job.cost_usd = result.cost_usd
        job.input_tokens = result.input_tokens
        job.output_tokens = result.output_tokens
        job.num_turns = result.num_turns
        job.events = result.events[:500]
        job.completed_at = datetime.utcnow().isoformat()
        jobs.update(job)

        logger.info(
            f"Job {job_id} completed: cost=${result.cost_usd:.4f}, turns={result.num_turns}"
        )

    except asyncio.TimeoutError:
        job.status = JobStatus.TIMEOUT
        job.error = f"Timed out after {ASYNC_TIMEOUT}s"
        job.completed_at = datetime.utcnow().isoformat()
        jobs.update(job)

    except Exception as e:
        job.status = JobStatus.FAILED
        job.error = str(e)
        job.completed_at = datetime.utcnow().isoformat()
        jobs.update(job)
        logger.error(f"Job {job_id} failed: {e}")

    finally:
        active_pids.pop(job_id, None)
        await notify_reply_to(job)


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    agent = paths.active_agent()
    job_counts: dict[str, int] = {}
    for job in jobs.values():
        job_counts[job.status] = job_counts.get(job.status, 0) + 1

    return {
        "status": "healthy",
        "agent": agent,
        "jobs": job_counts,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── Agent audit ─────────────────────────────────────────────────────────────


@app.get("/v1/agent/info")
async def agent_info():
    agent = paths.active_agent()
    profile_path = Path.home() / ".innie" / "agents" / (agent or "") / "profile.yaml"
    role = ""
    model = None
    provider = None
    if profile_path.exists():
        import yaml
        try:
            data = yaml.safe_load(profile_path.read_text()) or {}
            role = data.get("role", "")
            cc = data.get("claude-code", {}) or {}
            model = cc.get("model")
            if model:
                if model.startswith("claude"):
                    provider = "anthropic"
                else:
                    provider = "local"
        except Exception:
            pass
    uptime_s = int(time.time() - _serve_start_time)
    return {
        "agent": agent,
        "role": role,
        "model": model,
        "provider": provider,
        "version": "0.2.0",
        "uptime_seconds": uptime_s,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/v1/agent/skills")
async def agent_skills():
    from innie.skills.registry import discover_skills
    agent = paths.active_agent()
    skills = discover_skills(agent)
    return {
        "agent": agent,
        "skills": [
            {"name": s.name, "description": s.description}
            for s in sorted(skills.values(), key=lambda x: x.name)
        ],
        "count": len(skills),
    }


@app.get("/v1/agent/schedule")
async def agent_schedule():
    from innie.serve.scheduler import _load_schedule, _scheduler
    agent = paths.active_agent()
    sched_jobs = _load_schedule(agent or "")
    result = []
    for j in sched_jobs:
        next_run = None
        if _scheduler:
            try:
                job = _scheduler.get_job(j.name)
                if job and job.next_run_time:
                    next_run = job.next_run_time.isoformat()
            except Exception:
                pass
        result.append({
            "name": j.name,
            "enabled": j.enabled,
            "cron": j.cron,
            "interval_hours": j.interval_hours,
            "action": j.action,
            "prompt_preview": (j.prompt or "")[:120].strip() if j.prompt else None,
            "deliver_to": {"channel": j.deliver_to.channel, "contact": j.deliver_to.contact} if j.deliver_to else None,
            "reply_to": j.reply_to,
            "next_run": next_run,
        })
    return {"agent": agent, "jobs": result, "count": len(result)}


@app.get("/v1/agent/identity")
async def agent_identity():
    agent = paths.active_agent() or ""
    base = Path.home() / ".innie" / "agents" / agent

    def _read(path: Path) -> str | None:
        try:
            return path.read_text() if path.exists() else None
        except Exception:
            return None

    return {
        "agent": agent,
        "soul": _read(base / "SOUL.md"),
        "context": _read(base / "CONTEXT.md"),
        "profile": _read(base / "profile.yaml"),
    }


@app.get("/v1/agent/avatar")
async def agent_avatar():
    agent = paths.active_agent() or ""
    base = Path.home() / ".innie" / "agents" / agent
    for ext, mime in [("png", "image/png"), ("jpg", "image/jpeg"), ("jpeg", "image/jpeg"), ("webp", "image/webp"), ("gif", "image/gif")]:
        path = base / f"avatar.{ext}"
        if path.exists():
            return FileResponse(path, media_type=mime)
    raise HTTPException(status_code=404, detail="No avatar found")


@app.get("/v1/agent/audit")
async def agent_audit():
    """Combined audit endpoint — returns info + skills + schedule + identity in one call."""
    info = await agent_info()
    skills = await agent_skills()
    schedule = await agent_schedule()
    identity = await agent_identity()
    return {
        "info": info,
        "skills": skills["skills"],
        "schedule": schedule["jobs"],
        "identity": {
            "soul": identity["soul"],
            "context": identity["context"],
        },
    }


@app.post("/v1/schedule/{job_name}/trigger")
async def trigger_schedule_job(job_name: str, background_tasks: BackgroundTasks):
    """Manually fire a scheduled job by name."""
    from innie.serve.scheduler import trigger_job
    agent = paths.active_agent()
    ok = await trigger_job(job_name, agent or "")
    if not ok:
        raise HTTPException(status_code=404, detail=f"Scheduled job '{job_name}' not found or disabled")
    return {"status": "triggered", "job": job_name}


# ── Chat completions ────────────────────────────────────────────────────────


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """OpenAI-compatible chat completions (streaming + non-streaming)."""
    prompt = _format_messages(request.messages)
    working_dir = _resolve_working_dir(request.working_directory)
    context = _resolve_context(None, True)
    perm = request.permission_mode or "yolo"

    if request.stream:

        async def generate():
            response_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
            created = int(time.time())

            role_chunk = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": request.model,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(role_chunk)}\n\n"

            async for data in stream_claude_events(
                prompt=prompt,
                model=request.model,
                system_prompt=context,
                permission_mode=perm,
                session_id=request.session_id,
                working_directory=working_dir,
                timeout=SYNC_TIMEOUT,
            ):
                if data.get("type") == "assistant":
                    message = data.get("message", {})
                    for block in message.get("content", []):
                        if block.get("type") == "text":
                            chunk = {
                                "id": response_id,
                                "object": "chat.completion.chunk",
                                "created": created,
                                "model": request.model,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {"content": block["text"]},
                                        "finish_reason": None,
                                    }
                                ],
                            }
                            yield f"data: {json.dumps(chunk)}\n\n"

            finish = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": request.model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(finish)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    # Non-streaming
    result = await collect_stream(
        prompt=prompt,
        model=request.model,
        system_prompt=context,
        permission_mode=perm,
        session_id=request.session_id,
        working_directory=working_dir,
        timeout=SYNC_TIMEOUT,
    )

    return ChatCompletionResponse(
        model=request.model,
        choices=[
            Choice(
                message=Message(role="assistant", content=result.text),
                finish_reason="stop",
            )
        ],
        usage=Usage(
            prompt_tokens=result.input_tokens,
            completion_tokens=result.output_tokens,
            total_tokens=result.input_tokens + result.output_tokens,
        ),
        session_id=result.session_id,
    )


# ── Jobs API ─────────────────────────────────────────────────────────────────


@app.post("/v1/jobs", response_model=JobCreateResponse)
async def create_job(
    request: JobCreateRequest,
    background_tasks: BackgroundTasks,
):
    if request.reply_to:
        scheme = request.reply_to.split("://")[0] if "://" in request.reply_to else ""
        if scheme not in {"mattermost", "https", "agents"}:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported reply_to scheme '{scheme}'. Use mattermost://, https://, or agents://",
            )

    job_id = f"job-{uuid.uuid4().hex[:12]}"

    prompt = request.prompt
    if request.system_prompt:
        prompt = f"[System Context]\n{request.system_prompt}\n\nUser: {request.prompt}"

    working_dir = _resolve_working_dir(request.working_directory)

    job = Job(
        id=job_id,
        status=JobStatus.PENDING,
        prompt=prompt,
        model=request.model,
        created_at=datetime.utcnow().isoformat(),
        working_directory=working_dir,
        include_memory=request.include_memory,
        session_id=request.session_id,
        permission_mode=request.permission_mode,
        agent=request.agent,
        reply_to=request.reply_to,
    )
    jobs.add(job)

    background_tasks.add_task(execute_job, job_id)

    return JobCreateResponse(
        job_id=job_id,
        status=JobStatus.PENDING,
        message="Job created and queued",
        poll_url=f"/v1/jobs/{job_id}",
    )


@app.get("/v1/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    duration = None
    if job.started_at:
        start = datetime.fromisoformat(job.started_at)
        end = datetime.fromisoformat(job.completed_at) if job.completed_at else datetime.utcnow()
        duration = (end - start).total_seconds()

    return JobStatusResponse(
        id=job.id,
        status=job.status,
        prompt=job.prompt[:200] + "..." if len(job.prompt) > 200 else job.prompt,
        model=job.model,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        result=job.result,
        error=job.error,
        duration_seconds=duration,
        session_id=job.session_id,
        cost_usd=job.cost_usd,
        input_tokens=job.input_tokens,
        output_tokens=job.output_tokens,
        num_turns=job.num_turns,
    )


@app.get("/v1/jobs/{job_id}/events")
async def get_job_events(job_id: str, types: str | None = None):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    events = list(job.events or [])
    if types:
        allowed = set(types.split(","))
        events = [e for e in events if e.get("type") in allowed]
    return {"job_id": job_id, "status": job.status, "events": events, "count": len(events)}


@app.get("/v1/jobs")
async def list_jobs(
    status: JobStatus | None = None,
    limit: int = 50,
):
    filtered = list(jobs.values())
    if status:
        filtered = [j for j in filtered if j.status == status]
    filtered.sort(key=lambda j: j.created_at, reverse=True)
    filtered = filtered[:limit]

    return {
        "jobs": [
            {
                "id": j.id,
                "status": j.status,
                "model": j.model,
                "created_at": j.created_at,
                "completed_at": j.completed_at,
            }
            for j in filtered
        ],
        "total": len(jobs),
    }


@app.post("/v1/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if job.status != JobStatus.RUNNING:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not running (status: {job.status})",
        )

    pid = active_pids.get(job_id)
    if pid:
        await graceful_kill(pid)
        del active_pids[job_id]

    job.status = JobStatus.CANCELLED
    job.error = "Cancelled by user"
    job.completed_at = datetime.utcnow().isoformat()
    jobs.update(job)

    return {"message": f"Job {job_id} cancelled"}


@app.delete("/v1/jobs/{job_id}")
async def delete_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.status == JobStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Cancel the job first")
    jobs.delete(job_id)
    return {"message": f"Job {job_id} deleted"}


# ── Memory CRUD ──────────────────────────────────────────────────────────────


@app.get("/v1/memory/context")
async def get_memory_context():
    ctx_file = paths.context_file()
    if ctx_file.exists():
        stat = ctx_file.stat()
        return MemoryContextResponse(
            content=ctx_file.read_text(),
            last_modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
            size_bytes=stat.st_size,
        )
    return MemoryContextResponse(content="")


@app.put("/v1/memory/context")
async def update_memory_context(request: Request):
    body = await request.json()
    content = body.get("content", "")
    ctx_file = paths.context_file()
    ctx_file.parent.mkdir(parents=True, exist_ok=True)
    ctx_file.write_text(content)
    stat = ctx_file.stat()
    return MemoryContextResponse(
        content=content,
        last_modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
        size_bytes=stat.st_size,
    )


@app.get("/v1/memory/search")
async def search_memory_api(q: str, limit: int = 5):
    """Search the knowledge base via API."""
    try:
        from innie.core.search import (
            open_db,
            search_hybrid,
        )

        db_path = paths.index_db()
        if not db_path.exists():
            return {"results": [], "query": q}

        conn = open_db(db_path)
        results = search_hybrid(conn, q, limit=limit)
        conn.close()
        return {"results": results, "query": q, "count": len(results)}
    except Exception as e:
        return {"results": [], "query": q, "error": str(e)}


# ── Traces API ──────────────────────────────────────────────────────────────


@app.post("/v1/traces/events")
async def ingest_trace_event(request: Request):
    """Ingest a trace event (session start/end or span)."""
    from innie.core.trace import end_session, open_trace_db, record_span, start_session

    body = await request.json()
    event_type = body.get("type", "span")
    conn = open_trace_db()

    try:
        if event_type == "session_start":
            sid = start_session(
                conn,
                session_id=body.get("session_id"),
                agent_name=body.get("agent_name"),
                interactive=body.get("interactive", True),
                model=body.get("model"),
                cwd=body.get("cwd"),
                metadata=body.get("metadata"),
            )
            return {"status": "ok", "session_id": sid}

        elif event_type == "session_end":
            end_session(
                conn,
                session_id=body["session_id"],
                cost_usd=body.get("cost_usd"),
                input_tokens=body.get("input_tokens"),
                output_tokens=body.get("output_tokens"),
                num_turns=body.get("num_turns"),
            )
            return {"status": "ok"}

        elif event_type == "span":
            span_id = record_span(
                conn,
                session_id=body["session_id"],
                tool_name=body.get("tool_name", "unknown"),
                event_type=body.get("event_type", "tool_use"),
                input_json=body.get("input_json"),
                output_summary=body.get("output_summary"),
                status=body.get("status", "ok"),
                start_time=body.get("start_time"),
                end_time=body.get("end_time"),
                duration_ms=body.get("duration_ms"),
            )
            return {"status": "ok", "span_id": span_id}

        else:
            raise HTTPException(400, f"Unknown event type: {event_type}")
    finally:
        conn.close()


@app.get("/v1/traces")
async def list_traces_api(
    agent: str | None = None,
    limit: int = 50,
    days: int = 0,
):
    """List trace sessions."""
    import time as _time

    from innie.core.trace import list_sessions, open_trace_db, trace_db_path

    db = trace_db_path()
    if not db.exists():
        return {"sessions": [], "total": 0}

    conn = open_trace_db(db)
    since = _time.time() - (days * 86400) if days > 0 else None
    sessions = list_sessions(conn, agent_name=agent, limit=limit, since=since)
    conn.close()

    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "machine_id": s.machine_id,
                "agent_name": s.agent_name,
                "model": s.model,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "cost_usd": s.cost_usd,
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens,
                "num_turns": s.num_turns,
            }
            for s in sessions
        ],
        "total": len(sessions),
    }


@app.get("/v1/traces/{session_id}")
async def get_trace_api(session_id: str):
    """Get session detail with spans."""
    from innie.core.trace import get_session, open_trace_db, trace_db_path

    db = trace_db_path()
    if not db.exists():
        raise HTTPException(404, "No trace data")

    conn = open_trace_db(db)
    session = get_session(conn, session_id)
    conn.close()

    if not session:
        raise HTTPException(404, f"Session '{session_id}' not found")

    return {
        "session_id": session.session_id,
        "machine_id": session.machine_id,
        "agent_name": session.agent_name,
        "interactive": session.interactive,
        "model": session.model,
        "cwd": session.cwd,
        "start_time": session.start_time,
        "end_time": session.end_time,
        "cost_usd": session.cost_usd,
        "input_tokens": session.input_tokens,
        "output_tokens": session.output_tokens,
        "num_turns": session.num_turns,
        "metadata": session.metadata,
        "spans": [
            {
                "span_id": sp.span_id,
                "tool_name": sp.tool_name,
                "event_type": sp.event_type,
                "status": sp.status,
                "start_time": sp.start_time,
                "end_time": sp.end_time,
                "duration_ms": sp.duration_ms,
                "input_json": sp.input_json,
                "output_summary": sp.output_summary,
            }
            for sp in session.spans
        ],
        "span_count": len(session.spans),
    }


@app.get("/v1/traces/stats")
async def trace_stats_api(
    agent: str | None = None,
    days: int = 30,
):
    """Aggregate trace statistics."""
    import time as _time

    from innie.core.trace import get_stats, open_trace_db, trace_db_path

    db = trace_db_path()
    if not db.exists():
        return {"total_sessions": 0}

    conn = open_trace_db(db)
    since = _time.time() - (days * 86400) if days > 0 else None
    s = get_stats(conn, agent_name=agent, since=since)
    conn.close()

    return {
        "total_sessions": s.total_sessions,
        "total_spans": s.total_spans,
        "total_cost_usd": s.total_cost_usd,
        "total_input_tokens": s.total_input_tokens,
        "total_output_tokens": s.total_output_tokens,
        "avg_session_duration_s": s.avg_session_duration_s,
        "avg_turns_per_session": s.avg_turns_per_session,
        "tool_usage": s.tool_usage,
        "sessions_by_agent": s.sessions_by_agent,
        "sessions_by_day": s.sessions_by_day,
    }
