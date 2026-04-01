"""Claude Code CLI subprocess management — streaming and non-streaming."""

import asyncio
import json
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)

# ── Inference URL circuit breaker ─────────────────────────────────────────────
#
# When ANTHROPIC_FALLBACK_BASE_URL is set, grove probes the primary
# ANTHROPIC_BASE_URL before each job and routes to the fallback if it's
# unhealthy. The probe result is cached for GROVE_FALLBACK_CHECK_INTERVAL
# seconds (default 30) to avoid adding latency to every job.
#
# State is module-level (one circuit breaker per process).

_primary_healthy: bool = True
_last_probe_time: float = 0.0      # monotonic, for interval math
_last_probe_wall: float = 0.0      # wall clock, for diagnostics
_probe_lock: Optional[asyncio.Lock] = None


def _get_probe_lock() -> asyncio.Lock:
    global _probe_lock
    if _probe_lock is None:
        _probe_lock = asyncio.Lock()
    return _probe_lock


def _probe_interval() -> float:
    # Env var overrides config; config overrides default
    env_val = os.environ.get("GROVE_FALLBACK_CHECK_INTERVAL")
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            pass
    try:
        from grove.core.config import get as _cfg_get
        return float(_cfg_get("serve.fallback_check_interval", 30))
    except Exception:
        return 30.0


async def _probe_url(url: str) -> bool:
    """Check reachability of an Anthropic-compatible base URL.

    Strips the /v1 path suffix and hits /health. Returns True if the server
    responds with any non-5xx status, False on connection error or timeout.
    """
    import httpx

    base = url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{base}/health", follow_redirects=False)
            return r.status_code < 500
    except Exception:
        return False


async def _choose_base_url() -> tuple[str, str | None]:
    """Return (inference_base_url, model_override) for this job.

    model_override is non-None when on fallback and GROVE_FALLBACK_MODEL is set,
    allowing the caller to swap the model to one the fallback endpoint understands.

    If ANTHROPIC_FALLBACK_BASE_URL is not set, returns (ANTHROPIC_BASE_URL, None)
    with no circuit breaker logic applied.
    """
    global _primary_healthy, _last_probe_time, _last_probe_wall

    primary = os.environ.get("ANTHROPIC_BASE_URL", "")
    fallback = os.environ.get("ANTHROPIC_FALLBACK_BASE_URL", "")

    if not fallback:
        return primary, None

    now = time.monotonic()
    if (now - _last_probe_time) >= _probe_interval():
        async with _get_probe_lock():
            if (time.monotonic() - _last_probe_time) >= _probe_interval():
                _last_probe_time = time.monotonic()
                _last_probe_wall = time.time()
                was_healthy = _primary_healthy
                _primary_healthy = await _probe_url(primary)
                if _primary_healthy and not was_healthy:
                    logger.info(
                        "[claude] primary inference URL recovered — switching back: %s", primary
                    )
                    asyncio.create_task(_notify_fallback_transition(on_fallback=False))
                elif not _primary_healthy and was_healthy:
                    logger.warning(
                        "[claude] primary inference URL unreachable — switching to fallback: %s",
                        fallback,
                    )
                    asyncio.create_task(_notify_fallback_transition(on_fallback=True))

    if _primary_healthy:
        return primary, None
    else:
        return fallback, (os.environ.get("GROVE_FALLBACK_MODEL") or None)


async def _notify_fallback_transition(on_fallback: bool) -> None:
    """Fire-and-forget Mattermost DM to Josh when circuit breaker trips or recovers."""
    channel = os.environ.get("GROVE_FALLBACK_NOTIFY_MM_CHANNEL", "")
    token = os.environ.get("MATTERMOST_BOT_TOKEN", "")
    if not channel or not token:
        return

    mm_url = _mm_base_url()
    if not mm_url:
        return

    agent = os.environ.get("GROVE_AGENT", "agent")
    fallback_model = os.environ.get("GROVE_FALLBACK_MODEL", "local")
    primary = os.environ.get("ANTHROPIC_BASE_URL", "?")

    if on_fallback:
        msg = (
            f":warning: **{agent}** switched to local ollama fallback "
            f"(`{fallback_model}`). Primary unreachable: `{primary}`"
        )
    else:
        msg = f":white_check_mark: **{agent}** restored to primary inference: `{primary}`"

    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{mm_url.rstrip('/')}/api/v4/posts",
                headers={"Authorization": f"Bearer {token}"},
                json={"channel_id": channel, "message": msg},
            )
    except Exception as e:
        logger.warning("[claude] fallback MM notification failed: %s", e)


def _mm_base_url() -> str:
    """Get Mattermost base URL from env or channels.yaml."""
    url = os.environ.get("MATTERMOST_BASE_URL", "")
    if url:
        return url
    try:
        import yaml
        from grove.core import paths
        channels_file = paths.agent_dir() / "channels.yaml"
        if channels_file.exists():
            data = yaml.safe_load(channels_file.read_text()) or {}
            return (data.get("mattermost") or {}).get("base_url", "")
    except Exception:
        pass
    return ""


@dataclass
class StreamResult:
    text: str = ""
    session_id: str | None = None
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    num_turns: int = 0
    is_error: bool = False
    errors: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)


