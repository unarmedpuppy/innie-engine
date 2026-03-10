"""innie env — manage per-agent secrets via a gitignored .env file."""

import typer
from rich.console import Console
from rich.table import Table

from innie.core import paths
from innie.core.agent_env import get_env_var, load_agent_env, set_env_var, unset_env_var

console = Console()


def env_set(
    key: str = typer.Argument(..., help="Variable name"),
    value: str = typer.Argument(..., help="Value to store"),
    agent: str = typer.Option("", "--agent", "-a", help="Agent name (default: active)"),
):
    """Set a secret env var for an agent."""
    target = agent or paths.active_agent()
    set_env_var(key, value, target)
    console.print(f"[green]✓[/green] Set [bold]{key}[/bold] for agent [bold]{target}[/bold]")
    console.print(f"  Stored in: {paths.env_file(target)}")


def env_get(
    key: str = typer.Argument(..., help="Variable name"),
    agent: str = typer.Option("", "--agent", "-a", help="Agent name (default: active)"),
):
    """Get a secret env var for an agent (prints value)."""
    target = agent or paths.active_agent()
    value = get_env_var(key, target)
    if value is None:
        console.print(f"[red]{key} not set for agent {target}[/red]")
        raise typer.Exit(1)
    console.print(value)


def env_list(
    agent: str = typer.Option("", "--agent", "-a", help="Agent name (default: active)"),
):
    """List all env vars for an agent (values masked)."""
    target = agent or paths.active_agent()
    env = load_agent_env(target)

    if not env:
        env_path = paths.env_file(target)
        if not env_path.exists():
            console.print(f"No .env file for agent [bold]{target}[/bold]")
            console.print(f"  Create one with: innie env set KEY VALUE")
        else:
            console.print(f"[dim].env file exists but is empty[/dim]")
        return

    table = Table(title=f"Agent: {target}")
    table.add_column("Key", style="bold")
    table.add_column("Value")

    for key, value in sorted(env.items()):
        masked = value[:4] + "***" + value[-4:] if len(value) > 8 else "***"
        table.add_row(key, masked)

    console.print(table)
    console.print(f"\n[dim]File: {paths.env_file(target)}[/dim]")


def env_unset(
    key: str = typer.Argument(..., help="Variable name to remove"),
    agent: str = typer.Option("", "--agent", "-a", help="Agent name (default: active)"),
):
    """Remove a secret env var for an agent."""
    target = agent or paths.active_agent()
    removed = unset_env_var(key, target)
    if removed:
        console.print(f"[green]✓[/green] Removed [bold]{key}[/bold] from agent [bold]{target}[/bold]")
    else:
        console.print(f"[yellow]{key} not found for agent {target}[/yellow]")
        raise typer.Exit(1)
