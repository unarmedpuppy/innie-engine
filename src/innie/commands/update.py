"""innie update — upgrade innie-engine from its configured install source."""

import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

from innie.core.config import get

console = Console()


def update(
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation and index rebuild prompt"),
):
    """Upgrade innie-engine from its configured install source.

    Install source is set during `innie init` and stored in config.toml
    under [update]. Edit it manually if you switch from Gitea to GitHub or
    change your local clone path.
    """
    source = get("update.source", "")
    installer = get("update.installer", "uv")

    if not source:
        console.print("[red]No update source configured.[/red]")
        console.print("  Set it in ~/.innie/config.toml:")
        console.print("  [dim][update]")
        console.print("  source = \"git+ssh://gitea.server.unarmedpuppy.com:2223/homelab/innie-engine.git\"[/dim]")
        console.print("  Or re-run: [bold]innie init[/bold]")
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
        _prompt_reindex(yes)
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
    _prompt_reindex(yes)


def _prompt_reindex(yes: bool) -> None:
    console.print("\n  [bold]Index rebuild recommended[/bold]")
    console.print("  Chunk configuration may have changed. Old chunks may be stale.")
    if yes or typer.confirm("  Run `innie index` now?", default=True):
        console.print()
        result = subprocess.run(["innie", "index"], text=True)
        if result.returncode != 0:
            console.print("[yellow]Index rebuild failed — run `innie index` manually.[/yellow]")
        else:
            console.print("  [green]✓[/green] Index rebuilt.")
