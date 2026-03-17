"""Claude Code backend adapter.

Handles hook installation into ~/.claude/settings.json using safe
namespace-based merge (only touches entries containing 'innie').
"""

import json
import logging
import shutil
from pathlib import Path

from innie.backends.base import Backend, HookConfig, SessionData

logger = logging.getLogger(__name__)


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
            HookConfig(
                event="UserPromptSubmit",
                command=f"bash {hooks_dir}/prompt-submit.sh",
                timeout=3000,
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

        # Disable attribution header — it invalidates the KV cache and causes
        # ~90% slower inference with local models. Must be set in settings.json;
        # shell exports do not work. https://unsloth.ai/docs/basics/claude-code
        env = config.setdefault("env", {})
        env.setdefault("CLAUDE_CODE_ATTRIBUTION_HEADER", "0")

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

    def launch_cmd(self, agent: str) -> list[str]:
        from innie.core import paths

        ctx_file = paths.agent_dir(agent) / "launch-context.md"
        if ctx_file.exists():
            return ["claude", "--append-system-prompt", str(ctx_file)]
        return ["claude"]

    def inject_context(self, agent: str, context: str) -> None:
        from innie.core import paths

        ctx_file = paths.agent_dir(agent) / "launch-context.md"
        ctx_file.write_text(context)

    def _parse_timestamp(self, ts, fallback: float) -> float:
        """Normalize a JSONL timestamp (ISO string or Unix float) to a Unix float."""
        if ts is None:
            return fallback
        if isinstance(ts, (int, float)):
            return float(ts)
        try:
            from datetime import datetime
            return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
        except Exception:
            return fallback

    def _extract_content_text(self, content) -> str:
        """Extract readable text from a message content field (str or list of blocks)."""
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            if btype == "text":
                text = block.get("text", "").strip()
                # Skip system injections and XML-wrapped blocks
                if text and not text.startswith("<"):
                    parts.append(text)
            elif btype == "tool_use":
                parts.append(f"[tool:{block.get('name', '')}]")
            elif btype == "tool_result":
                rc = block.get("content", "")
                if isinstance(rc, str) and rc.strip():
                    parts.append(f"[result:{rc[:200]}]")
                elif isinstance(rc, list):
                    for item in rc:
                        if isinstance(item, dict) and item.get("type") == "text":
                            t = item.get("text", "").strip()
                            if t:
                                parts.append(f"[result:{t[:200]}]")
        return " ".join(parts)

    def _load_todos(self, session_id: str) -> list[dict] | None:
        """Load todo state for a session from ~/.claude/todos/{session_id}-agent-{session_id}.json.

        Returns list of {content, status} dicts, or None if no todo file exists / file is empty.
        Status values: 'completed' | 'in_progress' | 'pending'
        """
        todo_path = Path.home() / ".claude" / "todos" / f"{session_id}-agent-{session_id}.json"
        if not todo_path.exists():
            return None
        try:
            data = json.loads(todo_path.read_text(encoding="utf-8", errors="ignore"))
            if not isinstance(data, list) or not data:
                return None
            return [{"content": t.get("content", ""), "status": t.get("status", "")} for t in data]
        except Exception as e:
            logger.debug("Failed to load todos for %s: %s", todo_path, e)
            return None

    def _session_dirs(self) -> list[tuple[Path, str]]:
        """Return (dir, label) pairs to scan for JSONL session files.

        Always includes ~/.claude/projects/ (one level deep, each subdir is a project).
        Also includes any flat dirs listed in backends.claude_code.additional_session_dirs
        config — these are scanned directly for *.jsonl (no subdir level).

        Default additional dir: ~/.openclaw/agents/main/sessions/ if it exists.
        """
        from innie.core.config import get

        results: list[tuple[Path, str]] = []

        # Primary: ~/.claude/projects/<project>/*.jsonl
        projects_dir = Path.home() / ".claude" / "projects"
        if projects_dir.exists():
            for d in projects_dir.iterdir():
                if d.is_dir():
                    results.append((d, d.name))

        # Additional flat dirs (e.g. openclaw gateway sessions)
        defaults = ["~/.openclaw/agents/main/sessions"]
        extra = get("backends.claude_code.additional_session_dirs", defaults)
        for raw in extra:
            p = Path(raw).expanduser()
            if p.is_dir():
                results.append((p, p.name))

        return results

    def collect_sessions(self, since: float) -> list[SessionData]:
        """Parse JSONL session files from ~/.claude/projects/ and additional dirs."""
        sessions: list[SessionData] = []

        for session_dir, label in self._session_dirs():
            for jsonl_file in session_dir.glob("*.jsonl"):
                try:
                    mtime = jsonl_file.stat().st_mtime
                    if mtime < since:
                        continue
                    content = jsonl_file.read_text(encoding="utf-8", errors="ignore")
                    lines = [ln for ln in content.strip().split("\n") if ln.strip()]
                    if not lines:
                        continue

                    first = json.loads(lines[0])
                    last = json.loads(lines[-1])

                    started = self._parse_timestamp(first.get("timestamp"), mtime)
                    ended = self._parse_timestamp(last.get("timestamp"), mtime)

                    # Build readable transcript from messages.
                    # Two JSONL formats:
                    # - Claude Code: top-level "type" is "user"|"assistant", content in entry["message"]["content"]
                    # - OpenClaw gateway: top-level "type" is "message", role in entry["message"]["role"], content in entry["message"]["content"]
                    messages: list[str] = []
                    for line in lines:
                        try:
                            entry = json.loads(line)
                            entry_type = entry.get("type", "")
                            msg = entry.get("message", {})
                            if not isinstance(msg, dict):
                                continue
                            if entry_type in ("user", "assistant"):
                                role = entry_type
                            elif entry_type == "message":
                                role = msg.get("role", "")
                            else:
                                continue
                            if role not in ("user", "assistant"):
                                continue
                            text = self._extract_content_text(msg.get("content", ""))
                            if text.strip():
                                messages.append(f"[{role}] {text[:500]}")
                        except json.JSONDecodeError:
                            continue

                    if messages:
                        metadata: dict = {
                            "source": label,
                            "file": str(jsonl_file),
                            "message_count": len(messages),
                        }
                        todos = self._load_todos(jsonl_file.stem)
                        if todos:
                            metadata["todos"] = todos
                        sessions.append(
                            SessionData(
                                session_id=jsonl_file.stem,
                                started=started,
                                ended=ended,
                                content="\n".join(messages),
                                metadata=metadata,
                            )
                        )
                except Exception as e:
                    logger.warning("Failed to parse session file %s: %s", jsonl_file, e)
                    continue

        return sessions
