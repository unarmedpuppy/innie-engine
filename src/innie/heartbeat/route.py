"""Phase 3: Deterministic file routing — no AI involved.

Routes extraction results to the correct files in the knowledge base.
AI never writes files directly — this module handles all file I/O.
"""

import json
import re
import time
from datetime import datetime

from innie.core import paths
from innie.core.collector import load_heartbeat_state, save_heartbeat_state
from innie.heartbeat.schema import HeartbeatExtraction


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower().strip())
    return slug.strip("-")[:60]


def route_journal(extraction: HeartbeatExtraction, agent: str | None = None) -> int:
    """Route journal entries to data/journal/YYYY/MM/DD.md."""
    count = 0
    for entry in extraction.journal_entries:
        try:
            dt = datetime.strptime(entry.date, "%Y-%m-%d")
        except ValueError:
            dt = datetime.now()

        jdir = paths.journal_dir(agent) / f"{dt.year}" / f"{dt.month:02d}"
        journal_file = jdir / f"{dt.day:02d}.md"
        journal_file.parent.mkdir(parents=True, exist_ok=True)

        # Append to existing or create new
        if journal_file.exists():
            content = journal_file.read_text()
        else:
            content = f"# {entry.date}\n\n"

        content += f"- **{entry.time}** — {entry.summary}"
        if entry.details:
            content += f"\n  {entry.details}"
        content += "\n"

        journal_file.write_text(content)
        count += 1
    return count


def route_learnings(extraction: HeartbeatExtraction, agent: str | None = None) -> int:
    """Route learnings to data/learnings/{category}/."""
    count = 0
    today = datetime.now().strftime("%Y-%m-%d")
    for learning in extraction.learnings:
        cat_dir = paths.learnings_dir(agent) / learning.category
        cat_dir.mkdir(parents=True, exist_ok=True)

        slug = _slugify(learning.title)
        learning_file = cat_dir / f"{today}-{slug}.md"

        content = f"# {learning.title}\n\n"
        content += f"*Confidence: {learning.confidence} | Learned: {today}*\n\n"
        content += learning.content + "\n"

        learning_file.write_text(content)
        count += 1
    return count


def route_project_updates(extraction: HeartbeatExtraction, agent: str | None = None) -> int:
    """Route project updates to data/projects/{project}/context.md."""
    count = 0
    today = datetime.now().strftime("%Y-%m-%d")
    for update in extraction.project_updates:
        project_dir = paths.projects_dir(agent) / _slugify(update.project)
        project_dir.mkdir(parents=True, exist_ok=True)

        context_file = project_dir / "context.md"
        if context_file.exists():
            content = context_file.read_text()
        else:
            content = f"# {update.project}\n\n*Status: {update.status}*\n\n## Updates\n\n"

        content += f"### {today}\n\n{update.summary}\n\n"
        context_file.write_text(content)
        count += 1
    return count


def route_decisions(extraction: HeartbeatExtraction, agent: str | None = None) -> int:
    """Route decisions to data/projects/{project}/decisions/."""
    count = 0
    today = datetime.now().strftime("%Y-%m-%d")
    for decision in extraction.decisions:
        project_dir = paths.projects_dir(agent) / _slugify(decision.project)
        decisions_dir = project_dir / "decisions"
        decisions_dir.mkdir(parents=True, exist_ok=True)

        slug = _slugify(decision.title)
        decision_file = decisions_dir / f"{today}-{slug}.md"

        content = f"# {decision.title}\n\n"
        content += f"*Date: {today} | Project: {decision.project}*\n\n"
        content += f"## Context\n\n{decision.context}\n\n"
        content += f"## Decision\n\n{decision.decision}\n\n"
        if decision.alternatives:
            content += "## Alternatives Considered\n\n"
            for alt in decision.alternatives:
                content += f"- {alt}\n"
            content += "\n"

        decision_file.write_text(content)
        count += 1
    return count


def route_open_items(extraction: HeartbeatExtraction, agent: str | None = None) -> int:
    """Update CONTEXT.md open items based on extraction."""
    ctx_file = paths.context_file(agent)
    if not ctx_file.exists():
        return 0

    content = ctx_file.read_text()
    changes = 0

    for item in extraction.open_items:
        if item.action == "add":
            # Add to Open Items section
            marker = "## Open Items"
            if marker in content:
                idx = content.index(marker) + len(marker)
                # Find next line after header
                next_nl = content.index("\n", idx)
                content = content[: next_nl + 1] + f"\n- {item.text}" + content[next_nl:]
                changes += 1
        elif item.action == "complete":
            # Mark as done (strikethrough) — only count if actually found
            new_content = content.replace(f"- {item.text}", f"- ~~{item.text}~~")
            if new_content != content:
                content = new_content
                changes += 1
        elif item.action == "remove":
            new_content = content.replace(f"- {item.text}\n", "")
            if new_content != content:
                content = new_content
                changes += 1

    if changes:
        # Update timestamp
        content = re.sub(
            r"\*Last updated:.*?\*",
            f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
            content,
        )
        ctx_file.write_text(content)

    return changes


def route_metrics(extraction: HeartbeatExtraction, agent: str | None = None) -> None:
    """Append daily metrics to data/metrics/daily.jsonl."""
    metrics_dir = paths.metrics_dir(agent)
    metrics_dir.mkdir(parents=True, exist_ok=True)
    metrics_file = metrics_dir / "daily.jsonl"

    entry = {
        "timestamp": time.time(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "journal_entries": len(extraction.journal_entries),
        "learnings": len(extraction.learnings),
        "decisions": len(extraction.decisions),
        "sessions_processed": extraction.processed_sessions.count,
    }

    with open(metrics_file, "a") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def route_all(extraction: HeartbeatExtraction, agent: str | None = None) -> dict[str, int]:
    """Run all routing for a heartbeat extraction. Returns counts per route."""
    results = {
        "journal": route_journal(extraction, agent),
        "learnings": route_learnings(extraction, agent),
        "projects": route_project_updates(extraction, agent),
        "decisions": route_decisions(extraction, agent),
        "open_items": route_open_items(extraction, agent),
    }

    route_metrics(extraction, agent)

    # Update heartbeat state
    state = load_heartbeat_state(agent)
    state["last_run"] = time.time()
    processed = state.get("processed_sessions", [])
    processed.extend(extraction.processed_sessions.ids)
    # Keep only last 1000 session IDs
    state["processed_sessions"] = processed[-1000:]
    save_heartbeat_state(state, agent)

    return results
