"""Heartbeat data collection — Phase 1 of the heartbeat pipeline.

Gathers raw data from session logs, git activity, and current context.
No AI involved — pure data collection.
"""

import json
import subprocess
import time
from pathlib import Path

from innie.core import paths
from innie.core.config import get


def load_heartbeat_state(agent: str | None = None) -> dict:
    state_file = paths.heartbeat_state(agent)
    if state_file.exists():
        return json.loads(state_file.read_text())
    return {"last_run": 0, "processed_sessions": []}


def save_heartbeat_state(state: dict, agent: str | None = None) -> None:
    state_file = paths.heartbeat_state(agent)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2))


def collect_session_data(agent: str | None = None) -> dict:
    """Collect unprocessed session data from the active backend."""
    state = load_heartbeat_state(agent)
    since = state.get("last_run", 0)

    # Discover and use active backends
    from innie.backends.registry import detect_backends

    all_sessions = []
    for backend in detect_backends():
        try:
            sessions = backend.collect_sessions(since)
            all_sessions.extend(sessions)
        except Exception:
            continue

    # Filter out already-processed sessions
    processed = set(state.get("processed_sessions", []))
    new_sessions = [s for s in all_sessions if s.session_id not in processed]

    return {
        "sessions": [
            {
                "id": s.session_id,
                "started": s.started,
                "ended": s.ended,
                "content": s.content[:50000],  # Cap at 50KB per session
                "metadata": s.metadata,
            }
            for s in new_sessions
        ],
        "since": since,
    }


def collect_git_activity(workspace: str | None = None) -> list[dict]:
    """Collect recent git activity across workspace repos."""
    if not get("heartbeat.collect_git", True):
        return []

    workspace_path = Path(workspace) if workspace else Path.home() / "workspace"
    if not workspace_path.exists():
        return []

    activity = []
    for repo_dir in workspace_path.iterdir():
        git_dir = repo_dir / ".git"
        if not git_dir.exists():
            continue

        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "--since=1 hour ago", "--format=%h %s"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().split("\n"):
                    activity.append(
                        {
                            "repo": repo_dir.name,
                            "commit": line,
                        }
                    )
        except Exception:
            continue

    return activity


def collect_current_context(agent: str | None = None) -> str:
    """Snapshot current CONTEXT.md."""
    ctx_file = paths.context_file(agent)
    if ctx_file.exists():
        return ctx_file.read_text()
    return ""


def collect_all(agent: str | None = None) -> dict:
    """Run full Phase 1 collection."""
    return {
        "timestamp": time.time(),
        "sessions": collect_session_data(agent),
        "git_activity": collect_git_activity(),
        "current_context": collect_current_context(agent),
    }
