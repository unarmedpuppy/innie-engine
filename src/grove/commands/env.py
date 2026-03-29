"""grove env — manage agent secrets via a two-tier .env system.

~/.grove/.env                — shared across all agents (--shared flag)
~/.grove/agents/<name>/.env  — agent-specific (default)
"""

import typer
from rich.console import Console
from rich.table import Table

from grove.core import paths
from grove.core.agent_env import get_env_var, load_agent_env, load_shared_env, set_env_var, unset_env_var

console = Console()


def env_set(
    key: str = typer.Argument(..., help="Variable name"),
    value: str = typer.Argument(..., help="Value to store"),
    agent: str = typer.Option("", "--agent", "-a", help="Agent name (default: active)"),
    shared: bool = typer.Option(False, "--shared", "-s", help="Write to shared ~/.grove/.env instead"),
):
    """Set a secret env var. Default: agent-specific. Use --shared for cross-agent secrets."""
    if shared:
        set_env_var(key, value, shared=True)
        console.print(f"[green]✓[/green] Set [bold]{key}[/bold] (shared)")
        console.print(f"  Stored in: {paths.shared_env_file()}")
    else:
        target = agent or paths.active_agent()
        set_env_var(key, value, target)
        console.print(f"[green]✓[/green] Set [bold]{key}[/bold] for agent [bold]{target}[/bold]")
        console.print(f"  Stored in: {paths.env_file(target)}")


def env_get(
    key: str = typer.Argument(..., help="Variable name"),
    agent: str = typer.Option("", "--agent", "-a", help="Agent name (default: active)"),
):
    """Get a secret env var — checks merged (shared + agent-specific) env."""
    target = agent or paths.active_agent()
    value = get_env_var(key, target)
    if value is None:
        console.print(f"[red]{key} not set for agent {target} or in shared .env[/red]")
        raise typer.Exit(1)
    console.print(value)


def env_list(
    agent: str = typer.Option("", "--agent", "-a", help="Agent name (default: active)"),
    shared: bool = typer.Option(False, "--shared", "-s", help="List only shared ~/.grove/.env"),
):
    """List env vars (values masked). Default: merged view. --shared: shared file only."""
    target = agent or paths.active_agent()

    if shared:
        env = load_shared_env()
        title = "~/.grove/.env (shared)"
        file_path = paths.shared_env_file()
    else:
        env = load_agent_env(target)
        title = f"Agent: {target} (merged)"
        file_path = paths.env_file(target)

    if not env:
        console.print(f"No secrets found")
        console.print(f"  Agent-specific: {paths.env_file(target)}")
        console.print(f"  Shared:         {paths.shared_env_file()}")
        return

    table = Table(title=title)
    table.add_column("Key", style="bold")
    table.add_column("Value")

    for key, value in sorted(env.items()):
        masked = value[:4] + "***" + value[-4:] if len(value) > 8 else "***"
        table.add_row(key, masked)

    console.print(table)
    console.print(f"\n[dim]File: {file_path}[/dim]")


def env_unset(
    key: str = typer.Argument(..., help="Variable name to remove"),
    agent: str = typer.Option("", "--agent", "-a", help="Agent name (default: active)"),
    shared: bool = typer.Option(False, "--shared", "-s", help="Remove from shared ~/.grove/.env instead"),
):
    """Remove a secret env var from agent-specific or shared .env."""
    if shared:
        removed = unset_env_var(key, shared=True)
        if removed:
            console.print(f"[green]✓[/green] Removed [bold]{key}[/bold] from shared .env")
        else:
            console.print(f"[yellow]{key} not found in shared .env[/yellow]")
            raise typer.Exit(1)
    else:
        target = agent or paths.active_agent()
        removed = unset_env_var(key, target)
        if removed:
            console.print(f"[green]✓[/green] Removed [bold]{key}[/bold] from agent [bold]{target}[/bold]")
        else:
            console.print(f"[yellow]{key} not found for agent {target}[/yellow]")
            raise typer.Exit(1)
