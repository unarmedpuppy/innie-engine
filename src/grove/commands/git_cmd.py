"""Git config commands — toggle auto-commit and auto-push."""

import typer
from rich.console import Console

from grove.core import paths

console = Console()


def _read_config() -> dict:
    try:
        import tomllib

        with open(paths.home() / "config.toml", "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _set_config_value(key: str, value: bool) -> None:
    """Write a true/false value in the [git] section of config.toml."""
    config_path = paths.home() / "config.toml"
    if not config_path.exists():
        console.print("[red]No config.toml found. Run `g init` first.[/red]")
        raise typer.Exit(1)

    content = config_path.read_text()
    old = f"{key} = {'true' if not value else 'false'}"
    new = f"{key} = {'true' if value else 'false'}"

    if old in content:
        config_path.write_text(content.replace(old, new, 1))
    elif f"{key} = " not in content:
        # Key missing — append under [git] section
        lines = content.splitlines()
        out = []
        in_git = False
        inserted = False
        for line in lines:
            out.append(line)
            if line.strip() == "[git]":
                in_git = True
            elif in_git and line.startswith("[") and not inserted:
                out.insert(-1, f"{key} = {'true' if value else 'false'}")
                inserted = True
                in_git = False
        if not inserted:
            out.append(f"{key} = {'true' if value else 'false'}")
        config_path.write_text("\n".join(out) + "\n")
    else:
        console.print(f"[yellow]Could not locate {key} in config.toml — edit manually.[/yellow]")
        raise typer.Exit(1)


def auto_push(
    enable: bool = typer.Option(None, "--enable/--disable", help="Enable or disable auto-push"),
):
    """Toggle auto-push to remote after each heartbeat commit."""
    cfg = _read_config()
    current = cfg.get("git", {}).get("auto_push", False)

    if enable is None:
        # Toggle
        enable = not current

    _set_config_value("auto_push", enable)
    state = "[green]enabled[/green]" if enable else "[dim]disabled[/dim]"
    console.print(f"auto_push {state}")
    if enable:
        console.print("[dim]Heartbeat will push after each commit. Ensure a remote is configured.[/dim]")


def auto_commit(
    enable: bool = typer.Option(None, "--enable/--disable", help="Enable or disable auto-commit"),
):
    """Toggle auto-commit of knowledge base after heartbeat."""
    cfg = _read_config()
    current = cfg.get("git", {}).get("auto_commit", False)

    if enable is None:
        enable = not current

    _set_config_value("auto_commit", enable)
    state = "[green]enabled[/green]" if enable else "[dim]disabled[/dim]"
    console.print(f"auto_commit {state}")


def status():
    """Show current git config (auto_commit, auto_push, remote)."""
    cfg = _read_config().get("git", {})
    commit = cfg.get("auto_commit", False)
    push = cfg.get("auto_push", False)

    def flag(v: bool) -> str:
        return "[green]on[/green]" if v else "[dim]off[/dim]"

    console.print(f"  auto_commit  {flag(commit)}")
    console.print(f"  auto_push    {flag(push)}")
    if push and not commit:
        console.print("  [yellow]![/yellow] auto_push is on but auto_commit is off — push will never trigger")
