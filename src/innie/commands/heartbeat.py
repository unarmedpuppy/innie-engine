"""Heartbeat pipeline commands."""

import json
import time
from datetime import datetime

import typer
from rich.console import Console

from innie.core import paths

console = Console()


def run():
    """Run one heartbeat cycle: collect → extract → route."""
    agent = paths.active_agent()
    console.print(f"Running heartbeat for agent: [bold]{agent}[/bold]")

    # Phase 1: Collect
    console.print("  Phase 1: Collecting data...")
    from innie.core.collector import collect_all

    collected = collect_all(agent)
    session_count = len(collected.get("sessions", {}).get("sessions", []))
    git_count = len(collected.get("git_activity", []))
    console.print(f"    Sessions: {session_count}, Git commits: {git_count}")

    if session_count == 0 and git_count == 0:
        console.print("  [dim]Nothing new to process.[/dim]")
        return

    # Phase 2: Extract
    console.print("  Phase 2: AI extraction...")
    try:
        from innie.heartbeat.extract import extract

        extraction = extract(collected, agent)
        console.print(
            f"    Extracted: {len(extraction.journal_entries)} journal, "
            f"{len(extraction.learnings)} learnings, "
            f"{len(extraction.decisions)} decisions"
        )
    except Exception as e:
        console.print(f"  [red]Extraction failed: {e}[/red]")
        raise typer.Exit(1)

    # Phase 3: Route
    console.print("  Phase 3: Routing to knowledge base...")
    from innie.heartbeat.route import route_all

    results = route_all(extraction, agent)
    for target, count in results.items():
        if count > 0:
            console.print(f"    {target}: {count}")

    # Re-index changed files
    console.print("  Re-indexing...")
    try:
        from innie.core.search import collect_files, index_files, open_db

        conn = open_db(agent=agent)
        files = collect_files(agent)
        indexed = index_files(conn, files, changed_only=True)
        conn.close()
        if indexed:
            console.print(f"    Indexed {indexed} files")
    except Exception:
        pass

    # Git auto-commit if enabled
    _git_autocommit()

    console.print("  [green]Done.[/green]")


def _git_autocommit():
    """Auto-commit knowledge base changes to git if repo exists."""
    import subprocess

    from innie.core.config import get

    if not get("git.auto_commit", False):
        return

    innie_home = paths.home()
    git_dir = innie_home / ".git"
    if not git_dir.exists():
        return

    # Check for changes
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=innie_home,
        capture_output=True,
        text=True,
    )
    if not result.stdout.strip():
        return  # Nothing to commit

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    subprocess.run(
        ["git", "add", "-A"],
        cwd=innie_home,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", f"heartbeat: auto-commit {now}"],
        cwd=innie_home,
        capture_output=True,
    )

    # Push if remote exists
    if get("git.auto_push", False):
        push_result = subprocess.run(
            ["git", "push"],
            cwd=innie_home,
            capture_output=True,
            text=True,
        )
        if push_result.returncode == 0:
            console.print("  [green]✓[/green] Pushed to remote")
        else:
            console.print("  [yellow]![/yellow] Push failed (no remote?)")


def enable():
    """Install cron job for automatic heartbeat (every 30 min)."""
    from innie.commands.init import _install_cron

    _install_cron()
    console.print("Heartbeat cron installed (every 30 min).")


def disable():
    """Remove heartbeat cron job."""
    import subprocess

    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode != 0:
        console.print("[dim]No crontab found.[/dim]")
        return

    lines = [ln for ln in result.stdout.strip().split("\n") if ln and "innie" not in ln]
    new_crontab = "\n".join(lines) + "\n" if lines else ""
    subprocess.run(["crontab", "-"], input=new_crontab, text=True, check=True)
    console.print("Heartbeat cron removed.")


def hb_status():
    """Show heartbeat status."""
    agent = paths.active_agent()
    state_file = paths.heartbeat_state(agent)

    if not state_file.exists():
        console.print("[dim]Heartbeat has never run.[/dim]")
        return

    state = json.loads(state_file.read_text())
    last_run = state.get("last_run", 0)
    processed = len(state.get("processed_sessions", []))

    if last_run:
        dt = datetime.fromtimestamp(last_run)
        ago = int(time.time() - last_run)
        console.print(f"Last run: {dt.strftime('%Y-%m-%d %H:%M')} ({ago}s ago)")
    console.print(f"Sessions processed (total): {processed}")

    # Check cron
    import subprocess

    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    has_cron = result.returncode == 0 and "innie" in result.stdout
    console.print(f"Cron: {'[green]enabled[/green]' if has_cron else '[dim]disabled[/dim]'}")
