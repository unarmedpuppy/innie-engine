"""Built-in skills — structured knowledge base entry creation.

These skills create well-formatted entries in the agent's data/ directory.
They are designed to be called during interactive sessions, either by the
AI assistant or via CLI.
"""

import logging
from datetime import datetime
from pathlib import Path

from innie.core import paths

logger = logging.getLogger(__name__)


def daily(
    summary: str,
    highlights: list[str] | None = None,
    blockers: list[str] | None = None,
    agent: str | None = None,
) -> Path:
    """Create or append to today's journal entry.

    Returns path to the journal file.
    """
    today = datetime.now()
    journal_dir = paths.journal_dir(agent)
    year_dir = journal_dir / str(today.year) / f"{today.month:02d}"
    year_dir.mkdir(parents=True, exist_ok=True)

    journal_file = year_dir / f"{today.day:02d}.md"

    parts = []
    if journal_file.exists():
        parts.append(journal_file.read_text().rstrip())
        parts.append("")  # blank line separator
    else:
        parts.append(f"# {today.strftime('%Y-%m-%d %A')}")
        parts.append("")

    parts.append(f"## {today.strftime('%H:%M')} — Daily Update")
    parts.append("")
    parts.append(summary)

    if highlights:
        parts.append("")
        parts.append("### Highlights")
        for item in highlights:
            parts.append(f"- {item}")

    if blockers:
        parts.append("")
        parts.append("### Blockers")
        for item in blockers:
            parts.append(f"- {item}")

    parts.append("")
    journal_file.write_text("\n".join(parts))
    return journal_file


def learn(
    title: str,
    content: str,
    category: str = "patterns",
    tags: list[str] | None = None,
    agent: str | None = None,
) -> Path:
    """Create a learning entry in the knowledge base.

    Categories: debugging, patterns, tools, infrastructure, processes
    """
    today = datetime.now().strftime("%Y-%m-%d")
    slug = title.lower().replace(" ", "-")[:50]

    learn_dir = paths.learnings_dir(agent) / category
    learn_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{today}-{slug}.md"
    filepath = learn_dir / filename

    parts = [
        f"# {title}",
        "",
        f"*Learned: {today}*",
    ]

    if tags:
        parts.append(f"*Tags: {', '.join(tags)}*")

    parts.extend(["", content, ""])
    filepath.write_text("\n".join(parts))
    return filepath


def meeting(
    title: str,
    attendees: list[str],
    notes: str,
    action_items: list[str] | None = None,
    decisions: list[str] | None = None,
    agent: str | None = None,
) -> Path:
    """Create a meeting notes entry."""
    today = datetime.now()
    slug = title.lower().replace(" ", "-")[:50]

    meeting_dir = paths.meetings_dir(agent)
    meeting_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{today.strftime('%Y-%m-%d')}-{slug}.md"
    filepath = meeting_dir / filename

    parts = [
        f"# {title}",
        "",
        f"*Date: {today.strftime('%Y-%m-%d %H:%M')}*",
        f"*Attendees: {', '.join(attendees)}*",
        "",
        "## Notes",
        "",
        notes,
    ]

    if decisions:
        parts.extend(["", "## Decisions"])
        for item in decisions:
            parts.append(f"- {item}")

    if action_items:
        parts.extend(["", "## Action Items"])
        for item in action_items:
            parts.append(f"- [ ] {item}")

    parts.append("")
    filepath.write_text("\n".join(parts))
    return filepath


def contact(
    name: str,
    role: str = "",
    notes: str = "",
    contact_info: dict[str, str] | None = None,
    agent: str | None = None,
) -> Path:
    """Create or update a contact entry."""
    slug = name.lower().replace(" ", "-")

    people_dir = paths.people_dir(agent)
    people_dir.mkdir(parents=True, exist_ok=True)

    filepath = people_dir / f"{slug}.md"

    if filepath.exists():
        # Append to existing
        existing = filepath.read_text().rstrip()
        today = datetime.now().strftime("%Y-%m-%d")
        updated = f"{existing}\n\n## Update ({today})\n\n{notes}\n"
        filepath.write_text(updated)
    else:
        parts = [
            f"# {name}",
            "",
        ]
        if role:
            parts.append(f"*Role: {role}*")
        if contact_info:
            parts.append("")
            parts.append("## Contact")
            for key, val in contact_info.items():
                parts.append(f"- **{key}**: {val}")
        if notes:
            parts.extend(["", "## Notes", "", notes])
        parts.append("")
        filepath.write_text("\n".join(parts))

    return filepath


def inbox(
    content: str,
    source: str = "manual",
    agent: str | None = None,
) -> Path:
    """Quick capture to inbox (append-only)."""
    inbox_dir = paths.inbox_dir(agent)
    inbox_dir.mkdir(parents=True, exist_ok=True)

    inbox_file = inbox_dir / "inbox.md"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    entry = f"\n- [{now}] ({source}) {content}\n"

    if inbox_file.exists():
        with open(inbox_file, "a") as f:
            f.write(entry)
    else:
        with open(inbox_file, "w") as f:
            f.write("# Inbox\n")
            f.write(entry)

    return inbox_file


def adr(
    title: str,
    context: str,
    decision: str,
    alternatives: list[str] | None = None,
    consequences: list[str] | None = None,
    status: str = "accepted",
    agent: str | None = None,
) -> Path:
    """Create an Architecture Decision Record."""
    today = datetime.now().strftime("%Y-%m-%d")
    slug = title.lower().replace(" ", "-")[:60]

    # ADRs go in data/projects or a top-level decisions dir
    decisions_dir = paths.data_dir(agent) / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)

    # Find next ADR number
    existing = list(decisions_dir.glob("*.md"))
    next_num = len(existing) + 1

    filename = f"{next_num:04d}-{slug}.md"
    filepath = decisions_dir / filename

    parts = [
        f"# ADR {next_num}: {title}",
        "",
        f"*Date: {today}*",
        f"*Status: {status}*",
        "",
        "## Context",
        "",
        context,
        "",
        "## Decision",
        "",
        decision,
    ]

    if alternatives:
        parts.extend(["", "## Alternatives Considered"])
        for alt in alternatives:
            parts.append(f"- {alt}")

    if consequences:
        parts.extend(["", "## Consequences"])
        for con in consequences:
            parts.append(f"- {con}")

    parts.append("")
    filepath.write_text("\n".join(parts))
    return filepath
