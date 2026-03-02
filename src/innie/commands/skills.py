"""innie skill — list and run built-in skills."""

import json

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
