"""grove launch — exec claude directly as this agent.

Always replaces the current process with claude (no tmux wrapping).

Modes:
  default   — route through LLM router via ANTHROPIC_BASE_URL + ANTHROPIC_API_KEY from agent .env
  claude    — use Claude Code native OAuth (clears ANTHROPIC_BASE_URL + ANTHROPIC_API_KEY)
              requires `claude login` on the host machine
"""

import os
import shlex
import subprocess
from typing import Optional

import typer
from rich.console import Console

from grove.core import paths
from grove.core.agent_env import load_agent_env
from grove.core.profile import load_profile

console = Console()

# Keys that must be present in the merged env for each mode.
# These are warnings, not hard failures — the launch proceeds regardless.
ENV_SCHEMA: dict[str, list[str]] = {
    "shared": [
        "GITEA_TOKEN",
    ],
    "agent": [
        "MATTERMOST_BOT_TOKEN",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
    ],
    "claude": [],  # no required keys — uses Claude Code native OAuth
}


def _validate_env(agent: str, merged: dict[str, str], mode: str) -> list[str]:
    """Check required keys. Returns list of missing key warnings (strings)."""
    from grove.core.agent_env import load_shared_env

    shared = load_shared_env()
    warnings = []

    for key in ENV_SCHEMA["shared"]:
        if key not in shared:
            warnings.append(f"[shared] {key} missing from ~/.grove/.env")

    for key in ENV_SCHEMA["agent"]:
        if key not in merged:
            warnings.append(f"[{agent}] {key} missing from agent or shared .env")

    return warnings


def _build_claude_cmd(agent: str, model_override: str | None = None) -> list[str]:
    """Build the claude CLI invocation for this agent (without env vars)."""
    profile = load_profile(agent)
    cc = profile.backend_config or {}

    cmd = ["claude"]

    model = model_override or cc.get("model")
    if model:
        cmd += ["--model", model]

    cmd.append("--dangerously-skip-permissions")

    inject_files = []
    agent_dir = paths.agent_dir(agent)
    for f in ["SOUL.md", "CONTEXT.md"]:
        fpath = agent_dir / f
        if fpath.exists():
            inject_files.append(str(fpath))

    user_file = paths.user_file()
    if user_file.exists():
        inject_files.append(str(user_file))

    if inject_files:
        cat_cmd = "cat " + " ".join(shlex.quote(f) for f in inject_files)
        cmd += ["--append-system-prompt", f"$({cat_cmd})"]

    return cmd


def _build_env(agent: str, mode: str) -> dict[str, str]:
    """Build the env dict to inject when launching claude."""
    merged = load_agent_env(agent)
    env: dict[str, str] = {"GROVE_AGENT": agent}

    # Pass through all agent env vars
    env.update(merged)

    if mode == "claude":
        # Native OAuth — clear any routing overrides so Claude Code uses its stored login
        env.pop("ANTHROPIC_BASE_URL", None)
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_OAUTH_TOKEN", None)
    else:
        # Default — use ANTHROPIC_BASE_URL and ANTHROPIC_API_KEY from agent .env.
        env["ANTHROPIC_BASE_URL"] = merged.get("ANTHROPIC_BASE_URL", "http://localhost:9292")
        if api_key := merged.get("ANTHROPIC_API_KEY"):
            env["ANTHROPIC_API_KEY"] = api_key
        else:
            env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_OAUTH_TOKEN", None)

    return env


def _exec_direct(cmd: list[str], env: dict[str, str]) -> None:
    """Replace current process with claude.

    Sets env vars directly in os.environ (safe for multiline values like private keys),
    then execs sh to handle $(...) subshell expansion in --append-system-prompt.
    """
    for k, v in env.items():
        os.environ[k] = v
    # Always start claude in ~/workspace to avoid "do you trust this folder" prompts
    workspace = os.path.expanduser("~/workspace")
    if os.path.isdir(workspace):
        os.chdir(workspace)
    # Properly quote all args. $(...) subshells are double-quoted to allow shell
    # expansion while preventing word-splitting on multiline output (SOUL.md etc.)
    parts = []
    for c in cmd:
        if c.startswith("$("):
            parts.append(f'"{c}"')
        else:
            parts.append(shlex.quote(c))
    os.execlp("sh", "sh", "-c", " ".join(parts))


def apply_mode_env(agent: str, mode: str) -> None:
    """Inject mode-specific env vars into os.environ in-process.

    Use this in commands (heartbeat, index) that need proxy routing
    without replacing the process. Same logic as launch --mode.
    """
    env = _build_env(agent, mode)
    for k, v in env.items():
        os.environ[k] = v


def launch(
    agent: str = typer.Argument(..., help="Agent name to launch"),
    mode: str = typer.Option("default", "--mode", "-m", help="Launch mode: default | claude"),
    model: Optional[str] = typer.Option(None, "--model", "-M", help="Model override (e.g. homelab/auto, claude-sonnet-4-6)"),
):
    """Launch an agent by exec-ing claude directly (replaces current process)."""
    if not paths.agent_dir(agent).exists():
        console.print(f"[red]Agent not found: {agent}[/red]")
        raise typer.Exit(1)

    if mode not in ("default", "claude"):
        console.print(f"[red]Unknown mode: {mode}. Use 'default' or 'claude'.[/red]")
        raise typer.Exit(1)

    # Build env and validate
    merged = load_agent_env(agent)
    warnings = _validate_env(agent, merged, mode)
    for w in warnings:
        console.print(f"[yellow]⚠ {w}[/yellow]")

    env = _build_env(agent, mode)
    cmd = _build_claude_cmd(agent, model_override=model)

    _exec_direct(cmd, env)


def env_check(
    agent: Optional[str] = typer.Argument(None, help="Agent name (default: all agents)"),
    mode: str = typer.Option("default", "--mode", "-m", help="Check for mode: default | claude"),
):
    """Validate required env vars across shared and agent .env files."""
    from grove.core.agent_env import load_shared_env, _parse_env_file
    from grove.core.profile import list_agents

    agents_to_check = [agent] if agent else list_agents()
    shared = load_shared_env()

    # Shared checks
    console.print("\n[bold]Shared (~/.grove/.env)[/bold]")
    for key in ENV_SCHEMA["shared"]:
        status = "[green]✓[/green]" if key in shared else "[red]✗ MISSING[/red]"
        console.print(f"  {status}  {key}")

    if mode == "claude":
        console.print("\n[bold]Claude mode (shared)[/bold]")
        for key in ENV_SCHEMA["claude"]:
            status = "[green]✓[/green]" if key in shared else "[yellow]? check agent .env[/yellow]"
            console.print(f"  {status}  {key}")

    # Per-agent checks
    for a in agents_to_check:
        merged = load_agent_env(a)
        console.print(f"\n[bold]Agent: {a}[/bold]")

        for key in ENV_SCHEMA["agent"]:
            status = "[green]✓[/green]" if key in merged else "[red]✗ MISSING[/red]"
            source = ""
            agent_env = _parse_env_file(paths.env_file(a))
            if key in agent_env:
                source = " [dim](agent)[/dim]"
            elif key in shared:
                source = " [dim](shared)[/dim]"
            console.print(f"  {status}  {key}{source}")

        if mode == "claude":
            for key in ENV_SCHEMA["claude"]:
                status = "[green]✓[/green]" if key in merged else "[red]✗ MISSING[/red]"
                console.print(f"  {status}  {key} [dim](claude mode)[/dim]")
