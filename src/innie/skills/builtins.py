"""Built-in skills — structured knowledge base entry creation.

These skills create well-formatted entries in the agent's data/ directory.
They are designed to be called during interactive sessions, either by the
AI assistant or via CLI.

All files include YAML frontmatter and Obsidian-compatible wikilinks.
"""

import logging
import re
from datetime import datetime
from pathlib import Path

from innie.core import paths

logger = logging.getLogger(__name__)


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
    """Build an Obsidian wikilink."""
    slug = _slugify(name)
    if kind == "project":
        return f"[[projects/{slug}/context|{name}]]"
    elif kind == "person":
        return f"[[people/{slug}|{name}]]"
    elif kind == "decision":
        return f"[[decisions/{slug}|{name}]]"
    elif kind == "meeting":
        return f"[[meetings/{slug}|{name}]]"
    return f"[[{slug}|{name}]]"


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
        date_str = today.strftime("%Y-%m-%d")
        parts.append(
            _frontmatter(
                date=date_str,
                type="journal",
                tags=["journal"],
            ).rstrip()
        )
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
    slug = _slugify(title)

    learn_dir = paths.learnings_dir(agent) / category
    learn_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{today}-{slug}.md"
    filepath = learn_dir / filename

    all_tags = ["learning", category]
    if tags:
        all_tags.extend(tags)

    parts = [
        _frontmatter(
            date=today,
            type="learning",
            category=category,
            tags=all_tags,
        ).rstrip(),
        f"# {title}",
        "",
        content,
        "",
    ]
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
    slug = _slugify(title)

    meeting_dir = paths.meetings_dir(agent)
    meeting_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{today.strftime('%Y-%m-%d')}-{slug}.md"
    filepath = meeting_dir / filename

    date_str = today.strftime("%Y-%m-%d")
    attendee_links = [_wikilink("person", a) for a in attendees]

    parts = [
        _frontmatter(
            date=date_str,
            type="meeting",
            attendees=attendees,
            tags=["meeting"],
        ).rstrip(),
        f"# {title}",
        "",
        f"*Attendees: {', '.join(attendee_links)}*",
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
    slug = _slugify(name)

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
        today = datetime.now().strftime("%Y-%m-%d")
        tag_list = ["person"]
        if role:
            tag_list.append(_slugify(role))

        parts = [
            _frontmatter(
                date=today,
                type="person",
                role=role or None,
                tags=tag_list,
            ).rstrip(),
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
            f.write(_frontmatter(type="inbox", tags=["inbox"]))
            f.write("# Inbox\n")
            f.write(entry)

    return inbox_file


def adr(
    title: str,
    context: str,
    decision: str,
    project: str | None = None,
    alternatives: list[str] | None = None,
    consequences: list[str] | None = None,
    status: str = "accepted",
    agent: str | None = None,
) -> Path:
    """Create an Architecture Decision Record."""
    today = datetime.now().strftime("%Y-%m-%d")
    slug = _slugify(title)

    decisions_dir = paths.data_dir(agent) / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)

    # Find next ADR number
    existing = list(decisions_dir.glob("*.md"))
    next_num = len(existing) + 1

    filename = f"{next_num:04d}-{slug}.md"
    filepath = decisions_dir / filename

    tag_list = ["decision", "adr"]
    if project:
        tag_list.append(_slugify(project))

    parts = [
        _frontmatter(
            date=today,
            type="decision",
            status=status,
            project=project,
            tags=tag_list,
        ).rstrip(),
        f"# ADR {next_num}: {title}",
        "",
    ]

    if project:
        parts.append(f"Project: {_wikilink('project', project)}")
        parts.append("")

    parts.extend([
        "## Context",
        "",
        context,
        "",
        "## Decision",
        "",
        decision,
    ])

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
