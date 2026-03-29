"""Shell alias management."""

import os
from pathlib import Path

import typer
from rich.console import Console

from grove.core import paths
from grove.core.profile import load_profile

console = Console()


def _get_rc_file() -> Path:
    shell = os.environ.get("SHELL", "/bin/zsh")
    if "zsh" in shell:
        return Path.home() / ".zshrc"
    return Path.home() / ".bashrc"


def build_context(agent: str) -> str:
    """Build context for pre-launch injection: SOUL + CONTEXT + session status block."""
    from datetime import date

    parts = []
    agent_dir = paths.agent_dir(agent)
    for f in ["SOUL.md", "CONTEXT.md"]:
        fpath = agent_dir / f
        if fpath.exists():
            parts.append(fpath.read_text())

    user_file = paths.user_file()
    if user_file.exists():
        parts.append(user_file.read_text())

    status_lines = [f"Date: {date.today().isoformat()}"]
    try:
        from grove.core.search import index_status, open_db

        db_path = paths.index_db(agent)
        if db_path.exists():
            conn = open_db(db_path)
            stats = index_status(conn)
            conn.close()
            status_lines.append(f"Index: {stats['files']} files, {stats['chunks']} chunks")
    except Exception:
        pass

    try:
        journal_dir = paths.journal_dir(agent)
        if journal_dir.exists():
            count = len(list(journal_dir.rglob("*.md")))
            status_lines.append(f"Journal entries: {count}")
    except Exception:
        pass

    parts.append("## Session Status\n\n" + "\n".join(status_lines))
    return "\n\n---\n\n".join(parts)


def _build_alias(name: str) -> str:
    """Build a shell alias from the agent's profile.yaml."""
    profile = load_profile(name)
    cc = profile.backend_config or {}

    parts = ["claude"]

    # Model
    model = cc.get("model")
    if model:
        parts.append(f"--model {model}")

    # Always accept permissions for unattended use
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

    console.print(f"\n[dim]Generated alias:[/dim]")
    console.print(f"  {alias}\n")

    final = typer.prompt(
        "Press Enter to install as-is, or paste an edited alias",
        default=alias,
        show_default=False,
    )

    prefix = f"alias {name}="
    if rc_file.exists():
        content = rc_file.read_text()
        lines = [ln for ln in content.split("\n") if not ln.strip().startswith(prefix)]
        lines.append(final)
        rc_file.write_text("\n".join(lines))
    else:
        rc_file.write_text(final + "\n")

    console.print(f"Added alias [bold]{name}[/bold] to {rc_file}")
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


def generate_all():
    """Output shell aliases for all agents — pipe into source or append to shell RC.

    Usage in ~/.zshrc:
        source <(g alias generate-all)

    Each agent gets two aliases:
        <agent>         → g launch <agent>              (default Anthropic oauth)
        <agent>-claude  → g launch <agent> --mode claude (local proxy routing)
    """
    from grove.core.profile import list_agents

    # Only generate aliases for agents that have a SOUL.md (real agents, not stubs)
    # Exclude "innie" — it would shadow the innie CLI itself
    agents = [a for a in list_agents() if (paths.agent_dir(a) / "SOUL.md").exists() and a != "innie"]
    lines = ["# grove agent aliases — generated by `g alias generate-all`"]
    for name in agents:
        lines.append(f"alias {name}='g launch {name}'")
        lines.append(f"alias {name}-claude='g launch {name} --mode claude'")

    print("\n".join(lines))
