"""innie skill — list, run, install, show, and remove skills."""

import json
import shutil
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table


def list_skills():
    """List all available skills."""
    from innie.skills.registry import discover_skills

    skills = discover_skills()

    console = Console()
    table = Table(title="Available Skills")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Path", style="dim")

    # Built-in skills always available
    builtins = [
        ("daily", "Create/append to today's journal entry"),
        ("learn", "Create a learning entry in the knowledge base"),
        ("meeting", "Create meeting notes"),
        ("contact", "Create or update a contact entry"),
        ("inbox", "Quick capture to inbox"),
        ("adr", "Create an Architecture Decision Record"),
    ]
    for name, desc in builtins:
        table.add_row(f"/{name}", desc, "(built-in)")

    for name, skill in skills.items():
        table.add_row(f"/{name}", skill.description[:60], str(skill.path))

    console.print(table)


def run_skill(
    name: str = typer.Argument(..., help="Skill name (e.g. daily, learn, inbox)"),
    args: str = typer.Argument("", help="JSON arguments for the skill"),
):
    """Run a built-in skill with JSON arguments."""
    from innie.skills import builtins

    skill_fn = getattr(builtins, name, None)
    if not skill_fn:
        typer.echo(f"Unknown built-in skill: {name}")
        typer.echo("Use 'innie skill list' to see available skills.")
        raise typer.Exit(1)

    kwargs = {}
    if args:
        try:
            kwargs = json.loads(args)
        except json.JSONDecodeError as e:
            typer.echo(f"Invalid JSON arguments: {e}")
            raise typer.Exit(1)

    try:
        result = skill_fn(**kwargs)
        typer.echo(f"Created: {result}")
    except TypeError as e:
        typer.echo(f"Invalid arguments for '{name}': {e}")
        raise typer.Exit(1)


def install_skill(
    source: str = typer.Argument(..., help="Path to skill directory or SKILL.md file"),
    agent: str = typer.Option(None, "--agent", "-a", help="Target agent (default: active agent)"),
):
    """Install a skill from a local path into the active agent's skills directory."""
    from innie.core import paths

    console = Console()
    src = Path(source).expanduser().resolve()

    if src.is_file() and src.name == "SKILL.md":
        src = src.parent
    if not src.is_dir() or not (src / "SKILL.md").exists():
        console.print(f"[red]No SKILL.md found at: {source}[/red]")
        raise typer.Exit(1)

    skills_dir = paths.skills_dir(agent)
    skills_dir.mkdir(parents=True, exist_ok=True)
    dest = skills_dir / src.name

    if dest.exists():
        if not typer.confirm(f"Skill '{src.name}' already installed. Overwrite?"):
            raise typer.Abort()
        shutil.rmtree(dest)

    shutil.copytree(src, dest)
    console.print(f"[green]Installed:[/green] {src.name} → {dest}")


def show_skill(
    name: str = typer.Argument(..., help="Skill name"),
    agent: str = typer.Option(None, "--agent", "-a", help="Agent to look up (default: active)"),
):
    """Print the SKILL.md content for a skill."""
    from innie.skills.registry import get_skill

    console = Console()
    skill = get_skill(name, agent)
    if not skill:
        console.print(f"[red]Skill not found: {name}[/red]")
        raise typer.Exit(1)
    console.print(skill.template)


def remove_skill(
    name: str = typer.Argument(..., help="Skill name to remove"),
    agent: str = typer.Option(None, "--agent", "-a", help="Agent to remove from (default: active)"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Remove a skill from the active agent's skills directory."""
    from innie.core import paths

    console = Console()
    skills_dir = paths.skills_dir(agent)
    dest = skills_dir / name

    if not dest.exists():
        console.print(f"[red]Skill not found: {name}[/red]")
        raise typer.Exit(1)

    if not force and not typer.confirm(f"Remove skill '{name}'?"):
        raise typer.Abort()

    shutil.rmtree(dest)
    console.print(f"[green]Removed:[/green] {name}")
