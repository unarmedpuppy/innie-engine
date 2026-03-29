"""Edit agent identity files — SOUL.md, CONTEXT.md, user.md."""

import typer
from rich.console import Console

from grove.core import paths

console = Console()


def _open_editor(file_path, title: str) -> None:
    from grove.tui.detect import is_interactive

    if is_interactive():
        from grove.tui.apps.editor import edit_file

        result = edit_file(file_path, title=title)
        if result is None:
            console.print("[dim]Discarded.[/dim]")
        else:
            console.print(f"[green]✓[/green] Saved {file_path}")
    else:
        # Non-interactive: open $EDITOR
        import os
        import subprocess

        editor = os.environ.get("EDITOR", "vi")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if not file_path.exists():
            file_path.write_text("")
        subprocess.run([editor, str(file_path)])


def soul(
    agent: str = typer.Option(None, "--agent", "-a", help="Agent name (defaults to active agent)"),
):
    """Edit SOUL.md — who this agent is."""
    agent = agent or paths.active_agent()
    agent_dir = paths.agent_dir(agent)
    if not agent_dir.exists():
        console.print(f"[red]Agent not found: {agent}[/red]")
        raise typer.Exit(1)
    _open_editor(agent_dir / "SOUL.md", title=f"SOUL.md — {agent}")


def context(
    agent: str = typer.Option(None, "--agent", "-a", help="Agent name (defaults to active agent)"),
):
    """Edit CONTEXT.md — working memory."""
    agent = agent or paths.active_agent()
    agent_dir = paths.agent_dir(agent)
    if not agent_dir.exists():
        console.print(f"[red]Agent not found: {agent}[/red]")
        raise typer.Exit(1)
    _open_editor(agent_dir / "CONTEXT.md", title=f"CONTEXT.md — {agent}")


def user():
    """Edit user.md — your identity shared across all agents."""
    file_path = paths.user_file()
    _open_editor(file_path, title="user.md")
