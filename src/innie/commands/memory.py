"""Live in-session memory management commands.

innie memory store <type> <title> <content>  — write directly to knowledge base
innie memory forget <path> <reason>          — supersede a file immediately
innie memory ops [--since HOURS]             — show recent memory operations
"""

import json
import re
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from innie.core import paths

console = Console()


class StoreType(str, Enum):
    learning = "learning"
    decision = "decision"
    project = "project"


class LearningCategory(str, Enum):
    debugging = "debugging"
    patterns = "patterns"
    tools = "tools"
    infrastructure = "infrastructure"
    processes = "processes"


class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower().strip())
    return slug.strip("-")[:60]


def _frontmatter(**fields) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, list):
            if value:
                lines.append(f"{key}: [{', '.join(str(v) for v in value)}]")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def _append_op(op: dict, agent: str | None = None) -> None:
    ops_file = paths.memory_ops_file(agent)
    ops_file.parent.mkdir(parents=True, exist_ok=True)
    op["ts"] = int(time.time())
    with open(ops_file, "a") as f:
        f.write(json.dumps(op, separators=(",", ":")) + "\n")


def _index_file(file_path: Path, agent: str | None = None) -> None:
    """Index a single file into the search DB. Fails silently."""
    try:
        from innie.core.search import index_files, open_db
        conn = open_db(paths.index_db(agent))
        index_files(conn, [file_path], changed_only=False, use_embeddings=False)
        conn.close()
    except Exception:
        pass


