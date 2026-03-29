"""Request/response models for the serve API."""

import os
import time
import uuid
from enum import Enum

from pydantic import BaseModel, Field


def _default_model() -> str:
    return os.environ.get("GROVE_DEFAULT_MODEL") or os.environ.get("INNIE_DEFAULT_MODEL", "claude-sonnet-4-6")


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = Field(default_factory=_default_model)
    messages: list[Message]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    working_directory: str | None = None
    session_id: str | None = None
    permission_mode: str | None = None


class Choice(BaseModel):
    index: int = 0
    message: Message
    finish_reason: str = "stop"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:8]}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: list[Choice]
    usage: Usage = Field(default_factory=Usage)
    session_id: str | None = None


class JobCreateRequest(BaseModel):
    prompt: str = Field(..., description="Task prompt for Claude")
    model: str = Field(default_factory=_default_model)
    working_directory: str | None = Field(default=None, description="Working directory for Claude")
    system_prompt: str | None = None
    include_memory: bool = Field(
        default=False,
        description="Include CONTEXT.md (full memory). Default: USER.md only.",
    )
    session_id: str | None = Field(default=None, description="Resume a previous session")
    permission_mode: str | None = Field(default=None, description="yolo | plan | interactive")
    agent: str | None = Field(default=None, description="Target agent name")
    reply_to: str | None = Field(
        default=None,
        description="Where to POST result: agents://<name>, mattermost://<channel>, https://<url>",
    )


class JobCreateResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str
    poll_url: str
    session_id: str | None = None


class JobStatusResponse(BaseModel):
    id: str
    status: JobStatus
    prompt: str
    model: str
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    result: str | None = None
    error: str | None = None
    duration_seconds: float | None = None
    session_id: str | None = None
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    num_turns: int | None = None


class Job(BaseModel):
    id: str
    status: JobStatus
    prompt: str
    model: str
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    result: str | None = None
    error: str | None = None
    working_directory: str | None = None
    include_memory: bool = False
    session_id: str | None = None
    permission_mode: str | None = None
    agent: str | None = None
    reply_to: str | None = None
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    num_turns: int | None = None
    events: list[dict] = Field(default_factory=list)


class MemoryContextResponse(BaseModel):
    content: str
    last_modified: str | None = None
    size_bytes: int = 0
