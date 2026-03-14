"""Heartbeat data collection — Phase 1 of the heartbeat pipeline.

Gathers raw data from session logs, git activity, and current context.
No AI involved — pure data collection.
"""

import json
import re
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


def collect_session_data(agent: str | None = None, since_override: float | None = None) -> dict:
    """Collect unprocessed session data from the active backend."""
    state = load_heartbeat_state(agent)
    since = since_override if since_override is not None else state.get("last_run", 0)

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
    # State format: {"prefix": {"full_uuid": timestamp, ...}, ...}
    ps = state.get("processed_sessions", {})
    if isinstance(ps, dict):
        processed = set()
        for prefix_dict in ps.values():
            if isinstance(prefix_dict, dict):
                processed.update(prefix_dict.keys())
    else:
        processed = set(ps)
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


def collect_existing_knowledge(agent: str | None = None, sessions: list[dict] | None = None) -> list[dict]:
    """Return relevant existing learnings/decisions for contradiction detection.

    Tries hybrid search using session content as the query.
    Falls back to the 20 most recently modified files if search unavailable.
    Capped at ~6000 chars total to stay within token budget.
    """
    from innie.core import paths as _paths

    data_dir = _paths.data_dir(agent)
    if not data_dir.exists():
        return []

    # Build query string from session content
    query_parts: list[str] = []
    for s in (sessions or [])[:5]:
        query_parts.append(s.get("content", "")[:300])
    query = " ".join(query_parts)[:1500]

    results: list[dict] = []

    # Try semantic/hybrid search first
    if query:
        try:
            from innie.core.search import open_db, search_hybrid
            db_path = _paths.index_db(agent)
            if db_path.exists():
                conn = open_db(db_path)
                hits = search_hybrid(conn, query, limit=20)
                conn.close()
                seen_files: set[str] = set()
                for hit in hits:
                    fp = Path(hit["file_path"])
                    if str(fp) in seen_files:
                        continue
                    seen_files.add(str(fp))
                    try:
                        rel = str(fp.relative_to(data_dir))
                    except ValueError:
                        continue
                    # Skip non-learnings/decisions
                    if not (rel.startswith("learnings/") or rel.startswith("decisions/")):
                        continue
                    results.append({
                        "file": rel,
                        "summary": hit["content"][:300].strip(),
                    })
        except Exception:
            pass

    # Fallback: most recently modified files from learnings/ and decisions/
    if not results:
        candidates: list[Path] = []
        for subdir in ("learnings", "decisions"):
            d = data_dir / subdir
            if d.exists():
                candidates.extend(d.rglob("*.md"))
        candidates.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        for fp in candidates[:20]:
            try:
                rel = str(fp.relative_to(data_dir))
                text = fp.read_text(encoding="utf-8", errors="ignore")
                # Skip frontmatter
                body = re.sub(r"^---\n.*?\n---\n?", "", text, flags=re.DOTALL).strip()
                results.append({"file": rel, "summary": body[:300]})
            except Exception:
                continue

    # Apply total char budget
    budget = 6000
    trimmed: list[dict] = []
    used = 0
    for r in results:
        entry_len = len(r["file"]) + len(r["summary"]) + 10
        if used + entry_len > budget:
            break
        trimmed.append(r)
        used += entry_len

    return trimmed


def collect_inbox(agent: str | None = None) -> list[dict]:
    """Read all unprocessed messages from data/inbox/.

    Returns list of {filename, from_agent, content} dicts.
    Files remain in place — archiving happens in route_inbox_archive() after extraction.
    """
    inbox_dir = paths.inbox_dir(agent)
    if not inbox_dir.exists():
        return []

    messages = []
    for f in sorted(inbox_dir.glob("*.md")):
        try:
            content = f.read_text(encoding="utf-8", errors="ignore").strip()
            if not content:
                continue
            # Try to extract sender from filename: YYYY-MM-DD-from-{agent}-{slug}.md
            from_agent = "unknown"
            parts = f.stem.split("-from-")
            if len(parts) == 2:
                from_agent = parts[1].split("-")[0]
            messages.append({
                "filename": f.name,
                "from_agent": from_agent,
                "content": content,
            })
        except Exception:
            continue

    return messages


def collect_live_memory_ops(agent: str | None = None, since: float = 0) -> list[dict]:
    """Read memory-ops.jsonl entries since last heartbeat run.

    Returns list of op dicts so the extractor knows what the agent already did
    this session and can avoid creating duplicates.
    """
    ops_file = paths.memory_ops_file(agent)
    if not ops_file.exists():
        return []

    entries = []
    for line in ops_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if entry.get("ts", 0) >= since:
                entries.append(entry)
        except json.JSONDecodeError:
            continue
    return entries


def collect_all(agent: str | None = None, since_override: float | None = None) -> dict:
    """Run full Phase 1 collection."""
    state = load_heartbeat_state(agent)
    last_run = state.get("last_run", 0)

    session_data = collect_session_data(agent, since_override=since_override)
    return {
        "timestamp": time.time(),
        "sessions": session_data,
        "git_activity": collect_git_activity(),
        "current_context": collect_current_context(agent),
        "existing_knowledge": collect_existing_knowledge(agent, session_data.get("sessions", [])),
        "inbox_messages": collect_inbox(agent),
        "live_memory_ops": collect_live_memory_ops(agent, since=last_run),
    }
