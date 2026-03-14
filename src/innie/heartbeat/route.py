"""Phase 3: Deterministic file routing — no AI involved.

Routes extraction results to the correct files in the knowledge base.
AI never writes files directly — this module handles all file I/O.

All routed files include YAML frontmatter for Obsidian compatibility
and wikilinks to related entries (projects, people, decisions).
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


def _frontmatter(**fields) -> str:
    """Build YAML frontmatter block."""
    lines = ["---"]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, list):
            if value:
                formatted = ", ".join(str(v) for v in value)
                lines.append(f"{key}: [{formatted}]")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def _wikilink(kind: str, name: str) -> str:
    """Build an Obsidian wikilink. e.g. [[projects/my-app/context|my-app]]"""
    slug = _slugify(name)
    if kind == "project":
        return f"[[projects/{slug}/context|{name}]]"
    elif kind == "person":
        return f"[[people/{slug}|{name}]]"
    elif kind == "decision":
        return f"[[decisions/{slug}|{name}]]"
    return f"[[{slug}|{name}]]"


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
            content = _frontmatter(
                date=entry.date,
                type="journal",
                tags=["journal"],
            )
            content += f"# {entry.date}\n\n"

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

        # Skip if a live-stored file with matching slug already exists in this category
        existing = list(cat_dir.glob(f"*-{slug}.md"))
        live_exists = any(
            "source: live" in f.read_text(encoding="utf-8", errors="ignore")
            for f in existing
        )
        if live_exists:
            continue

        learning_file = cat_dir / f"{today}-{slug}.md"
        content = _frontmatter(
            date=today,
            type="learning",
            category=learning.category,
            confidence=learning.confidence,
            tags=["learning", learning.category],
        )
        content += f"# {learning.title}\n\n"
        content += learning.content + "\n"

        learning_file.write_text(content)
        count += 1
    return count


def route_project_updates(extraction: HeartbeatExtraction, agent: str | None = None) -> int:
    """Route project updates to data/projects/{project}/context.md."""
    count = 0
    today = datetime.now().strftime("%Y-%m-%d")
    for update in extraction.project_updates:
        project_slug = _slugify(update.project)
        project_dir = paths.projects_dir(agent) / project_slug
        project_dir.mkdir(parents=True, exist_ok=True)

        context_file = project_dir / "context.md"
        if context_file.exists():
            content = context_file.read_text()
        else:
            content = _frontmatter(
                date=today,
                type="project",
                status=update.status,
                tags=["project", project_slug],
            )
            content += f"# {update.project}\n\n## Updates\n\n"

        content += f"### {today}\n\n{update.summary}\n\n"
        context_file.write_text(content)
        count += 1
    return count


def route_decisions(extraction: HeartbeatExtraction, agent: str | None = None) -> int:
    """Route decisions to data/projects/{project}/decisions/."""
    count = 0
    today = datetime.now().strftime("%Y-%m-%d")
    for decision in extraction.decisions:
        project_slug = _slugify(decision.project)
        project_dir = paths.projects_dir(agent) / project_slug
        decisions_dir = project_dir / "decisions"
        decisions_dir.mkdir(parents=True, exist_ok=True)

        slug = _slugify(decision.title)
        decision_file = decisions_dir / f"{today}-{slug}.md"

        content = _frontmatter(
            date=today,
            type="decision",
            project=decision.project,
            tags=["decision", project_slug],
        )
        content += f"# {decision.title}\n\n"
        content += f"Project: {_wikilink('project', decision.project)}\n\n"
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
            # Skip if already present (substring match)
            if item.text in content:
                continue
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


def route_metrics(
    extraction: HeartbeatExtraction,
    agent: str | None = None,
    decay_candidates: int = 0,
) -> None:
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
        "decay_candidates": decay_candidates,
    }

    with open(metrics_file, "a") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def route_superseded(extraction: HeartbeatExtraction, agent: str | None = None) -> int:
    """Mark superseded learnings/decisions with frontmatter flags.

    Writes superseded: true, superseded_on, superseded_reason to the file's
    frontmatter. Files are kept (not deleted) for audit trail. The search
    indexer excludes them from results.
    """
    if not extraction.superseded_learnings:
        return 0

    data_dir = paths.data_dir(agent)
    today = datetime.now().strftime("%Y-%m-%d")
    count = 0

    for item in extraction.superseded_learnings:
        # Resolve path — accept relative (to data/) or absolute
        target = data_dir / item.file_path
        if not target.exists():
            # Try stripping leading data/ if LLM included it
            alt = data_dir / item.file_path.lstrip("data/").lstrip("/")
            if alt.exists():
                target = alt
            else:
                continue  # File not found — skip silently

        try:
            text = target.read_text(encoding="utf-8")

            if text.startswith("---"):
                # Update existing frontmatter
                end = text.index("---", 3)
                fm_block = text[3:end]
                # Remove any existing superseded fields
                fm_block = re.sub(r"\nsuperseded[^\n]*", "", fm_block)
                new_fm = (
                    f"---{fm_block}"
                    f"\nsuperseded: true"
                    f"\nsuperseded_on: {today}"
                    f"\nsuperseded_reason: \"{item.reason.replace(chr(34), chr(39))}\""
                    f"\n---"
                )
                text = new_fm + text[end + 3:]
            else:
                # Prepend frontmatter
                text = (
                    f"---\nsuperseded: true\nsuperseded_on: {today}"
                    f"\nsuperseded_reason: \"{item.reason.replace(chr(34), chr(39))}\"\n---\n\n"
                    + text
                )

            target.write_text(text, encoding="utf-8")
            count += 1
        except Exception:
            continue

    return count


def route_people(extraction: HeartbeatExtraction, agent: str | None = None) -> int:
    """Append new context to per-person files in data/people/.

    Creates the file if it doesn't exist. Appends a dated section with the
    new content so the file builds up a timestamped history.
    """
    if not extraction.people_updates:
        return 0

    people_dir = paths.data_dir(agent) / "people"
    people_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    count = 0

    for update in extraction.people_updates:
        name = update.name.strip().lower()
        if not name or not update.content.strip():
            continue

        person_file = people_dir / f"{name}.md"
        section = f"\n## Update {today}\n\n{update.content.strip()}\n"

        if person_file.exists():
            person_file.write_text(
                person_file.read_text(encoding="utf-8") + section,
                encoding="utf-8",
            )
        else:
            # Bootstrap minimal file
            person_file.write_text(
                f"---\nname: {name.title()}\nupdated: {today}\n---\n\n# {name.title()}\n{section}",
                encoding="utf-8",
            )
        count += 1

    return count


def route_inbox_out(extraction: HeartbeatExtraction, agent: str | None = None) -> int:
    """Write outbound agent_messages to target agents' data/inbox/ dirs.

    File naming: YYYY-MM-DD-from-{sender}-{slug}.md
    The target agent picks these up on their next heartbeat collect phase.
    """
    if not extraction.agent_messages:
        return 0

    sender = agent or paths.active_agent()
    today = datetime.now().strftime("%Y-%m-%d")
    count = 0

    for msg in extraction.agent_messages:
        target = msg.to.strip().lower()
        if not target or not msg.content.strip():
            continue

        target_inbox = paths.agents_dir() / target / "data" / "inbox"
        target_inbox.mkdir(parents=True, exist_ok=True)

        slug = _slugify(msg.subject)[:40] if msg.subject else "note"
        filename = f"{today}-from-{sender}-{slug}.md"
        # Avoid collisions
        dest = target_inbox / filename
        i = 1
        while dest.exists():
            dest = target_inbox / f"{today}-from-{sender}-{slug}-{i}.md"
            i += 1

        dest.write_text(
            f"---\nfrom: {sender}\nto: {target}\ndate: {today}\nsubject: {msg.subject}\n---\n\n{msg.content.strip()}\n",
            encoding="utf-8",
        )
        count += 1

    return count


def route_inbox_archive(collected: dict, agent: str | None = None) -> int:
    """Archive processed inbox messages to data/inbox/archive/.

    Called after extraction so inbox is clear for next run.
    """
    inbox_msgs = collected.get("inbox_messages", [])
    if not inbox_msgs:
        return 0

    inbox_dir = paths.inbox_dir(agent)
    archive_dir = inbox_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    for msg in inbox_msgs:
        src = inbox_dir / msg["filename"]
        if src.exists():
            src.rename(archive_dir / msg["filename"])
            count += 1

    return count


def route_sessions(collected: dict | None, agent: str | None = None) -> int:
    """Index raw session content into sessions_meta + session_fts for searchability.

    Called with the full collected dict from collect_all(). Returns count of newly indexed sessions.
    """
    if not collected:
        return 0

    session_data = collected.get("sessions", {})
    sessions = session_data.get("sessions", []) if isinstance(session_data, dict) else []
    if not sessions:
        return 0

    try:
        from innie.core.search import index_session, open_db

        conn = open_db(paths.index_db(agent))
        agent_name = agent or paths.active_agent()
        count = 0
        for s in sessions:
            sid = s.get("id", "")
            content = s.get("content", "").strip()
            if not sid or not content:
                continue
            meta = s.get("metadata", {}) if isinstance(s.get("metadata"), dict) else {}
            source = meta.get("source", "")
            file_path = meta.get("file", "")
            newly = index_session(
                conn,
                session_id=sid,
                started=s.get("started", 0.0),
                ended=s.get("ended", 0.0),
                agent=agent_name,
                source=source,
                content=content,
                file_path=file_path,
            )
            if newly:
                count += 1
        conn.close()
        return count
    except Exception:
        return 0


def route_confidence_decay(agent: str | None = None, threshold_days: int = 30) -> int:
    """Scan for low-confidence learnings not retrieved recently.

    Returns count of decay candidates (files that are old, low-confidence, and
    have not appeared in retrieval-log.jsonl within threshold_days).
    Does not modify any files — candidates surface in `innie memory quality`.
    """
    import json

    learnings_dir = paths.learnings_dir(agent)
    if not learnings_dir.exists():
        return 0

    log_file = paths.retrieval_log_file(agent)
    cutoff = time.time() - (threshold_days * 86400)

    # Collect files retrieved within threshold window
    recently_retrieved: set[str] = set()
    if log_file.exists():
        try:
            for line in log_file.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("ts", 0) >= cutoff:
                    for f in entry.get("files", []):
                        recently_retrieved.add(f)
        except Exception:
            pass

    candidates = 0
    for f in learnings_dir.rglob("*.md"):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            if not text.startswith("---"):
                continue
            end = text.find("---", 3)
            if end == -1:
                continue
            fm_text = text[3:end]
            if "confidence: low" not in fm_text:
                continue
            if "superseded: true" in fm_text:
                continue
            # File is old if mtime > threshold_days ago
            if f.stat().st_mtime > cutoff:
                continue
            if str(f) not in recently_retrieved:
                candidates += 1
        except Exception:
            continue

    return candidates


def route_all(
    extraction: HeartbeatExtraction,
    agent: str | None = None,
    collected: dict | None = None,
) -> dict[str, int]:
    """Run all routing for a heartbeat extraction. Returns counts per route."""
    decay_candidates = route_confidence_decay(agent)
    results = {
        "journal": route_journal(extraction, agent),
        "learnings": route_learnings(extraction, agent),
        "projects": route_project_updates(extraction, agent),
        "decisions": route_decisions(extraction, agent),
        "open_items": route_open_items(extraction, agent),
        "superseded": route_superseded(extraction, agent),
        "people": route_people(extraction, agent),
        "inbox_out": route_inbox_out(extraction, agent),
        "inbox_archived": route_inbox_archive(collected or {}, agent),
        "sessions_indexed": route_sessions(collected, agent),
        "decay_candidates": decay_candidates,
    }

    route_metrics(extraction, agent, decay_candidates=decay_candidates)

    # Update heartbeat state — processed_sessions is a per-backend dict {sid: timestamp}
    state = load_heartbeat_state(agent)
    state["last_run"] = time.time()
    processed: dict = state.get("processed_sessions", {})
    if isinstance(processed, list):
        # Migrate legacy flat list to dict
        processed = {}
    for sid in extraction.processed_sessions.ids:
        backend = sid.split("-")[0] if "-" in sid else "unknown"
        processed.setdefault(backend, {})[sid] = time.time()
        # Trim per-backend to 1000 entries
        if len(processed[backend]) > 1000:
            oldest = sorted(processed[backend].items(), key=lambda x: x[1])
            processed[backend] = dict(oldest[-1000:])
    state["processed_sessions"] = processed
    save_heartbeat_state(state, agent)

    return results
