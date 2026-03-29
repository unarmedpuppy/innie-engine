"""Agent profile dataclass and load/save."""

from dataclasses import dataclass, field
from typing import Any

import yaml

from grove.core import paths


@dataclass
class MemoryConfig:
    injection: str = "full"  # full | summary | minimal
    max_context_lines: int = 200


@dataclass
class GuardConfig:
    engine: str = ""  # dcg | "" (empty = no guard)
    config: str = ""  # path to config file (e.g. dcg-config.toml), relative to agent dir
    trust_level: str = "low"  # low | medium | high


@dataclass
class Profile:
    name: str
    role: str = "Work Second Brain"
    permissions: str = "interactive"
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    guard: GuardConfig = field(default_factory=GuardConfig)
    backend_config: dict[str, Any] = field(default_factory=dict)

    # Loaded markdown content (populated by load_profile)
    soul: str | None = None
    context: str | None = None
    heartbeat_doc: str | None = None


def load_profile(name: str | None = None) -> Profile:
    name = name or paths.active_agent()
    profile_path = paths.profile_file(name)

    if not profile_path.exists():
        raise ValueError(f"Agent not found: {name} (looked in {profile_path.parent})")

    with open(profile_path) as f:
        cfg = yaml.safe_load(f) or {}

    mem = cfg.get("memory", {})
    memory_config = MemoryConfig(
        injection=mem.get("injection", "full"),
        max_context_lines=mem.get("max_context_lines", 200),
    )

    guard_cfg = cfg.get("guard", {})
    guard_config = GuardConfig(
        engine=guard_cfg.get("engine", ""),
        config=guard_cfg.get("config", ""),
        trust_level=guard_cfg.get("trust_level", "low"),
    )

    profile = Profile(
        name=cfg.get("name", name),
        role=cfg.get("role", "Work Second Brain"),
        permissions=cfg.get("permissions", "interactive"),
        memory=memory_config,
        guard=guard_config,
        backend_config=cfg.get("claude-code", {}),
    )

    # Load markdown files
    agent = paths.agent_dir(name)
    for filename, attr in [
        ("SOUL.md", "soul"),
        ("CONTEXT.md", "context"),
        ("HEARTBEAT.md", "heartbeat_doc"),
    ]:
        fpath = agent / filename
        if fpath.exists():
            setattr(profile, attr, fpath.read_text().strip())

    return profile


def save_profile(profile: Profile, name: str | None = None) -> None:
    name = name or profile.name
    profile_path = paths.profile_file(name)
    profile_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "name": profile.name,
        "role": profile.role,
        "permissions": profile.permissions,
        "memory": {
            "injection": profile.memory.injection,
            "max_context_lines": profile.memory.max_context_lines,
        },
    }
    if profile.guard.engine:
        data["guard"] = {
            "engine": profile.guard.engine,
            "config": profile.guard.config,
            "trust_level": profile.guard.trust_level,
        }
    if profile.backend_config:
        data["claude-code"] = profile.backend_config

    with open(profile_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def list_agents() -> list[str]:
    adir = paths.agents_dir()
    if not adir.exists():
        return []
    return sorted(d.name for d in adir.iterdir() if d.is_dir() and (d / "profile.yaml").exists())
