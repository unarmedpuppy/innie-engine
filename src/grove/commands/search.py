"""Search, index, context, and log commands."""

import re
from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from grove.core import paths

console = Console()


def search(
    query: Optional[str] = typer.Argument(None, help="Search query (omit for interactive browser)"),
    keyword: bool = typer.Option(False, "--keyword", "-k", help="FTS5 keyword search only"),
    semantic: bool = typer.Option(False, "--semantic", "-s", help="Vector search only"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results"),
    expand: bool = typer.Option(False, "--expand", "-e", help="Generate alt query phrasing via LLM before searching (overrides config)"),
):
    """Search the knowledge base (hybrid keyword + semantic by default)."""
    from grove.tui.detect import is_interactive

    if is_interactive():
        from grove.tui.apps.search import SearchApp

        SearchApp(initial_query=query).run()
        return

    if not query:
        console.print("[red]Query required in non-interactive mode.[/red]")
        raise typer.Exit(1)

    import os

    from grove.core.search import (
        format_results,
        open_db,
        search_hybrid,
        search_keyword,
        search_semantic,
    )

    db_path = paths.index_db()
    if not db_path.exists():
        console.print("[yellow]No index found. Run: innie index[/yellow]")
        raise typer.Exit(1)

    conn = open_db(db_path)

    # --expand temporarily sets the env-level override without mutating config on disk
    if expand:
        os.environ["INNIE_QUERY_EXPANSION"] = "1"

    if keyword:
        results = search_keyword(conn, query, limit)
    elif semantic:
        results = search_semantic(conn, query, limit)
    else:
        results = search_hybrid(conn, query, limit)

    if expand:
        os.environ.pop("INNIE_QUERY_EXPANSION", None)

    conn.close()

    if not results:
        console.print("[dim]No results found.[/dim]")
        return

    output = format_results(results)
    console.print(output)


def index(
    changed_only: bool = typer.Option(False, "--changed-only", help="Only index modified files"),
    status_only: bool = typer.Option(False, "--status", help="Show index stats only"),
    mode: str = typer.Option("default", "--mode", "-m", help="LLM routing mode: default | claude (routes any LLM calls through local proxy)"),
):
    """Build or refresh the semantic index."""
    from grove.core import paths
    from grove.core.search import collect_files, index_files, index_status, open_db

    if mode != "default":
        try:
            from grove.commands.launch import apply_mode_env
            apply_mode_env(paths.active_agent(), mode)
        except Exception:
            pass

    conn = open_db()

    if status_only:
        stats = index_status(conn)
        conn.close()
        console.print(f"Files indexed: {stats['files']}")
        console.print(f"Chunks: {stats['chunks']}")
        console.print(f"Vectors: {stats['vectors']}")
        console.print(f"Has embeddings: {stats['has_embeddings']}")
        return

    files = collect_files()
    console.print(f"Found {len(files)} files to index...")

    # Try with embeddings, fall back to FTS-only
    try:
        count = index_files(conn, files, changed_only=changed_only, use_embeddings=True)
    except Exception as e:
        console.print(f"[yellow]Embedding service unavailable ({e}). Using keyword-only.[/yellow]")
        count = index_files(conn, files, changed_only=changed_only, use_embeddings=False)

    conn.close()
    console.print(f"Indexed {count} files.")


def context_show(agent: Optional[str] = None):
    """Print current CONTEXT.md."""
    ctx_file = paths.context_file(agent)
    if not ctx_file.exists():
        console.print("[dim]No CONTEXT.md found.[/dim]")
        return
    console.print(ctx_file.read_text())


def context_add(
    text: str = typer.Argument(..., help="Open item text to add (prefix '- ' optional)"),
    agent: Optional[str] = typer.Option(None, "--agent", hidden=True),
):
    """Add an open item to CONTEXT.md. Takes effect next session."""
    import json
    import time

    ctx_file = paths.context_file(agent)
    if not ctx_file.exists():
        console.print("[red]No CONTEXT.md found.[/red]")
        raise typer.Exit(1)

    content = ctx_file.read_text()
    bullet = text if text.startswith("- ") else f"- {text}"

    # Check for duplicate
    if bullet in content or text in content:
        console.print("[dim]Already in CONTEXT.md — skipped.[/dim]")
        return

    marker = "## Open Items"
    if marker not in content:
        content += f"\n\n{marker}\n\n{bullet}\n"
    else:
        idx = content.index(marker) + len(marker)
        next_nl = content.index("\n", idx)
        content = content[: next_nl + 1] + f"\n{bullet}" + content[next_nl:]

    import re
    content = re.sub(
        r"\*Last updated:.*?\*",
        f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        content,
    )
    ctx_file.write_text(content)

    # Audit trail
    ops_file = paths.memory_ops_file(agent)
    ops_file.parent.mkdir(parents=True, exist_ok=True)
    with open(ops_file, "a") as f:
        f.write(json.dumps({"ts": int(time.time()), "op": "context_add", "text": bullet}, separators=(",", ":")) + "\n")

    console.print(f"[green]✓[/green] Added: {bullet}")
    console.print("[dim]Takes effect next session.[/dim]")


def context_remove(
    text: str = typer.Argument(..., help="Substring of the open item to remove"),
    agent: Optional[str] = typer.Option(None, "--agent", hidden=True),
):
    """Remove an open item from CONTEXT.md by substring match."""
    import json
    import time

    ctx_file = paths.context_file(agent)
    if not ctx_file.exists():
        console.print("[red]No CONTEXT.md found.[/red]")
        raise typer.Exit(1)

    content = ctx_file.read_text()
    lines = content.splitlines(keepends=True)
    new_lines = [l for l in lines if text not in l]

    if len(new_lines) == len(lines):
        console.print(f"[dim]No match for: {text!r}[/dim]")
        return

    import re
    new_content = "".join(new_lines)
    new_content = re.sub(
        r"\*Last updated:.*?\*",
        f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        new_content,
    )
    ctx_file.write_text(new_content)

    ops_file = paths.memory_ops_file(agent)
    ops_file.parent.mkdir(parents=True, exist_ok=True)
    with open(ops_file, "a") as f:
        f.write(json.dumps({"ts": int(time.time()), "op": "context_remove", "text": text}, separators=(",", ":")) + "\n")

    removed = len(lines) - len(new_lines)
    console.print(f"[green]✓[/green] Removed {removed} line(s) matching: {text!r}")
    console.print("[dim]Takes effect next session.[/dim]")


def context_load(
    path: str = typer.Argument(..., help="File path relative to data/ (e.g. learnings/tools/2026-03-01-slug.md)"),
    agent: Optional[str] = typer.Option(None, "--agent", hidden=True),
):
    """Print the full content of a knowledge base file.

    Use when memory-context is in index-only mode and you need to read a specific entry.
    Path is relative to data/; absolute paths are also accepted.
    """
    from pathlib import Path as _Path

    a = agent or paths.active_agent()
    target = paths.data_dir(a) / path.lstrip("/")
    if not target.exists():
        abs_path = _Path(path).expanduser()
        if abs_path.exists():
            target = abs_path
        else:
            console.print(f"[red]Not found:[/red] {path}")
            raise typer.Exit(1)

    if target.suffix != ".md":
        console.print("[red]Only .md files supported.[/red]")
        raise typer.Exit(1)

    console.print(target.read_text())


def context_compress(
    apply: bool = typer.Option(False, "--apply", help="Write compressed output (skip diff prompt)"),
    agent: Optional[str] = typer.Option(None, "--agent", hidden=True),
):
    """Dedup and trim CONTEXT.md Open Items via LLM. Shows diff, prompts before writing."""
    ctx_file = paths.context_file(agent)
    if not ctx_file.exists():
        console.print("[red]No CONTEXT.md found.[/red]")
        raise typer.Exit(1)

    content = ctx_file.read_text()

    # Extract Open Items section for preview/diff
    marker = "## Open Items"
    if marker not in content:
        console.print("[dim]No Open Items section found.[/dim]")
        return

    start = content.index(marker)
    after_header = content.index("\n", start) + 1
    next_section = re.search(r"^##\s", content[after_header:], re.MULTILINE)
    end = after_header + next_section.start() if next_section else len(content)
    open_items_block = content[after_header:end].strip()

    if not open_items_block:
        console.print("[dim]Open Items section is empty.[/dim]")
        return

    bullets = [l for l in open_items_block.splitlines() if l.strip().startswith("-")]
    if len(bullets) <= 3:
        console.print(f"[dim]Only {len(bullets)} items — nothing to compress.[/dim]")
        return

    console.print(f"[dim]Compressing {len(bullets)} open items via LLM...[/dim]")

    # Snapshot content before compression for diff display
    old_bullets = set(bullets)

    if not apply:
        # Preview mode: need to show diff before writing — do a dry-run pass
        # We'll call the core function on a temp copy, then show diff, then confirm
        import shutil, tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            from grove.core.context import compress_context_open_items
            before, after = compress_context_open_items(tmp_path, agent)
        finally:
            # Don't actually persist the temp result yet
            tmp_path.unlink(missing_ok=True)

        if before == 0:
            console.print("[red]LLM call failed or nothing to compress.[/red]")
            raise typer.Exit(1)

        console.print(f"\n[bold]Before:[/bold] {before} items  →  [bold]After:[/bold] {after} items")
        console.print(f"  [dim]{after} items kept[/dim]")

        if not typer.confirm("\nApply?", default=False):
            console.print("[dim]Aborted.[/dim]")
            return

    # Apply compression for real
    from grove.core.context import compress_context_open_items
    before, after = compress_context_open_items(ctx_file, agent)

    if before == 0:
        console.print("[red]LLM call failed or nothing to compress.[/red]")
        raise typer.Exit(1)

    console.print(f"[green]✓[/green] Compressed: {before} → {after} items")
    console.print("[dim]Takes effect next session.[/dim]")


def ls(
    path: Optional[str] = typer.Argument(None, help="Subdirectory of data/ to list (e.g. learnings/tools)"),
    agent: Optional[str] = typer.Option(None, "--agent", hidden=True),
):
    """Browse the knowledge base directory structure."""
    import yaml

    base = paths.data_dir(agent)
    if not base.exists():
        console.print("[dim]No knowledge base found.[/dim]")
        return

    target = base / path.lstrip("/") if path else base

    if not target.exists():
        console.print(f"[red]Not found:[/red] {path}")
        raise typer.Exit(1)

    if not target.is_dir():
        console.print(f"[red]Not a directory:[/red] {path}")
        raise typer.Exit(1)

    # If top-level data/, show subdirectories with file counts
    if target == base:
        table = Table(show_header=True, header_style="bold", title="Knowledge Base")
        table.add_column("Directory")
        table.add_column("Files", justify="right", style="dim")
        for subdir in sorted(target.iterdir()):
            if subdir.is_dir() and not subdir.name.startswith("."):
                count = sum(1 for _ in subdir.rglob("*.md"))
                table.add_row(subdir.name, str(count))
        console.print(table)
        return

    # List .md files in the target directory (recursive one level)
    files = sorted(target.rglob("*.md"))
    if not files:
        console.print("[dim]No files found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold", title=str(target.relative_to(base)))
    table.add_column("Date", style="dim", width=12)
    table.add_column("Title / Abstract")
    table.add_column("Conf", width=6, style="dim")

    for f in files:
        date_str = ""
        title = f.stem
        confidence = ""
        abstract = ""

        # Parse frontmatter for metadata
        text = f.read_text(encoding="utf-8", errors="ignore")
        if text.startswith("---"):
            try:
                end = text.index("---", 3)
                fm = yaml.safe_load(text[3:end])
                if isinstance(fm, dict):
                    date_str = str(fm.get("date", ""))
                    confidence = str(fm.get("confidence", ""))
                    abstract = str(fm.get("abstract_l0", ""))
            except Exception:
                pass

        if not abstract:
            # Fall back to first non-header, non-empty line after frontmatter
            body = text[text.index("---", 3) + 3:].strip() if text.startswith("---") else text
            for line in body.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("---"):
                    abstract = line[:80]
                    break

        if not abstract:
            abstract = title.replace("-", " ")

        table.add_row(date_str, abstract, confidence)

    console.print(table)


def log(
    date: str = typer.Option("", "--date", "-d", help="Date (YYYY-MM-DD), default today"),
    session: bool = typer.Option(
        False, "--session", "-s", help="Show session log instead of journal"
    ),
):
    """Show journal entry or session log for a date."""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    if session:
        log_file = paths.sessions_dir() / f"{date}.md"
    else:
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            console.print(f"[red]Invalid date format: {date}[/red]")
            raise typer.Exit(1)
        log_file = paths.journal_dir() / f"{dt.year}" / f"{dt.month:02d}" / f"{dt.day:02d}.md"

    if not log_file.exists():
        console.print(f"[dim]No {'session' if session else 'journal'} entry for {date}.[/dim]")
        return

    console.print(log_file.read_text())
