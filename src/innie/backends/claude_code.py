"""Claude Code backend adapter.

Handles hook installation into ~/.claude/settings.json using safe
namespace-based merge (only touches entries containing 'innie').
"""

import json
import shutil
from pathlib import Path

from innie.backends.base import Backend, HookConfig, SessionData


class ClaudeCodeBackend(Backend):
    def name(self) -> str:
        return "claude-code"

    def detect(self) -> bool:
        return shutil.which("claude") is not None

    def get_config_path(self) -> Path:
        return Path.home() / ".claude" / "settings.json"

    def get_hooks(self, hooks_dir: Path) -> list[HookConfig]:
        return [
            HookConfig(
                event="SessionStart",
                command=f"bash {hooks_dir}/session-start.sh",
                timeout=10000,
            ),
            HookConfig(
                event="PreCompact",
                command=f"bash {hooks_dir}/pre-compact.sh",
                timeout=5000,
            ),
            HookConfig(
                event="Stop",
                command=f"bash {hooks_dir}/session-end.sh",
                timeout=10000,
            ),
            HookConfig(
                event="PostToolUse",
                command=f"bash {hooks_dir}/observability.sh",
                timeout=1000,
            ),
            HookConfig(
                event="PreToolUse",
                command=f"bash {hooks_dir}/dcg-guard.sh",
                timeout=5000,
            ),
        ]

    def _is_innie_entry(self, entry: dict) -> bool:
        """Check if a hook entry belongs to innie (works with both old and new formats)."""
        # New format: matcher + hooks array
        for h in entry.get("hooks", []):
            if "innie" in h.get("command", ""):
                return True
        # Old format: bare command at top level
        if "innie" in entry.get("command", ""):
            return True
        return False

    def install_hooks(self, hooks_dir: Path) -> None:
        config_path = self.get_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing config
        if config_path.exists():
            # Backup
            backup = config_path.with_suffix(".innie-backup")
            shutil.copy2(config_path, backup)
            with open(config_path) as f:
                config = json.load(f)
        else:
            config = {}

        hooks = config.setdefault("hooks", {})
        new_hooks = self.get_hooks(hooks_dir)

        for hook in new_hooks:
            event_hooks = hooks.get(hook.event, [])

            # Remove existing innie entries (namespace-based)
            event_hooks = [h for h in event_hooks if not self._is_innie_entry(h)]

            # Append new innie hook in the new matcher + hooks format
            cmd_entry: dict = {"type": "command", "command": hook.command}
            if hook.timeout != 10000:
                cmd_entry["timeout"] = hook.timeout
            event_hooks.append({"matcher": "*", "hooks": [cmd_entry]})

            hooks[hook.event] = event_hooks

        config["hooks"] = hooks

        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
            f.write("\n")

    def uninstall_hooks(self) -> None:
        config_path = self.get_config_path()
        if not config_path.exists():
            return

        with open(config_path) as f:
            config = json.load(f)

        hooks = config.get("hooks", {})
        for event in list(hooks.keys()):
            hooks[event] = [h for h in hooks[event] if not self._is_innie_entry(h)]
            if not hooks[event]:
                del hooks[event]

        config["hooks"] = hooks

        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
            f.write("\n")

    def check_hooks(self) -> dict[str, bool]:
        config_path = self.get_config_path()
        if not config_path.exists():
            return {e: False for e in ["SessionStart", "PreCompact", "Stop", "PostToolUse"]}

        with open(config_path) as f:
            config = json.load(f)

        hooks = config.get("hooks", {})
        result = {}
        for event in ["SessionStart", "PreCompact", "Stop", "PostToolUse", "PreToolUse"]:
            event_hooks = hooks.get(event, [])
            result[event] = any(self._is_innie_entry(h) for h in event_hooks)
        return result

    def collect_sessions(self, since: float) -> list[SessionData]:
        """Parse JSONL session files from ~/.claude/projects/."""
        sessions: list[SessionData] = []
        projects_dir = Path.home() / ".claude" / "projects"
        if not projects_dir.exists():
            return sessions

        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            for jsonl_file in project_dir.glob("*.jsonl"):
                try:
                    mtime = jsonl_file.stat().st_mtime
                    if mtime < since:
                        continue
                    content = jsonl_file.read_text(encoding="utf-8", errors="ignore")
                    # Extract basic metadata from content
                    lines = content.strip().split("\n")
                    if not lines:
                        continue

                    # Parse first and last JSON lines for timestamps
                    first = json.loads(lines[0]) if lines else {}
                    last = json.loads(lines[-1]) if lines else {}

                    started = first.get("timestamp", mtime)
                    ended = last.get("timestamp", mtime)

                    # Build readable transcript from messages
                    messages: list[str] = []
                    for line in lines:
                        try:
                            entry = json.loads(line)
                            role = entry.get("role", "")
                            msg = entry.get("message", {})
                            if isinstance(msg, dict):
                                text = msg.get("content", "")
                                if isinstance(text, str) and text.strip():
                                    messages.append(f"[{role}] {text[:500]}")
                        except json.JSONDecodeError:
                            continue

                    if messages:
                        sessions.append(
                            SessionData(
                                session_id=jsonl_file.stem,
                                started=started,
                                ended=ended,
                                content="\n".join(messages),
                                metadata={
                                    "project": project_dir.name,
                                    "file": str(jsonl_file),
                                    "message_count": len(messages),
                                },
                            )
                        )
                except Exception:
                    continue

        return sessions
