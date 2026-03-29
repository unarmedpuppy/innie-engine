"""World directory sync — commit and push the grove-world Gitea repo."""

import subprocess
from datetime import datetime

import typer
from rich.console import Console

from grove.core import paths

console = Console()


def sync(
    pull: bool = typer.Option(False, "--pull", help="Pull latest from remote instead of pushing"),
    message: str = typer.Option("", "--message", "-m", help="Custom commit message"),
) -> None:
    """Sync the world directory to/from Gitea.

    Default: commit any changes and push.
    With --pull: pull latest from remote (for server/WSL machines).
    """
    from grove.core.config import load_config
    cfg = load_config()
    world = cfg.get("defaults", {}).get("world")

    if not world:
        console.print("[red]defaults.world not configured in config.toml[/red]")
        raise typer.Exit(1)

    world_path = paths.world_dir()
    if not world_path.exists():
        console.print(f"[red]World dir not found: {world_path}[/red]")
        raise typer.Exit(1)

    if pull:
        result = subprocess.run(
            ["git", "pull", "--rebase", "--quiet"],
            cwd=world_path, capture_output=True, text=True
        )
        if result.returncode == 0:
            console.print("[green]✓[/green] World dir pulled from remote")
        else:
            console.print(f"[red]Pull failed:[/red] {result.stderr.strip()}")
            raise typer.Exit(1)
        return

    # Push path: add, check for changes, commit, push
    subprocess.run(["git", "add", "-A"], cwd=world_path, capture_output=True)

    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=world_path, capture_output=True
    )
    if diff.returncode == 0:
        console.print("[dim]World dir: nothing to commit[/dim]")
        return

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = message or f"sync {ts}"
    commit = subprocess.run(
        ["git", "commit", "-m", msg, "--author=Oak <oak@innie.local>"],
        cwd=world_path, capture_output=True, text=True
    )
    if commit.returncode != 0:
        console.print(f"[red]Commit failed:[/red] {commit.stderr.strip()}")
        raise typer.Exit(1)

    push = subprocess.run(
        ["git", "push", "origin", "main", "--quiet"],
        cwd=world_path, capture_output=True, text=True
    )
    if push.returncode == 0:
        console.print(f"[green]✓[/green] World dir synced: {msg}")
    else:
        console.print(f"[red]Push failed:[/red] {push.stderr.strip()}")
        raise typer.Exit(1)
