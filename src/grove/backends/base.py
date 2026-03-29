"""Backend ABC — interface that all AI coding assistant backends implement."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class HookConfig:
    event: str  # SessionStart, PreCompact, Stop, PostToolUse
    command: str
    timeout: int = 10000


@dataclass
class SessionData:
    session_id: str
    started: float
    ended: float | None
    content: str
    metadata: dict


class Backend(ABC):
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def detect(self) -> bool:
        """Return True if this backend is installed on the system."""
        ...

    @abstractmethod
    def get_config_path(self) -> Path:
        """Return path to the backend's config file."""
        ...

    @abstractmethod
    def get_hooks(self, hooks_dir: Path) -> list[HookConfig]:
        """Return hook configs pointing to shim scripts in hooks_dir."""
        ...

    @abstractmethod
    def install_hooks(self, hooks_dir: Path) -> None:
        """Install innie hooks into the backend's config (namespace-safe merge)."""
        ...

    @abstractmethod
    def uninstall_hooks(self) -> None:
        """Remove all innie hooks from the backend's config."""
        ...

    @abstractmethod
    def check_hooks(self) -> dict[str, bool]:
        """Return dict of {event: is_installed} for all expected hooks."""
        ...

    @abstractmethod
    def collect_sessions(self, since: float) -> list[SessionData]:
        """Collect session data since timestamp for heartbeat processing."""
        ...

    @abstractmethod
    def launch_cmd(self, agent: str) -> list[str]:
        """Return the command to launch this backend."""
        ...

    @abstractmethod
    def inject_context(self, agent: str, context: str) -> None:
        """Write context to backend-specific location before launching."""
        ...
