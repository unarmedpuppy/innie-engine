"""Heartbeat pipeline commands."""

import json
import sys
import time
from datetime import datetime

import typer
from rich.console import Console

from innie.core import paths

console = Console()


def run(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview what would be collected and extracted without writing anything"),
    batch_size: int = typer.Option(0, "--batch-size", "-b", help="Max sessions to process per run (0 = unlimited). Use for retroactive backfill."),
    retroactive: bool = typer.Option(False, "--retroactive", "-r", help="Process all historical sessions regardless of last_run timestamp. Uses processed_sessions to avoid duplicates."),
):
    """Run one heartbeat cycle: collect → extract → route."""
    sys.argv[0] = "innie-heartbeat"
    try:
        import ctypes

        ctypes.CDLL(None).setproctitle(b"innie-heartbeat")
    except Exception:
        pass

    from innie.tui.detect import is_interactive

    if is_interactive():
        from innie.tui.apps.heartbeat import HeartbeatApp

        HeartbeatApp(agent=paths.active_agent(), dry_run=dry_run).run()
        return

    agent = paths.active_agent()
    mode = " [dim](dry run)[/dim]" if dry_run else ""
    console.print(f"Running heartbeat for agent: [bold]{agent}[/bold]{mode}")

    # Sync: pull latest from remote before collecting
    if not dry_run:
        _git_pull()
        _self_update()

    # Phase 1: Collect
    console.print("  Phase 1: Collecting data...")
    from innie.core.collector import collect_all

    collected = collect_all(agent, since_override=0 if retroactive else None)
    all_sessions = collected.get("sessions", {}).get("sessions", [])

    # Filter out trivial sessions.
    # Gateway/conversational sessions (openclaw iMessage/Mattermost) use a lower
    # bar — a 2-message exchange is still meaningful family/personal context.
    # Claude Code workspace sessions use higher thresholds to skip pure tool noise.
    GATEWAY_SOURCES = {"sessions"}  # ~/.openclaw/agents/main/sessions/ label
    def _is_substantive(s: dict) -> bool:
        meta = s.get("metadata", {})
        source = meta.get("source", "")
        msg_count = meta.get("message_count", 0)
        content_len = len(s.get("content", ""))
        if source in GATEWAY_SOURCES:
            return msg_count >= 1 and content_len >= 30
        return msg_count >= 3 and content_len >= 200

    substantive = [s for s in all_sessions if _is_substantive(s)]
    skipped = len(all_sessions) - len(substantive)

    # Apply batch limit
    if batch_size > 0:
        batch = substantive[:batch_size]
    else:
        batch = substantive

    git_count = len(collected.get("git_activity", []))
    console.print(f"    Sessions: {len(batch)} substantive (skipped {skipped} trivial), Git commits: {git_count}")

    if len(batch) == 0 and git_count == 0:
        console.print("  [dim]Nothing new to process.[/dim]")
        return

    # Inject filtered batch back into collected
    collected["sessions"]["sessions"] = batch

    if dry_run:
        console.print("\n  [bold]Sessions that would be processed:[/bold]")
        for s in batch:
            started = s.get("started", 0)
            try:
                ts = datetime.fromtimestamp(float(started)).strftime("%Y-%m-%d %H:%M")
            except Exception:
                ts = str(started)[:16]
            preview = s.get("content", "")[:120].replace("\n", " ")
            console.print(f"    [{ts}] {s['id'][:16]}...  {preview}...")
        if git_count:
            console.print(f"\n  [bold]Git activity:[/bold]")
            for g in collected.get("git_activity", []):
                console.print(f"    [{g['repo']}] {g['commit']}")
        if batch_size > 0 and len(substantive) > batch_size:
            console.print(f"\n  [dim]{len(substantive) - batch_size} more sessions remain after this batch.[/dim]")
        console.print("\n  [dim]Dry run — no extraction, routing, or state changes.[/dim]")
        return

    # Phase 2: Extract
    console.print("  Phase 2: AI extraction...")
    extraction = None
    try:
        from innie.heartbeat.extract import extract

        extraction = extract(collected, agent)
        console.print(
            f"    Extracted: {len(extraction.journal_entries)} journal, "
            f"{len(extraction.learnings)} learnings, "
            f"{len(extraction.decisions)} decisions"
        )
    except Exception as e:
        console.print(f"  [yellow]Extraction failed (skipping): {e}[/yellow]")

    # Phase 3: Route
    if extraction is not None:
        console.print("  Phase 3: Routing to knowledge base...")
        from innie.heartbeat.route import route_all

        results = route_all(extraction, agent, collected=collected)
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