def _claude_binary() -> str:
    """Return path to Claude CLI — ClaudeCode.app wrapper on macOS for FDA permissions."""
    app_bin = Path.home() / "Applications" / "ClaudeCode.app" / "Contents" / "MacOS" / "claude-wrapper"
    if app_bin.exists():
        return str(app_bin)
    return "claude"


def _default_model() -> str:
    return os.environ.get("GROVE_DEFAULT_MODEL") or os.environ.get("INNIE_DEFAULT_MODEL", "claude-sonnet-4-6")


async def stream_claude_events(
    prompt: str,
    model: str | None = None,
    system_prompt: str | None = None,
    permission_mode: str = "yolo",
    session_id: str | None = None,
    working_directory: str = ".",
    timeout: float = 1800,
) -> AsyncGenerator[dict, None]:
    """Stream JSONL events from Claude Code CLI."""
    if model is None:
        model = _default_model()
    cmd = [_claude_binary(), "--print", "--output-format", "stream-json", "--verbose"]
    cmd.extend(["--model", model])

    if permission_mode == "yolo":
        cmd.append("--dangerously-skip-permissions")
    elif permission_mode == "plan":
        cmd.extend(["--permission-mode", "plan"])

    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])
    if session_id:
        cmd.extend(["--resume", session_id])

    cmd.append("--")
    cmd.append(prompt)

    env = os.environ.copy()
    anthropic_base, model_override = await _choose_base_url()
    if model_override:
        model = model_override
        # Rebuild cmd with updated model — cmd[...--model was already appended above,
        # but we need to replace it. Easier to rebuild the flag portion.
        for i, arg in enumerate(cmd):
            if arg == "--model" and i + 1 < len(cmd):
                cmd[i + 1] = model
                break
    if anthropic_base:
        env["ANTHROPIC_BASE_URL"] = anthropic_base
    elif "ANTHROPIC_BASE_URL" in env:
        del env["ANTHROPIC_BASE_URL"]
    # Remove nested-session guard so Claude Code can run as a subprocess
    env.pop("CLAUDECODE", None)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=working_directory,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        limit=16 * 1024 * 1024,  # 16MB — default 64KB is too small for claude output
    )

    try:
        async for line in _read_lines(process.stdout, timeout):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                yield data
            except json.JSONDecodeError:
                continue
    except asyncio.TimeoutError:
        process.kill()
        raise
    finally:
        if process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                process.kill()
        # Log stderr so startup/auth errors are visible
        try:
            stderr_bytes = await asyncio.wait_for(process.stderr.read(), timeout=2.0)
            if stderr_bytes:
                logger.warning("[claude stderr] %s", stderr_bytes.decode("utf-8", errors="replace").strip())
        except (asyncio.TimeoutError, Exception):
            pass


async def _read_lines(stream: asyncio.StreamReader, timeout: float) -> AsyncGenerator[str, None]:
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        try:
            line = await asyncio.wait_for(stream.readline(), timeout=min(remaining, 60.0))
            if not line:
                break
            yield line.decode("utf-8", errors="replace")
        except asyncio.TimeoutError:
            if remaining <= 0:
                raise
        except ValueError:
            # Line exceeded StreamReader buffer — skip and continue
            logger.warning("[claude] skipped oversized line from stdout (exceeded buffer limit)")
            continue


async def collect_stream(
    prompt: str,
    model: str | None = None,
    system_prompt: str | None = None,
    permission_mode: str = "yolo",
    session_id: str | None = None,
    working_directory: str = ".",
    timeout: float = 1800,
) -> StreamResult:
    """Run Claude CLI and collect full result."""
    result = StreamResult()

    async for data in stream_claude_events(
        prompt=prompt,
        model=model,
        system_prompt=system_prompt,
        permission_mode=permission_mode,
        session_id=session_id,
        working_directory=working_directory,
        timeout=timeout,
    ):
        event_type = data.get("type")
        result.events.append(data)

        if event_type == "system":
            if data.get("session_id"):
                result.session_id = data["session_id"]

        elif event_type == "assistant":
            message = data.get("message", {})
            for block in message.get("content", []):
                if block.get("type") == "text":
                    result.text += block["text"]

        elif event_type == "result":
            result.session_id = data.get("session_id", result.session_id)
            result.cost_usd = data.get("total_cost_usd", data.get("cost_usd", 0.0))
            result.duration_ms = data.get("duration_ms", 0)
            result.num_turns = data.get("num_turns", 0)
            result.is_error = data.get("is_error", False)
            usage = data.get("usage", {})
            result.input_tokens = usage.get("input_tokens", data.get("input_tokens", 0))
            result.output_tokens = usage.get("output_tokens", data.get("output_tokens", 0))

        elif event_type == "error":
            result.is_error = True
            result.errors.append(data.get("error", "Unknown error"))

    return result


async def graceful_kill(pid: int, timeout: float = 5.0) -> None:
    """SIGTERM -> wait -> SIGKILL."""
    try:
        os.kill(pid, signal.SIGTERM)
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                os.kill(pid, 0)
                await asyncio.sleep(0.5)
            except OSError:
                return
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
