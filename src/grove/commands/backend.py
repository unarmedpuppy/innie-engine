"""Backend management commands."""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def install(
    name: str = typer.Argument(..., help="Backend name (claude-code, opencode, cursor)"),
):
    """Install grove hooks into a backend."""
    from grove.backends.registry import get_backend

    backend = get_backend(name)
    hooks_dir = Path(__file__).parent.parent / "hooks"
    backend.install_hooks(hooks_dir)
    console.print(f"Hooks installed for [bold]{name}[/bold]")


def list_backends():
    """Show detected and installed backends."""
    from grove.backends.registry import discover_backends

    backends = discover_backends()

    table = Table(title="Backends")
    table.add_column("Name")
    table.add_column("Detected")
    table.add_column("Hooks Installed")

    for bname, cls in backends.items():
        instance = cls()
        detected = instance.detect()
        hooks = instance.check_hooks()
        all_installed = all(hooks.values()) if hooks else False

        table.add_row(
            bname,
            "[green]yes[/green]" if detected else "[dim]no[/dim]",
            "[green]yes[/green]" if all_installed else "[dim]no[/dim]",
        )

    console.print(table)


def uninstall(
    name: str = typer.Argument(..., help="Backend name (claude-code, opencode, cursor)"),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation"),
):
    """Remove grove hooks from a backend."""
    from grove.backends.registry import get_backend

    backend = get_backend(name)
    hooks = backend.check_hooks()
    installed = [event for event, ok in hooks.items() if ok]

    if not installed:
        console.print(f"[dim]No grove hooks installed for {name}.[/dim]")
        return

    console.print(f"  Hooks to remove from [bold]{name}[/bold]: {', '.join(installed)}")
    if not yes and not typer.confirm("  Remove?", default=False):
        raise typer.Abort()

    backend.uninstall_hooks()
    console.print(f"  [green]✓[/green] Hooks removed from [bold]{name}[/bold].")


def check(
    name: str = typer.Argument("claude-code", help="Backend to check"),
):
    """Verify hook health for a backend."""
    from grove.backends.registry import get_backend

    backend = get_backend(name)
    hooks = backend.check_hooks()

    if not hooks:
        console.print(f"[dim]No hooks defined for {name}[/dim]")
        return

    all_ok = True
    for event, installed in hooks.items():
        status = "[green]✓[/green]" if installed else "[red]✗[/red]"
        console.print(f"  {status} {event}")
        if not installed:
            all_ok = False

    if not all_ok:
        console.print(f"\nRun: [bold]g backend install {name}[/bold]")
