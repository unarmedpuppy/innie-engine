"""Path resolution for innie-engine.

All paths derive from two env vars:
  INNIE_HOME  — root of all innie data (default: ~/.innie)
  INNIE_AGENT — active agent name (default: from config.toml)
"""

import os
from pathlib import Path


def home() -> Path:
    return Path(os.environ.get("INNIE_HOME", Path.home() / ".innie"))


def config_file() -> Path:
    return home() / "config.toml"


def user_file() -> Path:
    return home() / "user.md"


def agents_dir() -> Path:
    return home() / "agents"


def agent_dir(name: str | None = None) -> Path:
    name = name or active_agent()
    return agents_dir() / name


def active_agent() -> str:
    if agent := os.environ.get("INNIE_AGENT"):
        return agent
    from grove.core.config import load_config

    cfg = load_config()
    return cfg.get("defaults", {}).get("agent", "innie")


# Agent sub-paths


def profile_file(agent: str | None = None) -> Path:
    return agent_dir(agent) / "profile.yaml"


def soul_file(agent: str | None = None) -> Path:
    return agent_dir(agent) / "SOUL.md"


def context_file(agent: str | None = None) -> Path:
    return agent_dir(agent) / "CONTEXT.md"


def heartbeat_instructions(agent: str | None = None) -> Path:
    return agent_dir(agent) / "HEARTBEAT.md"


# World directory — synced across machines via Gitea


def world_dir() -> Path:
    """Root of the synced world directory. Configured via defaults.world in config.toml."""
    from grove.core.config import load_config
    cfg = load_config()
    configured = cfg.get("defaults", {}).get("world")
    if configured:
        return Path(configured).expanduser()
    return home() / "world"  # fallback if not configured


# data/ — permanent knowledge base (git-trackable)


def data_dir(agent: str | None = None) -> Path:
    """Return the data directory for an agent.

    If defaults.world is configured in config.toml, data lives in the world dir
    (synced across machines). Otherwise falls back to ~/.innie/agents/<name>/data/.
    """
    from grove.core.config import load_config
    cfg = load_config()
    if cfg.get("defaults", {}).get("world"):
        return world_dir() / "agents" / (agent or active_agent()) / "data"
    return agent_dir(agent) / "data"


def project_dir(project: str, agent: str | None = None) -> Path:
    return data_dir(agent) / "projects" / project


def project_now(project: str, agent: str | None = None) -> Path:
    return project_dir(project, agent) / "now.md"


def project_log(project: str, agent: str | None = None) -> Path:
    return project_dir(project, agent) / "log.md"


def project_tasks(project: str, agent: str | None = None) -> Path:
    return project_dir(project, agent) / "tasks.md"


def project_key(project: str, agent: str | None = None) -> Path:
    return project_dir(project, agent) / "key.md"


def journal_dir(agent: str | None = None) -> Path:
    return data_dir(agent) / "journal"


def projects_dir(agent: str | None = None) -> Path:
    return data_dir(agent) / "projects"


def learnings_dir(agent: str | None = None) -> Path:
    return data_dir(agent) / "learnings"


def people_dir(agent: str | None = None) -> Path:
    return data_dir(agent) / "people"


def meetings_dir(agent: str | None = None) -> Path:
    return data_dir(agent) / "meetings"


def inbox_dir(agent: str | None = None) -> Path:
    return data_dir(agent) / "inbox"


def metrics_dir(agent: str | None = None) -> Path:
    return data_dir(agent) / "metrics"


# state/ — operational state (local only, rebuildable)


def state_dir(agent: str | None = None) -> Path:
    return agent_dir(agent) / "state"


def sessions_dir(agent: str | None = None) -> Path:
    return state_dir(agent) / "sessions"


def trace_dir(agent: str | None = None) -> Path:
    return state_dir(agent) / "trace"


def index_dir(agent: str | None = None) -> Path:
    return state_dir(agent) / ".index"


def index_db(agent: str | None = None) -> Path:
    return index_dir(agent) / "memory.db"


def heartbeat_state(agent: str | None = None) -> Path:
    return state_dir(agent) / "heartbeat-state.json"


def skills_dir(agent: str | None = None) -> Path:
    return agent_dir(agent) / "skills"


def shared_skills_dir() -> Path:
    """Canonical shared skills directory for all agents."""
    return home() / "skills"


def env_file(agent: str | None = None) -> Path:
    """Agent-specific secrets. ~/.innie/agents/<name>/.env"""
    return agent_dir(agent) / ".env"


def shared_env_file() -> Path:
    """Shared secrets for all agents. ~/.innie/.env"""
    return home() / ".env"


def memory_ops_file(agent: str | None = None) -> Path:
    """Audit trail for live in-session memory ops. data/memory-ops.jsonl"""
    return data_dir(agent) / "memory-ops.jsonl"


def retrieval_log_file(agent: str | None = None) -> Path:
    """Retrieval event log for memory quality tracking. state/retrieval-log.jsonl"""
    return state_dir(agent) / "retrieval-log.jsonl"


def topic_catalog_file(agent: str | None = None) -> Path:
    """Topic catalog for session-start discovery signal. state/topic-catalog.json"""
    return state_dir(agent) / "topic-catalog.json"


def hook_cache_file(session_id: str, agent: str | None = None) -> Path:
    """Per-session dedup cache for prompt-submit hook. state/hook-cache-<id>.txt"""
    safe_id = session_id[:24].replace("/", "_").replace(".", "_")
    return state_dir(agent) / f"hook-cache-{safe_id}.txt"
