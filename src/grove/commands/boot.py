"""innie boot — full startup sequence: version check, heartbeat, serve, health."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import typer
from rich.console import Console

from grove.core import paths
from grove.core.config import get

console = Console()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _serve_port() -> int:
    return int(os.environ.get("INNIE_SERVE_PORT", get("serve.port", 8013)))


def _serve_label(agent: str) -> str:
    return f"ai.grove.serve.{agent}"


def _health_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/health"


def _hit_health(port: int) -> dict | None:
    try:
        import httpx

        resp = httpx.get(_health_url(port), timeout=4.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def _check_result(label: str, ok: bool, note: str = "") -> bool:
    icon = "[green]✓[/green]" if ok else "[red]✗[/red]"
    suffix = f"  [dim]{note}[/dim]" if note else ""
    console.print(f"  {icon} {label}{suffix}")
    return ok


# ── Steps ─────────────────────────────────────────────────────────────────────


def _step_version_check(agent: str, force_update: bool) -> str:
    """Check installed version vs source. Update if behind. Returns current version."""
    from grove import __version__ as installed_ver

    console.print(f"\n[bold]1. Version[/bold]  (installed: {installed_ver})")

    source = get("update.source", "")
    if not source:
        console.print("  [dim]No update.source in config — skipping version check.[/dim]")
        return installed_ver

    expanded = str(Path(source).expanduser().resolve()) if not source.startswith("git+") else None

    # For local editable installs: compare pyproject.toml version vs installed
    if expanded:
        toml_path = Path(expanded) / "pyproject.toml"
        source_ver: str | None = None
        if toml_path.exists():
            for line in toml_path.read_text().splitlines():
                if line.strip().startswith("version"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        source_ver = parts[1].strip().strip('"').strip("'")
                        break

        if source_ver and source_ver != installed_ver:
            console.print(f"  [yellow]![/yellow] Source has {source_ver}, installed has {installed_ver} — updating...")
            needs_update = True
        elif force_update:
            console.print("  Forcing reinstall (--force-update)...")
            needs_update = True
        else:
            _check_result(f"Up to date ({installed_ver})", True)
            return installed_ver

        if needs_update:
            result = subprocess.run(
                ["uv", "tool", "install", "-e", f"{expanded}[serve]", "--reinstall"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                # Re-read version after reinstall
                try:
                    from importlib.metadata import version as meta_ver

                    new_ver = meta_ver("grove")
                except Exception:
                    new_ver = installed_ver
                _check_result(f"Updated to {new_ver}", True)
                return new_ver
            else:
                console.print(f"  [red]✗[/red] Update failed: {result.stderr.strip()[:120]}")
                return installed_ver
    else:
        # Remote source — run uv tool upgrade
        needs_update = force_update
        if not needs_update:
            console.print("  [dim]Remote source — run `g update` for full upgrade check.[/dim]")
            _check_result(f"Version {installed_ver} (remote source, not checked)", True)
            return installed_ver

        result = subprocess.run(
            ["uv", "tool", "upgrade", "grove", "--reinstall"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            _check_result("Upgrade complete", True)
        else:
            console.print(f"  [red]✗[/red] Upgrade failed: {result.stderr.strip()[:120]}")

    return installed_ver


def _step_heartbeat_scheduler() -> None:
    """Ensure heartbeat scheduler is installed."""
    console.print("\n[bold]2. Heartbeat Scheduler[/bold]")

    if sys.platform == "darwin":
        plist_path = (
            Path.home() / "Library" / "LaunchAgents" / "com.grove.heartbeat.plist"
        )
        if plist_path.exists():
            _check_result("Heartbeat launchd plist present", True)
        else:
            console.print("  [yellow]![/yellow] Plist missing — installing...")
            from grove.commands.init import _install_scheduler

            _install_scheduler()
            _check_result("Heartbeat launchd plist installed", plist_path.exists())
    else:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        has_cron = result.returncode == 0 and "innie" in result.stdout
        if has_cron:
            _check_result("Heartbeat cron present", True)
        else:
            console.print("  [yellow]![/yellow] Cron missing — installing...")
            from grove.commands.init import _install_scheduler

            _install_scheduler()
            result2 = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
            _check_result("Heartbeat cron installed", "innie" in result2.stdout)


def _step_skills_symlink() -> None:
    """Ensure ~/.claude/skills → ~/.innie/skills/ symlink is in place."""
    console.print("\n[bold]3. Skills Symlink[/bold]")
    shared = paths.shared_skills_dir()
    claude_skills = Path.home() / ".claude" / "skills"

    if claude_skills.is_symlink() and claude_skills.resolve() == shared.resolve():
        _check_result(f"~/.claude/skills → {shared}", True)
        return

    try:
        claude_skills.parent.mkdir(parents=True, exist_ok=True)
        if claude_skills.exists() or claude_skills.is_symlink():
            claude_skills.unlink()
        claude_skills.symlink_to(shared)
        _check_result(f"~/.claude/skills → {shared} (created)", True)
    except Exception as e:
        _check_result(f"~/.claude/skills symlink", False, str(e)[:80])


def _step_restart_serve(agent: str, port: int) -> bool:
    """Restart (or start) the serve process. Returns True if serve is up after."""
    console.print("\n[bold]4. Serve / Message Gateways[/bold]")

    if sys.platform != "darwin":
        console.print("  [dim]Non-macOS: serve management not implemented — skip.[/dim]")
        return _hit_health(port) is not None

    label = _serve_label(agent)
    uid = os.getuid()
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"

    if not plist_path.exists():
        console.print(f"  [yellow]![/yellow] No plist at {plist_path} — cannot manage serve.")
        alive = _hit_health(port) is not None
        _check_result(f"Serve reachable on :{port}", alive)
        return alive

    # Try kickstart (restart if running, start if not)
    result = subprocess.run(
        ["launchctl", "kickstart", "-k", f"gui/{uid}/{label}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # May not be loaded yet — try load first
        subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True)
        time.sleep(1.0)
        result2 = subprocess.run(
            ["launchctl", "kickstart", f"gui/{uid}/{label}"],
            capture_output=True,
            text=True,
        )
        if result2.returncode != 0:
            console.print(f"  [yellow]![/yellow] kickstart failed: {result2.stderr.strip()}")

    # Wait up to 8s for serve to come up
    console.print("  Waiting for serve to come back up...")
    for _ in range(16):
        time.sleep(0.5)
        if _hit_health(port) is not None:
            break

    health = _hit_health(port)
    alive = health is not None
    _check_result(f"Serve reachable on :{port}", alive)
    return alive


def _step_run_heartbeat(agent: str, skip: bool) -> None:
    """Run one heartbeat cycle (in-process, non-interactive path)."""
    console.print("\n[bold]5. Heartbeat[/bold]")

    if skip:
        console.print("  [dim]Skipped (--skip-heartbeat).[/dim]")
        return

    # Run as subprocess to avoid re-entrant imports and TUI detection
    g_bin = Path(sys.executable).parent / "g"
    cmd = [str(g_bin), "heartbeat", "run"] if g_bin.exists() else [sys.executable, "-m", "grove.cli", "heartbeat", "run"]
    result = subprocess.run(
        cmd,
        capture_output=False,  # let output stream through
        text=True,
        env={**os.environ, "INNIE_AGENT": agent, "TERM": "dumb"},
    )
    if result.returncode != 0:
        console.print("  [yellow]![/yellow] Heartbeat exited non-zero.")


def _step_health_check(agent: str, port: int) -> None:
    """Full health check: fleet registration, channels, env vars, context files."""
    console.print("\n[bold]6. Health Check[/bold]")

    health = _hit_health(port)
    if health is None:
        console.print(f"  [red]✗[/red] Cannot reach serve on :{port} — skipping health checks.")
        return

    # Version
    _check_result(f"Version: {health.get('version', '?')}", True)

    # Uptime
    uptime = health.get("uptime_seconds", 0)
    _check_result(f"Uptime: {uptime}s", uptime >= 0)

    # Channels
    channels = health.get("channels", [])
    if channels:
        for ch in channels:
            name = ch.get("name", "?")
            enabled = ch.get("enabled", False)
            connected = ch.get("connected", False)
            if not enabled:
                console.print(f"  [dim]─[/dim] Channel {name}: disabled")
            else:
                _check_result(f"Channel {name}: connected", connected)
    else:
        console.print("  [dim]─[/dim] No channels configured")

    # Fleet gateway registration
    fleet_url = os.environ.get("INNIE_FLEET_URL", "")
    if fleet_url:
        try:
            import httpx

            resp = httpx.get(f"{fleet_url}/api/agents/{agent}", timeout=4.0)
            registered = resp.status_code == 200
            _check_result(f"Fleet gateway registration ({fleet_url})", registered)
        except Exception as e:
            _check_result(f"Fleet gateway reachable ({fleet_url})", False, str(e)[:60])
    else:
        console.print("  [dim]─[/dim] INNIE_FLEET_URL not set — fleet check skipped")

    # Env vars
    console.print("\n  [dim]Env vars (from .env files):[/dim]")
    from grove.core.agent_env import load_agent_env

    env = load_agent_env(agent)

    required_vars = [
        ("MATTERMOST_BOT_TOKEN", "Mattermost auth"),
        ("INNIE_API_TOKEN", "Agent API auth"),
    ]
    # Conditional: check Anthropic key only if no external URL configured
    external_url = get("heartbeat.external_url", "")
    if not external_url:
        required_vars.append(("ANTHROPIC_API_KEY", "LLM provider"))

    for key, label in required_vars:
        val = env.get(key) or os.environ.get(key, "")
        _check_result(f"{label} ({key})", bool(val), "" if val else "not set")

    # Context files
    console.print("\n  [dim]Context files:[/dim]")
    file_checks = [
        (paths.soul_file(agent), "SOUL.md"),
        (paths.context_file(agent), "CONTEXT.md"),
        (paths.profile_file(agent), "profile.yaml"),
        (paths.agent_dir(agent) / "channels.yaml", "channels.yaml"),
        (paths.agent_dir(agent) / "schedule.yaml", "schedule.yaml"),
    ]
    for fpath, label in file_checks:
        _check_result(label, fpath.exists(), str(fpath) if not fpath.exists() else "")

    # Heartbeat state
    hb = health.get("heartbeat", {})
    if hb:
        last_ts = hb.get("last_run_iso", "never")
        _check_result(f"Heartbeat last run: {last_ts}", True)

    console.print()


# ── Entry point ────────────────────────────────────────────────────────────────


def boot(
    skip_heartbeat: bool = typer.Option(False, "--skip-heartbeat", help="Skip running the heartbeat"),
    force_update: bool = typer.Option(False, "--force-update", help="Force reinstall even if version matches"),
    no_restart: bool = typer.Option(False, "--no-restart", help="Skip serve restart"),
) -> None:
    """Full startup sequence: version check, heartbeat scheduler, serve restart, heartbeat, health."""
    agent = paths.active_agent()
    port = _serve_port()

    console.print(f"[bold]innie boot[/bold]  agent=[cyan]{agent}[/cyan]  port={port}\n")

    _step_version_check(agent, force_update)
    _step_heartbeat_scheduler()
    _step_skills_symlink()

    if not no_restart:
        _step_restart_serve(agent, port)
    else:
        console.print("\n[bold]4. Serve / Message Gateways[/bold]  [dim]skipped (--no-restart)[/dim]")

    _step_run_heartbeat(agent, skip_heartbeat)
    _step_health_check(agent, port)

    console.print("[green]boot complete.[/green]")
