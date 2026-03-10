"""Claude Code CLI subprocess management — streaming and non-streaming."""

import asyncio
import json
import logging
import os
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


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


async def stream_claude_events(
    prompt: str,
    model: str = "claude-sonnet-4-20250514",
    system_prompt: str | None = None,
    permission_mode: str = "yolo",
    session_id: str | None = None,
    working_directory: str = ".",
    timeout: float = 1800,
) -> AsyncGenerator[dict, None]:
    """Stream JSONL events from Claude Code CLI."""
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
    anthropic_base = os.environ.get("ANTHROPIC_BASE_URL")
    if anthropic_base:
        env["ANTHROPIC_BASE_URL"] = anthropic_base

    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=working_directory,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
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


async def collect_stream(
    prompt: str,
    model: str = "claude-sonnet-4-20250514",
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
