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
from datetime import datetime

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from innie.core import paths
from innie.core.context import build_session_context
from innie.serve.claude import collect_stream, graceful_kill, stream_claude_events
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

app = FastAPI(
    title="innie-engine",
    description="Persistent memory and identity for AI coding assistants",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job store
jobs: dict[str, Job] = {}
active_pids: dict[str, int] = {}


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
        import httpx

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

        logger.info(
            f"Job {job_id} completed: cost=${result.cost_usd:.4f}, turns={result.num_turns}"
        )

    except asyncio.TimeoutError:
        job.status = JobStatus.TIMEOUT
        job.error = f"Timed out after {ASYNC_TIMEOUT}s"
        job.completed_at = datetime.utcnow().isoformat()

    except Exception as e:
        job.status = JobStatus.FAILED
        job.error = str(e)
        job.completed_at = datetime.utcnow().isoformat()
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
    jobs[job_id] = job

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

    return {"message": f"Job {job_id} cancelled"}


@app.delete("/v1/jobs/{job_id}")
async def delete_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.status == JobStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Cancel the job first")
    del jobs[job_id]
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
async def search_memory(q: str, limit: int = 5):
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