def store(
    type: StoreType = typer.Argument(..., help="Type: learning | decision | project"),
    title: str = typer.Argument(..., help="Title of the entry"),
    content: str = typer.Argument(..., help="Content body"),
    category: LearningCategory = typer.Option(LearningCategory.tools, "--category", "-c", help="Learning category"),
    confidence: Confidence = typer.Option(Confidence.medium, "--confidence", help="Confidence level"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name (for decision type)"),
    agent: Optional[str] = typer.Option(None, "--agent", hidden=True),
):
    """Write a learning, decision, or project update directly to the knowledge base."""
    today = datetime.now().strftime("%Y-%m-%d")
    slug = _slugify(title)
    agent = agent or paths.active_agent()

    # H3: prompt injection scan before any write
    from innie.core.secrets import scan_for_injection
    hits = scan_for_injection(f"{title}\n{content}")
    if hits:
        console.print(f"[red]Rejected:[/red] content matches injection pattern: {hits[0]}")
        raise typer.Exit(1)

    if type == StoreType.learning:
        cat_dir = paths.learnings_dir(agent) / category.value
        cat_dir.mkdir(parents=True, exist_ok=True)
        out_file = cat_dir / f"{today}-{slug}.md"
        fm = _frontmatter(
            date=today,
            type="learning",
            category=category.value,
            confidence=confidence.value,
            source="live",
            tags=["learning", category.value],
        )
        out_file.write_text(fm + f"# {title}\n\n{content}\n")
        rel = str(out_file.relative_to(paths.data_dir(agent)))
        _append_op({"op": "store", "type": "learning", "file": rel, "title": title}, agent)
        _index_file(out_file, agent)
        console.print(f"[green]✓[/green] {rel}")

    elif type == StoreType.decision:
        proj = project or "general"
        proj_slug = _slugify(proj)
        decisions_dir = paths.projects_dir(agent) / proj_slug / "decisions"
        decisions_dir.mkdir(parents=True, exist_ok=True)
        out_file = decisions_dir / f"{today}-{slug}.md"
        fm = _frontmatter(
            date=today,
            type="decision",
            project=proj,
            source="live",
            tags=["decision", proj_slug],
        )
        out_file.write_text(fm + f"# {title}\n\nProject: {proj}\n\n{content}\n")
        rel = str(out_file.relative_to(paths.data_dir(agent)))
        _append_op({"op": "store", "type": "decision", "file": rel, "title": title, "project": proj}, agent)
        _index_file(out_file, agent)
        console.print(f"[green]✓[/green] {rel}")

    elif type == StoreType.project:
        proj_slug = _slugify(title)
        project_dir = paths.projects_dir(agent) / proj_slug
        project_dir.mkdir(parents=True, exist_ok=True)
        context_file = project_dir / "context.md"
        if context_file.exists():
            existing = context_file.read_text()
        else:
            existing = _frontmatter(date=today, type="project", tags=["project", proj_slug])
            existing += f"# {title}\n\n## Updates\n\n"
        existing += f"### {today}\n\n{content}\n\n"
        context_file.write_text(existing)
        rel = str(context_file.relative_to(paths.data_dir(agent)))
        _append_op({"op": "store", "type": "project", "file": rel, "title": title}, agent)
        _index_file(context_file, agent)
        console.print(f"[green]✓[/green] {rel}")

    console.print("[dim]Takes effect in search index immediately. Heartbeat will skip re-extracting.[/dim]")


def forget(
    file_path: str = typer.Argument(..., help="File path relative to data/"),
    reason: str = typer.Argument(..., help="Why this entry is superseded"),
    agent: Optional[str] = typer.Option(None, "--agent", hidden=True),
):
    """Mark a knowledge base entry as superseded (does not delete)."""
    agent = agent or paths.active_agent()
    today = datetime.now().strftime("%Y-%m-%d")
    target = paths.data_dir(agent) / file_path.lstrip("/")

    if not target.exists():
        console.print(f"[red]Not found:[/red] {file_path}")
        raise typer.Exit(1)

    text = target.read_text(encoding="utf-8")
    safe_reason = reason.replace('"', "'")

    if text.startswith("---"):
        end = text.index("---", 3)
        fm_block = text[3:end]
        fm_block = re.sub(r"\nsuperseded[^\n]*", "", fm_block)
        new_fm = (
            f"---{fm_block}"
            f"\nsuperseded: true"
            f"\nsuperseded_on: {today}"
            f'\nsuperseded_reason: "{safe_reason}"'
            f"\n---"
        )
        text = new_fm + text[end + 3:]
    else:
        text = (
            f'---\nsuperseded: true\nsuperseded_on: {today}\nsuperseded_reason: "{safe_reason}"\n---\n\n'
            + text
        )

    target.write_text(text, encoding="utf-8")
    _append_op({"op": "forget", "file": file_path, "reason": reason}, agent)
    console.print(f"[green]✓[/green] Superseded: {file_path}")
    console.print("[dim]Heartbeat will not re-create this entry.[/dim]")


def quality(
    days: float = typer.Option(7.0, "--days", "-d", help="Lookback window in days"),
    agent: Optional[str] = typer.Option(None, "--agent", hidden=True),
):
    """Show memory quality stats: top retrieved, never retrieved, confidence distribution."""
    import yaml
    from collections import Counter

    agent = agent or paths.active_agent()
    log_file = paths.retrieval_log_file(agent)
    cutoff = time.time() - (days * 86400)

    # Load retrieval log
    retrieval_counts: Counter = Counter()
    if log_file.exists():
        for line in log_file.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("ts", 0) >= cutoff:
                    for f in entry.get("files", []):
                        retrieval_counts[f] += 1
            except json.JSONDecodeError:
                continue

    retrieved_files = set(retrieval_counts.keys())

    # Collect all data/ markdown files (skip superseded)
    data_dir = paths.data_dir(agent)
    all_files: list[tuple[str, str]] = []  # (path_str, confidence)
    if data_dir.exists():
        for f in sorted(data_dir.rglob("*.md")):
            confidence = ""
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
                if text.startswith("---"):
                    end = text.find("---", 3)
                    if end != -1:
                        fm = yaml.safe_load(text[3:end])
                        if isinstance(fm, dict):
                            if fm.get("superseded"):
                                continue
                            confidence = str(fm.get("confidence", ""))
            except Exception:
                pass
            all_files.append((str(f), confidence))

    never_retrieved = [(f, c) for f, c in all_files if f not in retrieved_files]

    # Confidence distribution
    conf_counts: Counter = Counter()
    for _, c in all_files:
        conf_counts[c or "none"] += 1

    console.print(f"\n[bold]Memory Quality Report[/bold]  (last {days:.0f}d)\n")

    # Top retrieved
    if retrieval_counts:
        console.print("[bold]Top Retrieved[/bold]")
        top = sorted(retrieval_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        table = Table(show_header=True, header_style="bold", show_edge=False)
        table.add_column("Hits", width=5, style="cyan")
        table.add_column("File")
        for fp, count in top:
            try:
                rel = str(Path(fp).relative_to(data_dir))
            except ValueError:
                rel = fp
            table.add_row(str(count), rel)
        console.print(table)
    else:
        console.print("[dim]No retrievals logged yet.[/dim]")

    # Never retrieved learnings (capped at 15)
    learnings_never = [(f, c) for f, c in never_retrieved if "/learnings/" in f][:15]
    if learnings_never:
        console.print(f"\n[bold]Learnings Never Retrieved[/bold]  ({len(learnings_never)} shown)")
        table2 = Table(show_header=True, header_style="bold", show_edge=False)
        table2.add_column("Conf", width=6, style="dim")
        table2.add_column("File")
        for fp, c in learnings_never:
            try:
                rel = str(Path(fp).relative_to(data_dir))
            except ValueError:
                rel = fp
            table2.add_row(c or "-", rel)
        console.print(table2)

    # Decay candidates: low confidence, never retrieved
    decay = [(f, c) for f, c in learnings_never if c == "low"]
    if decay:
        console.print(f"\n[yellow]Decay candidates:[/yellow] {len(decay)} low-confidence learnings never retrieved")
        console.print("[dim]Consider: innie memory forget <path> \"no longer relevant\"[/dim]")

    # Confidence distribution
    if conf_counts:
        console.print(f"\n[bold]Confidence Distribution[/bold]  ({len(all_files)} total files)")
        for lvl in ("high", "medium", "low", "none"):
            count = conf_counts.get(lvl, 0)
            if count:
                bar = "█" * min(count, 40)
                console.print(f"  {lvl:8s} {count:4d}  [dim]{bar}[/dim]")


def ops(
    since: float = typer.Option(8.0, "--since", "-s", help="Hours to look back"),
    agent: Optional[str] = typer.Option(None, "--agent", hidden=True),
):
    """Show recent memory operations from this session."""
    agent = agent or paths.active_agent()
    ops_file = paths.memory_ops_file(agent)

    if not ops_file.exists():
        console.print("[dim]No memory ops recorded yet.[/dim]")
        return

    cutoff = time.time() - (since * 3600)
    entries = []
    for line in ops_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if entry.get("ts", 0) >= cutoff:
                entries.append(entry)
        except json.JSONDecodeError:
            continue

    if not entries:
        console.print(f"[dim]No ops in last {since:.0f}h.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Time", style="dim", width=8)
    table.add_column("Op", width=8)
    table.add_column("Type", width=10)
    table.add_column("File / Detail")

    for e in entries:
        ts = datetime.fromtimestamp(e.get("ts", 0)).strftime("%H:%M:%S")
        op = e.get("op", "?")
        typ = e.get("type", "")
        detail = e.get("file", e.get("text", ""))
        table.add_row(ts, op, typ, detail)

    console.print(table)
