"""Session search and list commands.

innie session list   — list recently indexed sessions
innie session search — FTS search across session content
"""

import time
from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from grove.core import paths

console = Console()


def list_sessions(
    days: float = typer.Option(30.0, "--days", "-d", help="Sessions from last N days"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max rows to show"),
    agent: Optional[str] = typer.Option(None, "--agent", hidden=True),
):
    """List recently indexed sessions from the knowledge base."""
    from grove.core.search import list_sessions_kb, open_db, sessions_count

    db_path = paths.index_db(agent)
    if not db_path.exists():
        console.print("[dim]No index found. Run: innie index[/dim]")
        raise typer.Exit(1)

    conn = open_db(db_path)
    total = sessions_count(conn)
    since = time.time() - (days * 86400) if days > 0 else None
    sessions = list_sessions_kb(conn, agent=agent, limit=limit, since=since)
    conn.close()

    if not sessions:
        console.print("[dim]No sessions indexed yet. Heartbeat indexes sessions automatically.[/dim]")
        return

    table = Table(title=f"Sessions ({total} total, last {days:.0f}d)")
    table.add_column("Started", style="dim", width=16)
    table.add_column("Duration", width=8)
    table.add_column("Session ID", style="cyan", no_wrap=True)
    table.add_column("Source", style="green")

    for s in sessions:
        started = datetime.fromtimestamp(s["started"]).strftime("%Y-%m-%d %H:%M") if s["started"] else "-"
        duration = ""
        if s["started"] and s["ended"]:
            dur_s = s["ended"] - s["started"]
            if dur_s >= 3600:
                duration = f"{dur_s / 3600:.1f}h"
            elif dur_s >= 60:
                duration = f"{dur_s / 60:.0f}m"
            else:
                duration = f"{dur_s:.0f}s"

        table.add_row(started, duration, s["session_id"][:32], s["source"] or "-")

    console.print(table)


def search_sessions(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results"),
    agent: Optional[str] = typer.Option(None, "--agent", hidden=True),
):
    """Search across indexed session content."""
    from grove.core.search import open_db, search_sessions as _search

    db_path = paths.index_db(agent)
    if not db_path.exists():
        console.print("[dim]No index found. Run: innie index[/dim]")
        raise typer.Exit(1)

    conn = open_db(db_path)
    results = _search(conn, query, limit=limit)
    conn.close()

    if not results:
        console.print("[dim]No sessions matched.[/dim]")
        return

    for r in results:
        started = datetime.fromtimestamp(r["started"]).strftime("%Y-%m-%d %H:%M") if r["started"] else "?"
        fp_hint = f"  [dim]→ {r['file_path']}[/dim]" if r.get("file_path") else ""
        console.print(f"\n[bold cyan]{r['session_id'][:32]}[/bold cyan]  [dim]{started}  {r['source'] or ''}[/dim]{fp_hint}")
        console.print(f"  {r['snippet']}")


def backfill_sessions(
    agent: Optional[str] = typer.Option(None, "--agent", hidden=True),
):
    """Backfill file_path for sessions indexed before file tracking was added."""
    from pathlib import Path

    from grove.core.search import open_db

    db_path = paths.index_db(agent)
    if not db_path.exists():
        console.print("[dim]No index found.[/dim]")
        raise typer.Exit(1)

    conn = open_db(db_path)
    rows = conn.execute(
        "SELECT id, session_id FROM sessions_meta WHERE file_path IS NULL"
    ).fetchall()

    if not rows:
        console.print("[green]All sessions already have file_path — nothing to backfill.[/green]")
        conn.close()
        return

    # Build lookup: session_id stem -> absolute path
    session_map: dict[str, str] = {}
    projects_dir = Path.home() / ".claude" / "projects"
    if projects_dir.exists():
        for d in projects_dir.iterdir():
            if d.is_dir():
                for f in d.glob("*.jsonl"):
                    session_map[f.stem] = str(f)

    updated = 0
    for row_id, sid in rows:
        fp = session_map.get(sid)
        if fp:
            conn.execute("UPDATE sessions_meta SET file_path = ? WHERE id = ?", (fp, row_id))
            updated += 1

    conn.commit()
    conn.close()
    console.print(f"[green]Backfilled {updated}/{len(rows)} sessions with file_path.[/green]")
    if updated < len(rows):
        console.print(f"[dim]{len(rows) - updated} sessions have no matching JSONL on disk (file may have been deleted).[/dim]")


def read_session(
    session_id: str = typer.Argument(..., help="Session ID or prefix"),
    agent: Optional[str] = typer.Option(None, "--agent", hidden=True),
    raw: bool = typer.Option(False, "--raw", help="Print raw JSONL lines (requires source file)"),
):
    """Read full session content. Reads source JSONL if available, else cached transcript."""
    import json as _json

    from grove.core.search import open_db

    db_path = paths.index_db(agent)
    if not db_path.exists():
        console.print("[dim]No index found. Run: innie index[/dim]")
        raise typer.Exit(1)

    conn = open_db(db_path)
    row = conn.execute(
        "SELECT session_id, started, ended, source, file_path, content"
        " FROM sessions_meta WHERE session_id LIKE ? ORDER BY started DESC LIMIT 1",
        (f"{session_id}%",),
    ).fetchone()
    conn.close()

    if not row:
        console.print(f"[red]No session found matching:[/red] {session_id}")
        raise typer.Exit(1)

    sid, started, ended, source, file_path, content = row
    started_str = datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M") if started else "?"
    console.print(f"[bold cyan]{sid}[/bold cyan]  [dim]{started_str}  {source or ''}[/dim]")
    if file_path:
        console.print(f"[dim]Source: {file_path}[/dim]")

    # Try reading from raw JSONL source file first
    if file_path:
        from pathlib import Path as _Path
        jsonl = _Path(file_path)
        if jsonl.exists():
            if raw:
                console.print(jsonl.read_text(encoding="utf-8", errors="ignore"))
            else:
                # Re-parse to readable transcript (same logic as backend)
                lines = [ln for ln in jsonl.read_text(encoding="utf-8", errors="ignore").strip().split("\n") if ln.strip()]
                messages: list[str] = []
                for line in lines:
                    try:
                        entry = _json.loads(line)
                        role = entry.get("type", "")
                        if role not in ("user", "assistant"):
                            msg = entry.get("message", {})
                            role = msg.get("role", "") if isinstance(msg, dict) else ""
                        if role not in ("user", "assistant"):
                            continue
                        msg = entry.get("message", {})
                        content_field = msg.get("content", "") if isinstance(msg, dict) else ""
                        text = content_field if isinstance(content_field, str) else ""
                        if isinstance(content_field, list):
                            text = " ".join(
                                b.get("text", "") for b in content_field
                                if isinstance(b, dict) and b.get("type") == "text"
                            )
                        if text.strip():
                            console.print(f"\n[bold]\\[{role}][/bold] {text[:2000]}")
                    except Exception:
                        continue
            return

    # Fallback: cached transcript from DB
    if content:
        console.print("\n[dim](from cached index — source file not available)[/dim]")
        console.print(content)
    else:
        console.print("[dim]No content available.[/dim]")
