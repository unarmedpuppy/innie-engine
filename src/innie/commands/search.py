"""Search, index, context, and log commands."""

from datetime import datetime
from typing import Optional

import typer
from rich.console import Console

from innie.core import paths

console = Console()


def search(
    query: Optional[str] = typer.Argument(None, help="Search query (omit for interactive browser)"),
    keyword: bool = typer.Option(False, "--keyword", "-k", help="FTS5 keyword search only"),
    semantic: bool = typer.Option(False, "--semantic", "-s", help="Vector search only"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results"),
    expand: bool = typer.Option(False, "--expand", "-e", help="Generate alt query phrasing via LLM before searching (overrides config)"),
):
    """Search the knowledge base (hybrid keyword + semantic by default)."""
    from innie.tui.detect import is_interactive

    if is_interactive():
        from innie.tui.apps.search import SearchApp

        SearchApp(initial_query=query).run()
        return

    if not query:
        console.print("[red]Query required in non-interactive mode.[/red]")
        raise typer.Exit(1)

    import os

    from innie.core.search import (
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
):
    """Build or refresh the semantic index."""
    from innie.core.search import collect_files, index_files, index_status, open_db

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


def context():
    """Print current CONTEXT.md."""
    ctx_file = paths.context_file()
    if not ctx_file.exists():
        console.print("[dim]No CONTEXT.md found.[/dim]")
        return
    console.print(ctx_file.read_text())


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
