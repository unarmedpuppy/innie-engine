"""grove update — upgrade grove from its configured install source."""

import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

from grove.core.config import get

console = Console()


def update(
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation and index rebuild prompt"),
):
    """Upgrade grove from its configured install source.

    Install source is set during `g init` and stored in config.toml
    under [update]. Edit it manually if you switch from Gitea to GitHub or
    change your local clone path.
    """
    source = get("update.source", "")
    installer = get("update.installer", "uv")

    if not source:
        console.print("[red]No update source configured.[/red]")
        console.print("  Set it in ~/.grove/config.toml:")
        console.print("  [dim][update]")
        console.print("  source = \"git+https://github.com/joshuajenquist/grove.git\"[/dim]")
        console.print("  Or re-run: [bold]g init[/bold]")
        raise typer.Exit(1)

    # Local editable installs — code changes are already live
    is_local = source.startswith("/") or source.startswith("~") or source.startswith(".")
    if is_local:
        expanded = str(Path(source).expanduser().resolve())
        console.print(f"  Source: [dim]{expanded}[/dim] (local editable)")
        console.print("  Editable installs pick up code changes immediately.")
        console.print("  To pull latest commits: [bold]git -C {expanded} pull[/bold]")
        if typer.confirm("\n  Run git pull now?", default=True):
            result = subprocess.run(["git", "-C", expanded, "pull"], text=True)
            if result.returncode != 0:
                raise typer.Exit(1)
        _reinstall_hooks()
        _prompt_reindex(yes)
        _run_boot(yes)
        return

    # Remote install via uv or pip
    console.print(f"  Installer: [bold]{installer}[/bold]")
    console.print(f"  Source:    [dim]{source}[/dim]\n")

    if installer == "uv":
        cmd = ["uv", "tool", "install", "--upgrade", source]
    else:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", source]

    console.print(f"  Running: [dim]{' '.join(cmd)}[/dim]\n")
    result = subprocess.run(cmd, text=True)

    if result.returncode != 0:
        console.print("\n[red]Upgrade failed.[/red] Check the output above.")
        raise typer.Exit(1)

    console.print("\n  [green]✓[/green] Upgrade complete.")
    _reinstall_hooks()
    _prompt_reindex(yes)
    _run_boot(yes)


def _reinstall_hooks() -> None:
    """Re-register hooks for all detected backends after an upgrade."""
    from grove.backends.registry import detect_backends

    hooks_dir = Path(__file__).parent.parent / "hooks"
    backends = detect_backends()
    for backend in backends:
        try:
            backend.install_hooks(hooks_dir)
            console.print(f"  [green]✓[/green] Hooks updated for [bold]{backend.name()}[/bold]")
        except Exception as e:
            console.print(f"  [yellow]![/yellow] Hook update failed for {backend.name()}: {e}")


def _run_boot(yes: bool) -> None:
    """Run g boot after a successful update (skip version re-check and heartbeat)."""
    console.print()
    from grove.commands.boot import boot

    boot(skip_heartbeat=True, force_update=False, no_restart=False)


def _prompt_reindex(yes: bool) -> None:
    console.print("\n  [bold]Index rebuild recommended[/bold]")
    console.print("  Chunk configuration may have changed. Old chunks may be stale.")
    if yes or typer.confirm("  Run `g index` now?", default=True):
        console.print()
        try:
            from grove.core import paths
            from grove.core.search import collect_files, index_files, open_db

            agent = paths.active_agent()
            conn = open_db(agent=agent)
            files = collect_files(agent)
            indexed = index_files(conn, files, changed_only=False)
            conn.close()
            console.print(f"  [green]✓[/green] Index rebuilt ({indexed} files).")
        except Exception as e:
            console.print(f"[yellow]Index rebuild failed: {e} — run `g index` manually.[/yellow]")
