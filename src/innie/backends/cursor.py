"""Cursor backend adapter (stub)."""

from pathlib import Path

from innie.backends.base import Backend, HookConfig, SessionData


class CursorBackend(Backend):
    def name(self) -> str:
        return "cursor"

    def detect(self) -> bool:
        return (Path.home() / ".cursor").exists()

    def get_config_path(self) -> Path:
        return Path.home() / ".cursor" / "hooks.json"

    def get_hooks(self, hooks_dir: Path) -> list[HookConfig]:
        return []  # TODO

    def install_hooks(self, hooks_dir: Path) -> None:
        pass  # TODO

    def uninstall_hooks(self) -> None:
        pass  # TODO

    def check_hooks(self) -> dict[str, bool]:
        return {}  # TODO

    def collect_sessions(self, since: float) -> list[SessionData]:
        return []  # TODO
