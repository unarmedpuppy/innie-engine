"""Agent management commands: create, list, delete, switch."""

import shutil

import typer
from rich.console import Console
from rich.table import Table

from grove.core import paths
from grove.core.profile import list_agents as _list_agents
from grove.core.profile import load_profile

console = Console()


def create(
    name: str = typer.Argument(..., help="Agent name"),
    role: str = typer.Option("Work Second Brain", help="Agent role"),
):
    """Create a new agent with scaffolded data/ and state/ directories."""
    if paths.agent_dir(name).exists():
        console.print(f"[red]Agent already exists: {name}[/red]")
        raise typer.Exit(1)

    from grove.commands.init import _create_agent

    _create_agent(name, role)
    console.print(f"Agent [bold]{name}[/bold] created at {paths.agent_dir(name)}")


def list_agents():
    """List all agents with role and stats."""
    agents = _list_agents()
    if not agents:
        console.print("No agents found. Run [bold]innie init[/bold] to get started.")
        return

    active = paths.active_agent()
    table = Table(title="Agents")
    table.add_column("Name")
    table.add_column("Role")
    table.add_column("Active")
    table.add_column("Data Files")
    table.add_column("Sessions")

    for name in agents:
        try:
            profile = load_profile(name)
            data = paths.data_dir(name)
            data_count = len(list(data.rglob("*.md"))) if data.exists() else 0
            sessions = paths.sessions_dir(name)
            session_count = len(list(sessions.glob("*.md"))) if sessions.exists() else 0

            table.add_row(
                name,
                profile.role,
                "[green]✓[/green]" if name == active else "",
                str(data_count),
                str(session_count),
            )
        except Exception:
            table.add_row(name, "?", "✓" if name == active else "", "?", "?")

    console.print(table)


def delete(
    name: str = typer.Argument(..., help="Agent name to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Archive and remove an agent."""
    agent = paths.agent_dir(name)
    if not agent.exists():
        console.print(f"[red]Agent not found: {name}[/red]")
        raise typer.Exit(1)

    if name == paths.active_agent():
        console.print("[red]Cannot delete the active agent. Switch first.[/red]")
        raise typer.Exit(1)

    if not force:
        if not typer.confirm(f"Delete agent '{name}'? This archives data/ but removes state/."):
            raise typer.Abort()

    # Archive data/ before deletion
    archive_dir = paths.home() / "archived" / name
    data = paths.data_dir(name)
    if data.exists():
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(data, archive_dir / "data", dirs_exist_ok=True)
        console.print(f"  Archived data/ to {archive_dir}/data/")

    shutil.rmtree(agent)
    console.print(f"Agent [bold]{name}[/bold] deleted.")


def switch(name: str = typer.Argument(..., help="Agent name to activate")):
    """Set the active agent."""
    if not paths.agent_dir(name).exists():
        console.print(f"[red]Agent not found: {name}[/red]")
        raise typer.Exit(1)

    # Update config.toml
    config_path = paths.config_file()
    if config_path.exists():
        content = config_path.read_text()
        import re

        content = re.sub(r'agent = ".*?"', f'agent = "{name}"', content)
        config_path.write_text(content)

    console.print(f"Active agent: [bold]{name}[/bold]")
