"""Trace commands — view session traces, spans, and aggregate stats."""

import time
from datetime import datetime

import typer
from rich.console import Console
from rich.table import Table

from innie.core import paths
from innie.core.trace import get_session, get_stats, list_sessions, open_trace_db, trace_db_path

console = Console()


def list_traces(
    agent: str = typer.Option(None, "--agent", "-a", help="Filter by agent name"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of sessions to show"),
    days: int = typer.Option(0, "--days", "-d", help="Only show sessions from last N days"),
):
    """List recent trace sessions."""
    db = trace_db_path()
    if not db.exists():
        console.print("[dim]No trace data yet. Sessions are recorded automatically.[/dim]")
        return

    conn = open_trace_db(db)
    since = time.time() - (days * 86400) if days > 0 else None
    sessions = list_sessions(conn, agent_name=agent, limit=limit, since=since)
    conn.close()

    if not sessions:
        console.print("[dim]No sessions found.[/dim]")
        return

    table = Table(title="Trace Sessions")
    table.add_column("Session ID", style="cyan", no_wrap=True)
    table.add_column("Agent", style="green")
    table.add_column("Model")
    table.add_column("Started", style="dim")
    table.add_column("Duration")
    table.add_column("Turns", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Tokens", justify="right")

    for s in sessions:
        started = datetime.fromtimestamp(s.start_time).strftime("%Y-%m-%d %H:%M")
        duration = ""
        if s.end_time:
            dur_s = s.end_time - s.start_time
            if dur_s >= 3600:
                duration = f"{dur_s / 3600:.1f}h"
            elif dur_s >= 60:
                duration = f"{dur_s / 60:.0f}m"
            else:
                duration = f"{dur_s:.0f}s"
        else:
            duration = "[yellow]active[/yellow]"

        cost = f"${s.cost_usd:.4f}" if s.cost_usd else "-"
        tokens = ""
        if s.input_tokens or s.output_tokens:
            total = (s.input_tokens or 0) + (s.output_tokens or 0)
            if total > 1_000_000:
                tokens = f"{total / 1_000_000:.1f}M"
            elif total > 1000:
                tokens = f"{total / 1000:.1f}K"
            else:
                tokens = str(total)

        table.add_row(
            s.session_id[:20],
            s.agent_name,
            s.model or "-",
            started,
            duration,
            str(s.num_turns) if s.num_turns else "-",
            cost,
            tokens,
        )

    console.print(table)


def show(session_id: str = typer.Argument(..., help="Session ID (prefix match supported)")):
    """Show detail for a trace session including all spans."""
    db = trace_db_path()
    if not db.exists():
        console.print("[red]No trace data found.[/red]")
        raise typer.Exit(1)

    conn = open_trace_db(db)

    # Support prefix matching
    session = get_session(conn, session_id)
    if not session:
        # Try prefix match
        rows = conn.execute(
            "SELECT session_id FROM trace_sessions WHERE session_id LIKE ? LIMIT 1",
            (f"{session_id}%",),
        ).fetchall()
        if rows:
            session = get_session(conn, rows[0]["session_id"])

    conn.close()

    if not session:
        console.print(f"[red]Session '{session_id}' not found.[/red]")
        raise typer.Exit(1)

    # Session header
    started = datetime.fromtimestamp(session.start_time).strftime("%Y-%m-%d %H:%M:%S")
    console.print(f"\n[bold]Session: {session.session_id}[/bold]")
    console.print(f"  Agent:    {session.agent_name}")
    console.print(f"  Machine:  {session.machine_id}")
    console.print(f"  Model:    {session.model or 'unknown'}")
    console.print(f"  CWD:      {session.cwd or 'unknown'}")
    console.print(f"  Started:  {started}")

    if session.end_time:
        ended = datetime.fromtimestamp(session.end_time).strftime("%Y-%m-%d %H:%M:%S")
        dur = session.end_time - session.start_time
        console.print(f"  Ended:    {ended} ({dur:.0f}s)")
    else:
        console.print("  Ended:    [yellow]still active[/yellow]")

    if session.cost_usd is not None:
        console.print(f"  Cost:     ${session.cost_usd:.4f}")
    if session.input_tokens or session.output_tokens:
        console.print(
            f"  Tokens:   {session.input_tokens or 0:,} in / {session.output_tokens or 0:,} out"
        )
    if session.num_turns:
        console.print(f"  Turns:    {session.num_turns}")

    # Spans
    if session.spans:
        console.print(f"\n[bold]Spans ({len(session.spans)}):[/bold]\n")

        table = Table()
        table.add_column("Tool", style="cyan")
        table.add_column("Status")
        table.add_column("Duration", justify="right")
        table.add_column("Time", style="dim")
        table.add_column("Input", max_width=40, overflow="ellipsis")

        for span in session.spans:
            ts = datetime.fromtimestamp(span.start_time).strftime("%H:%M:%S")
            dur = f"{span.duration_ms:.0f}ms" if span.duration_ms else "-"
            status = "[green]ok[/green]" if span.status == "ok" else f"[red]{span.status}[/red]"
            input_preview = (span.input_json or "")[:60]

            table.add_row(span.tool_name, status, dur, ts, input_preview)

        console.print(table)
    else:
        console.print("\n[dim]No spans recorded.[/dim]")

    console.print()


def stats(
    agent: str = typer.Option(None, "--agent", "-a", help="Filter by agent name"),
    days: int = typer.Option(30, "--days", "-d", help="Stats for last N days"),
):
    """Show aggregate trace statistics."""
    db = trace_db_path()
    if not db.exists():
        console.print("[dim]No trace data yet.[/dim]")
        return

    conn = open_trace_db(db)
    since = time.time() - (days * 86400) if days > 0 else None
    s = get_stats(conn, agent_name=agent, since=since)
    conn.close()

    period = f"last {days} days" if days > 0 else "all time"
    console.print(f"\n[bold]Trace Statistics[/bold] ({period})\n")

    console.print(f"  Sessions:          {s.total_sessions}")
    console.print(f"  Tool spans:        {s.total_spans}")
    console.print(f"  Total cost:        ${s.total_cost_usd:.4f}")
    total_tokens = s.total_input_tokens + s.total_output_tokens
    if total_tokens > 1_000_000:
        console.print(f"  Total tokens:      {total_tokens / 1_000_000:.1f}M")
    elif total_tokens > 1000:
        console.print(f"  Total tokens:      {total_tokens / 1000:.1f}K")
    else:
        console.print(f"  Total tokens:      {total_tokens}")

    if s.avg_session_duration_s > 0:
        console.print(f"  Avg duration:      {s.avg_session_duration_s / 60:.1f}m")
    if s.avg_turns_per_session > 0:
        console.print(f"  Avg turns/session: {s.avg_turns_per_session:.1f}")

    # Tool breakdown
    if s.tool_usage:
        console.print("\n[bold]Tool Usage:[/bold]")
        for tool, count in list(s.tool_usage.items())[:15]:
            bar = "█" * min(count, 40)
            console.print(f"  {tool:<20} {count:>5}  {bar}")

    # By agent
    if len(s.sessions_by_agent) > 1:
        console.print("\n[bold]Sessions by Agent:[/bold]")
        for agent_name, count in s.sessions_by_agent.items():
            console.print(f"  {agent_name:<20} {count}")

    # Activity heatmap (last 14 days)
    if s.sessions_by_day:
        console.print("\n[bold]Daily Activity:[/bold]")
        max_count = max(s.sessions_by_day.values()) if s.sessions_by_day else 1
        for day, count in list(s.sessions_by_day.items())[:14]:
            bar_len = int((count / max_count) * 30) if max_count > 0 else 0
            bar = "█" * bar_len
            console.print(f"  {day}  {count:>3}  {bar}")

    console.print()
