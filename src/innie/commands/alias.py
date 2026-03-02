"""Shell alias management."""

import os
from pathlib import Path

import typer
from rich.console import Console

from innie.core import paths
from innie.core.profile import load_profile

console = Console()


def _get_rc_file() -> Path:
    shell = os.environ.get("SHELL", "/bin/zsh")
    if "zsh" in shell:
        return Path.home() / ".zshrc"
    return Path.home() / ".bashrc"


def _build_alias(name: str) -> str:
    """Build a shell alias from the agent's profile.yaml."""
    profile = load_profile(name)
    cc = profile.backend_config or {}

    parts = ["claude"]

    # Model
    model = cc.get("model")
    if model:
        parts.append(f"--model {model}")

    # Permissions
    if profile.permissions == "yolo":
        parts.append("--dangerously-skip-permissions")

    # System prompt injection — assemble SOUL + CONTEXT + user.md
    inject_files = []
    agent_dir = paths.agent_dir(name)
    for f in ["SOUL.md", "CONTEXT.md"]:
        fpath = agent_dir / f
        if fpath.exists():
            inject_files.append(str(fpath))

    user_file = paths.user_file()
    if user_file.exists():
        inject_files.append(str(user_file))

    if inject_files:
        cat_cmd = " ".join(f'"{f}"' for f in inject_files)
        parts.append(f'--append-system-prompt "$(cat {cat_cmd})"')

    cmd = " ".join(parts)
    return f'alias {name}=\'INNIE_AGENT="{name}" {cmd}\''


def add(name: str = typer.Argument(..., help="Agent name to create alias for")):
    """Add a shell alias that launches Claude Code with this agent's identity and memory."""
    if not paths.agent_dir(name).exists():
        console.print(f"[red]Agent not found: {name}[/red]")
        raise typer.Exit(1)

    rc_file = _get_rc_file()
    alias = _build_alias(name)

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
    console.print(f"  [dim]{alias}[/dim]")
    console.print(f"\nRun: [dim]source {rc_file}[/dim]")


def show(name: str = typer.Argument(..., help="Agent name to preview alias for")):
    """Preview the alias command without installing it."""
    if not paths.agent_dir(name).exists():
        console.print(f"[red]Agent not found: {name}[/red]")
        raise typer.Exit(1)

    alias = _build_alias(name)
    console.print(alias)


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
