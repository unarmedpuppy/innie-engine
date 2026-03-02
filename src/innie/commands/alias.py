"""Shell alias management."""

import os
from pathlib import Path

import typer
from rich.console import Console

console = Console()


def _get_rc_file() -> Path:
    shell = os.environ.get("SHELL", "/bin/zsh")
    if "zsh" in shell:
        return Path.home() / ".zshrc"
    return Path.home() / ".bashrc"


def _alias_line(name: str) -> str:
    return f"alias {name}='INNIE_AGENT=\"{name}\" claude'"


def add(name: str = typer.Argument(..., help="Agent name to create alias for")):
    """Add a shell alias that launches Claude Code with this agent's context."""
    from innie.core import paths

    if not paths.agent_dir(name).exists():
        console.print(f"[red]Agent not found: {name}[/red]")
        raise typer.Exit(1)

    rc_file = _get_rc_file()
    alias = _alias_line(name)

    if rc_file.exists():
        content = rc_file.read_text()
        # Remove existing alias for this name
        prefix = f"alias {name}="
        lines = [ln for ln in content.split("\n") if not ln.strip().startswith(prefix)]
        lines.append(alias)
        rc_file.write_text("\n".join(lines))
    else:
        rc_file.write_text(alias + "\n")

    console.print(f"Added alias [bold]{name}[/bold] to {rc_file}")
    console.print(f"Run: [dim]source {rc_file}[/dim]")


def remove(name: str = typer.Argument(..., help="Alias name to remove")):
    """Remove a shell alias."""
    rc_file = _get_rc_file()
    if not rc_file.exists():
        console.print("No shell RC file found.")
        return

    content = rc_file.read_text()
    prefix = f"alias {name}="
    lines = [ln for ln in content.split("\n") if not ln.strip().startswith(prefix)]
    rc_file.write_text("\n".join(lines))
    console.print(f"Removed alias [bold]{name}[/bold] from {rc_file}")