def _self_update():
    """Pull and reinstall the latest innie-engine if auto_update is enabled.

    Detects install type from direct_url.json:
    - Editable/local: reinstall from the local source dir (picks up working-tree changes)
    - PyPI/remote: uv tool upgrade innie-engine --reinstall
    """
    import json
    import subprocess
    import sys
    from pathlib import Path

    from innie.core.config import get

    if not get("heartbeat.auto_update", False):
        return

    dist_info = next(
        Path(sys.executable).parent.parent.glob(
            "lib/python*/site-packages/innie_engine*.dist-info"
        ),
        None,
    )
    if dist_info is None:
        return

    direct_url_file = dist_info / "direct_url.json"
    is_editable = False
    source_dir: str | None = None
    if direct_url_file.exists():
        try:
            info = json.loads(direct_url_file.read_text())
            if info.get("dir_info", {}).get("editable"):
                is_editable = True
                source_dir = info["url"].removeprefix("file://")
        except Exception:
            pass

    if is_editable and source_dir:
        result = subprocess.run(
            ["uv", "tool", "install", "-e", source_dir, "--reinstall"],
            capture_output=True,
            text=True,
        )
    else:
        result = subprocess.run(
            ["uv", "tool", "upgrade", "innie-engine", "--reinstall"],
            capture_output=True,
            text=True,
        )

    if result.returncode == 0:
        console.print("  [green]✓[/green] innie-engine updated")
    else:
        console.print(f"  [yellow]![/yellow] innie-engine update failed: {result.stderr.strip()[:120]}")


