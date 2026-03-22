"""innie launch — launch an agent in a tmux session (or directly if tmux unavailable).

Behavior:
  - tmux available, not in session → create/attach session named <agent>
  - tmux available, already in session → create new window named <agent>
  - tmux unavailable → exec claude directly

Modes:
  default   — use Anthropic oauth/API as-is (no overrides)
  claude    — inject ANTHROPIC_BASE_URL + ANTHROPIC_OAUTH_TOKEN from .env
              for routing through the local Anthropic proxy service
"""

import os
import shlex
import shutil
import subprocess
import sys
from typing import Optional

import typer
from rich.console import Console

from innie.core import paths
from innie.core.agent_env import load_agent_env
from innie.core.profile import load_profile

console = Console()

# Keys that must be present in the merged env for each mode.
# These are warnings, not hard failures — the launch proceeds regardless.
ENV_SCHEMA: dict[str, list[str]] = {
    "shared": [
        "INNIE_HEARTBEAT_API_KEY",
        "GITEA_TOKEN",
    ],
    "agent": [
        "MATTERMOST_BOT_TOKEN",
        "LLM_ROUTER_API_KEY",
        "LLM_ROUTER_URL",
    ],
    "claude": [
        "ANTHROPIC_BASE_URL",
        "CLAUDE_PROXY_TOKEN",
    ],
}


def _validate_env(agent: str, merged: dict[str, str], mode: str) -> list[str]:
    """Check required keys. Returns list of missing key warnings (strings)."""
    from innie.core.agent_env import load_shared_env

    shared = load_shared_env()
    warnings = []

    for key in ENV_SCHEMA["shared"]:
        if key not in shared:
            warnings.append(f"[shared] {key} missing from ~/.innie/.env")

    agent_env_path = paths.env_file(agent)
    if agent_env_path.exists():
        from innie.core.agent_env import _parse_env_file
        agent_only = _parse_env_file(agent_env_path)
    else:
        agent_only = {}

    for key in ENV_SCHEMA["agent"]:
        if key not in merged:
            warnings.append(f"[{agent}] {key} missing from agent or shared .env")

    if mode == "claude":
        for key in ENV_SCHEMA["claude"]:
            if key not in merged:
                warnings.append(f"[claude mode] {key} missing — needed for local proxy routing")

    return warnings


def _build_claude_cmd(agent: str) -> list[str]:
    """Build the claude CLI invocation for this agent (without env vars)."""
    profile = load_profile(agent)
    cc = profile.backend_config or {}

    cmd = ["claude"]

    model = cc.get("model")
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
    env: dict[str, str] = {"INNIE_AGENT": agent}

    # Pass through all agent env vars
    env.update(merged)

    if mode == "claude":
        # Anthropic proxy — routes through homelab proxy service using oauth token
        env["ANTHROPIC_BASE_URL"] = merged.get("ANTHROPIC_BASE_URL", "http://localhost:9292")
        if token := merged.get("CLAUDE_PROXY_TOKEN"):
            env["ANTHROPIC_OAUTH_TOKEN"] = token
        env.pop("ANTHROPIC_API_KEY", None)
    else:
        # Default — route through llm-proxy (localhost:9292 unless overridden in .env)
        # The proxy strips Claude's auth and injects the router key before
        # forwarding to the LLM router. No auth conflict this way.
        env["ANTHROPIC_BASE_URL"] = merged.get("ANTHROPIC_BASE_URL", "http://localhost:9292")
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_OAUTH_TOKEN", None)

    return env


def _exec_direct(cmd: list[str], env: dict[str, str]) -> None:
    """Replace current process with claude (for the no-tmux path).

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


def _tmux_inner_cmd(agent: str, mode: str) -> str:
    """Build the shell command tmux will run inside the new window/session.

    Env vars are passed via tmux -e flags, not embedded in the command string,
    so multiline values (private keys etc.) don't break shell parsing.
    """
    parts = [f"innie launch {shlex.quote(agent)}"]
    if mode != "default":
        parts.append(f"--mode {shlex.quote(mode)}")
    # Keep the window alive after claude exits so the user can see output
    return " ".join(parts) + "; exec $SHELL"


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
):
    """Launch an agent in a tmux session (creates or attaches). Falls back to direct exec if tmux unavailable."""
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
    cmd = _build_claude_cmd(agent)

    no_tmux = (
        os.environ.get("INNIE_NO_TMUX")
        or not shutil.which("tmux")
        or os.environ.get("TERM", "").startswith("xterm-ghostty")
    )

    if no_tmux:
        # Direct exec — replaces this process
        _exec_direct(cmd, env)
        return  # unreachable

    in_tmux = bool(os.environ.get("TMUX"))
    inner = _tmux_inner_cmd(agent, mode)

    if in_tmux:
        # Already in tmux — open new window
        # Pass INNIE_NO_TMUX via -e so multiline env vars don't break shell parsing
        os.execlp("tmux", "tmux", "new-window", "-n", agent, "-e", "INNIE_NO_TMUX=1", inner)
    else:
        # Outside tmux — create session if needed, then attach
        exists = subprocess.run(
            ["tmux", "has-session", "-t", agent],
            capture_output=True,
        ).returncode == 0

        if not exists:
            subprocess.run(
                ["tmux", "new-session", "-d", "-s", agent, "-e", "INNIE_NO_TMUX=1", inner],
                check=True,
            )

        os.execlp("tmux", "tmux", "attach-session", "-t", agent)


def env_check(
    agent: Optional[str] = typer.Argument(None, help="Agent name (default: all agents)"),
    mode: str = typer.Option("default", "--mode", "-m", help="Check for mode: default | claude"),
):
    """Validate required env vars across shared and agent .env files."""
    from rich.table import Table
    from innie.core.agent_env import load_shared_env, _parse_env_file
    from innie.core.profile import list_agents

    agents_to_check = [agent] if agent else list_agents()
    shared = load_shared_env()

    # Shared checks
    console.print("\n[bold]Shared (~/.innie/.env)[/bold]")
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
