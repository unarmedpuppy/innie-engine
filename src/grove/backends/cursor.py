"""Cursor backend adapter.

NOTE: collect_sessions() is not yet implemented — this backend is detected
but returns no sessions. Hook installation is also not implemented (Cursor
does not have a public hook mechanism equivalent to Claude Code).
"""

from pathlib import Path

from grove.backends.base import Backend, HookConfig, SessionData


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

    def launch_cmd(self, agent: str) -> list[str]:
        return ["cursor", "."]

    def inject_context(self, agent: str, context: str) -> None:
        import os

        rules_dir = Path(os.getcwd()) / ".cursor" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / f"{agent}-context.mdc").write_text(context)

    def collect_sessions(self, since: float) -> list[SessionData]:
        return []  # TODO
