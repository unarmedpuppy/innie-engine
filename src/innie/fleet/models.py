"""Fleet gateway data models."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class AgentType(str, Enum):
    SERVER = "server"
    CLI = "cli"


class AgentStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentHealth(BaseModel):
    status: AgentStatus = AgentStatus.UNKNOWN
    last_check: str | None = None
    last_success: str | None = None
    response_time_ms: float | None = None
    consecutive_failures: int = 0
    error: str | None = None
    version: str | None = None


class AgentConfig(BaseModel):
    name: str
    description: str = ""
    endpoint: str
    agent_type: AgentType = AgentType.SERVER
    expected_online: bool = True
    tags: list[str] = Field(default_factory=list)


class Agent(BaseModel):
    id: str
    name: str
    description: str = ""
    endpoint: str
    agent_type: AgentType = AgentType.SERVER
    expected_online: bool = True
    tags: list[str] = Field(default_factory=list)
    health: AgentHealth = Field(default_factory=AgentHealth)


class FleetStats(BaseModel):
    total_agents: int = 0
    online_count: int = 0
    offline_count: int = 0
    degraded_count: int = 0
    unknown_count: int = 0
    expected_online_count: int = 0
    unexpected_offline_count: int = 0
    avg_response_time_ms: float = 0.0
    last_updated: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class JobCreateRequest(BaseModel):
    agent_id: str
    prompt: str
    model: str = "claude-sonnet-4-20250514"
    working_directory: str | None = None
    system_prompt: str | None = None
    include_memory: bool = False
    session_id: str | None = None
    permission_mode: str | None = None
    reply_to: str | None = None


class JobResponse(BaseModel):
    job_id: str
    agent_id: str
    status: str
    message: str | None = None
    poll_url: str | None = None


class JobListResponse(BaseModel):
    jobs: list[dict] = Field(default_factory=list)
    total: int = 0
