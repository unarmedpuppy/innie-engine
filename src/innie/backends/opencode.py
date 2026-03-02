"""OpenCode backend adapter (stub)."""

from pathlib import Path

from innie.backends.base import Backend, HookConfig, SessionData


class OpenCodeBackend(Backend):
    def name(self) -> str:
        return "opencode"

    def detect(self) -> bool:
        return (Path.home() / ".config" / "opencode").exists()

    def get_config_path(self) -> Path:
        return Path.home() / ".config" / "opencode" / "plugins"

    def get_hooks(self, hooks_dir: Path) -> list[HookConfig]:
        return []  # TODO: OpenCode plugin mechanism

    def install_hooks(self, hooks_dir: Path) -> None:
        pass  # TODO

    def uninstall_hooks(self) -> None:
        pass  # TODO

    def check_hooks(self) -> dict[str, bool]:
        return {}  # TODO

    def collect_sessions(self, since: float) -> list[SessionData]:
        return []  # TODO: Query OpenCode SQLite database