def _has_remote():
    """Check if the .innie git repo has a remote configured."""
    import subprocess

    innie_home = paths.home()
    result = subprocess.run(
        ["git", "remote"],
        cwd=innie_home,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() != ""


def _git_pull():
    """Pull latest from remote before making local changes."""
    import subprocess

    from innie.core.config import get

    if not get("git.auto_commit", False):
        return

    innie_home = paths.home()
    git_dir = innie_home / ".git"
    if not git_dir.exists() or not _has_remote():
        return

    pull_result = subprocess.run(
        ["git", "pull", "--rebase", "--autostash"],
        cwd=innie_home,
        capture_output=True,
        text=True,
    )
    if pull_result.returncode == 0:
        pulled = "up to date" not in pull_result.stdout.lower()
        if pulled:
            console.print("  [green]✓[/green] Pulled latest from remote")
    else:
        console.print(f"  [yellow]![/yellow] Pull failed: {pull_result.stderr.strip()}")


def _git_autocommit():
    """Auto-commit and push knowledge base changes to git."""
    import subprocess

    from innie.core.config import get

    if not get("git.auto_commit", False):
        return

    innie_home = paths.home()
    git_dir = innie_home / ".git"
    if not git_dir.exists():
        return

    # Pull from remote before committing to stay in sync across machines.
    # Use rebase so our new entries land on top of any remote changes.
    # -X ours: when replaying our commits, prefer our version on conflict.
    pull_result = subprocess.run(
        ["git", "pull", "--rebase", "-X", "ours"],
        cwd=innie_home,
        capture_output=True,
        text=True,
    )
    if pull_result.returncode != 0:
        # Rebase couldn't auto-resolve — abort and fall back to merge with ours
        subprocess.run(["git", "rebase", "--abort"], cwd=innie_home, capture_output=True)
        subprocess.run(
            ["git", "pull", "-X", "ours"],
            cwd=innie_home,
            capture_output=True,
        )

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
    if _has_remote():
        push_result = subprocess.run(
            ["git", "push"],
            cwd=innie_home,
            capture_output=True,
            text=True,
        )
        if push_result.returncode == 0:
            console.print("  [green]✓[/green] Pushed to remote")
        else:
            console.print("  [yellow]![/yellow] Push failed: {push_result.stderr.strip()}")


def enable():
    """Install cron job for automatic heartbeat (every 30 min)."""
    import os

    from innie.core.config import get

    provider = get("heartbeat.provider", "auto")
    external_url = get("heartbeat.external_url", "")

    # Warn if Anthropic path is selected but key is missing
    from pathlib import Path

    has_openclaw = (Path.home() / ".openclaw" / "openclaw.json").exists()
    needs_anthropic = provider == "anthropic" or (
        provider == "auto" and not external_url and not has_openclaw
    )
    if needs_anthropic and not os.environ.get("ANTHROPIC_API_KEY", ""):
        console.print("[yellow]ANTHROPIC_API_KEY is not set in the current environment.[/yellow]")
        console.print("  The heartbeat cron will fail silently without it.")
        console.print("  To use a local model instead, set in config.toml:")
        console.print("  [dim]  [heartbeat]")
        console.print("  [dim]  provider = \"external\"")
        console.print("  [dim]  external_url = \"http://your-vllm-host/v1\"")
        console.print("  [dim]  model = \"your-model-name\"")
        if not typer.confirm("  Enable cron anyway?", default=False):
            raise typer.Abort()

    import sys

    from innie.commands.init import _install_scheduler

    _install_scheduler()
    scheduler = "launchd" if sys.platform == "darwin" else "cron"
    console.print(f"Heartbeat {scheduler} installed (every 30 min).")


def disable():
    """Remove heartbeat scheduler (launchd on macOS, cron elsewhere)."""
    import subprocess
    import sys
    from pathlib import Path

    if sys.platform == "darwin":
        plist_path = (
            Path.home() / "Library" / "LaunchAgents" / "com.innie-engine.heartbeat.plist"
        )
        if not plist_path.exists():
            console.print("[dim]No launchd plist found.[/dim]")
            return
        subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
        plist_path.unlink(missing_ok=True)
        console.print("Heartbeat launchd agent removed.")
        return

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

    try:
        state = json.loads(state_file.read_text())
    except (json.JSONDecodeError, ValueError):
        console.print("[yellow]Heartbeat state file is corrupted. Delete and re-run.[/yellow]")
        return
    last_run = state.get("last_run", 0)
    ps = state.get("processed_sessions", {})
    if isinstance(ps, dict):
        processed = sum(len(v) for v in ps.values())
    else:
        processed = len(ps)

    if last_run:
        dt = datetime.fromtimestamp(last_run)
        ago = int(time.time() - last_run)
        console.print(f"Last run: {dt.strftime('%Y-%m-%d %H:%M')} ({ago}s ago)")
    console.print(f"Sessions processed (total): {processed}")

    # Check scheduler
    import subprocess
    import sys
    from pathlib import Path

    if sys.platform == "darwin":
        plist_path = (
            Path.home() / "Library" / "LaunchAgents" / "com.innie-engine.heartbeat.plist"
        )
        has_scheduler = plist_path.exists()
        console.print(f"Launchd: {'[green]enabled[/green]' if has_scheduler else '[dim]disabled[/dim]'}")
    else:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        has_scheduler = result.returncode == 0 and "innie" in result.stdout
        console.print(f"Cron: {'[green]enabled[/green]' if has_scheduler else '[dim]disabled[/dim]'}")

    # Provider + credential check
    import os

    from innie.core.config import get as cfg_get

    provider = cfg_get("heartbeat.provider", "auto")
    external_url = cfg_get("heartbeat.external_url", "")
    model = cfg_get("heartbeat.model", "auto")
    if provider == "auto":
        from pathlib import Path

        if (Path.home() / ".openclaw" / "openclaw.json").exists():
            resolved_provider = "openclaw"
        elif external_url:
            resolved_provider = "external"
        else:
            resolved_provider = "anthropic"
    else:
        resolved_provider = provider

    console.print(f"Provider: [bold]{resolved_provider}[/bold]  model={model}")
    if resolved_provider == "openclaw":
        try:
            from innie.heartbeat.extract import _resolve_openclaw

            oc_url, _, oc_model = _resolve_openclaw()
            console.print(f"  URL: {oc_url}  model={oc_model}")
        except Exception as e:
            console.print(f"  [red]{e}[/red]")
    elif resolved_provider == "external":
        console.print(f"  URL: {external_url or '[red]not set[/red]'}")
    else:
        has_key = bool(os.environ.get("ANTHROPIC_API_KEY", ""))
        console.print(f"  ANTHROPIC_API_KEY: {'[green]set[/green]' if has_key else '[red]not set[/red]'}")


def reset_state(
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation"),
):
    """Reset heartbeat state so all sessions are re-processed on next run."""
    agent = paths.active_agent()
    state_file = paths.heartbeat_state(agent)

    if not state_file.exists():
        console.print("[dim]No heartbeat state found — nothing to reset.[/dim]")
        return

    state = json.loads(state_file.read_text())
    ps = state.get("processed_sessions", {})
    if isinstance(ps, dict):
        processed = sum(len(v) for v in ps.values())
    else:
        processed = len(ps)
    console.print(f"  Current state: {processed} sessions marked as processed.")

    if not yes and not typer.confirm("  Reset? All sessions will be re-processed on next run.", default=False):
        raise typer.Abort()

    state_file.write_text(json.dumps({"last_run": 0, "processed_sessions": {}}, indent=2))
    console.print("  [green]✓[/green] Heartbeat state reset.")
