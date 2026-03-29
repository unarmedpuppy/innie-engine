"""OpenCode backend adapter."""

import json
import logging
import sqlite3
from pathlib import Path

from grove.backends.base import Backend, HookConfig, SessionData

logger = logging.getLogger(__name__)


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

    def launch_cmd(self, agent: str) -> list[str]:
        return ["opencode"]

    def inject_context(self, agent: str, context: str) -> None:
        custom_dir = Path.home() / ".config" / "opencode" / "custom"
        custom_dir.mkdir(parents=True, exist_ok=True)
        (custom_dir / f"{agent}-context.md").write_text(context)

    def collect_sessions(self, since: float) -> list[SessionData]:
        """Query OpenCode SQLite database for sessions since timestamp."""
        sessions: list[SessionData] = []
        db_path = Path.home() / ".local" / "share" / "opencode" / "db.sqlite"
        if not db_path.exists():
            return sessions

        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row

            rows = conn.execute(
                "SELECT id, time_updated FROM session WHERE time_updated > ? ORDER BY time_updated",
                (since * 1000,),  # OpenCode stores ms timestamps
            ).fetchall()

            for row in rows:
                session_id = row["id"]
                time_updated = row["time_updated"] / 1000.0

                # Collect text parts from part table
                parts = conn.execute(
                    "SELECT data FROM part WHERE session_id = ? AND json_extract(data, '$.type') = 'text'",
                    (session_id,),
                ).fetchall()

                messages: list[str] = []
                for part in parts:
                    try:
                        data = json.loads(part["data"])
                        text = data.get("text", "")
                        if text.strip():
                            messages.append(text[:500])
                    except (json.JSONDecodeError, KeyError):
                        continue

                if messages:
                    sessions.append(
                        SessionData(
                            session_id=f"opencode-{session_id}",
                            started=since,
                            ended=time_updated,
                            content="\n".join(messages),
                            metadata={"backend": "opencode"},
                        )
                    )

            conn.close()
        except Exception as e:
            logger.warning("OpenCode SQLite query failed at %s: %s", db_path, e)

        return sessions
