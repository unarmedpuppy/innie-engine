"""grove docker — manage the full Docker services stack (embeddings, heartbeat, serve)."""

import json
import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from grove.core import paths
from grove.core.config import get

console = Console()

_SERVICES = ["embeddings", "heartbeat", "serve"]


def _compose_file() -> Path:
    return paths.home() / "docker-compose.yml"


def _docker_env() -> dict:
    """Return environment dict for Docker subprocess calls, setting DOCKER_HOST for Colima if needed."""
    import os

    env = os.environ.copy()
    if "DOCKER_HOST" in env:
        return env
    colima_sock = Path.home() / ".colima" / "default" / "docker.sock"
    if colima_sock.exists():
        env["DOCKER_HOST"] = f"unix://{colima_sock}"
        env.setdefault("DOCKER_API_VERSION", "1.47")
    return env


def _run_compose(*args: str, capture: bool = False, profile: bool = False) -> subprocess.CompletedProcess:
    compose = _compose_file()
    if not compose.exists():
        console.print("[red]docker-compose.yml not found at ~/.grove/docker-compose.yml[/red]")
        console.print("  Re-run [bold]g init[/bold] and select Docker embedding provider.")
        raise typer.Exit(1)
    cmd = ["docker", "compose", "-f", str(compose)]
    if profile:
        cmd += ["--profile", "serve"]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=capture, text=True, env=_docker_env())


def _container_states() -> dict[str, dict]:
    """Return {service_name: {status, health}} from `docker compose ps`."""
    result = _run_compose("ps", "--format", "json", capture=True, profile=True)
    states: dict[str, dict] = {}
    if result.returncode != 0 or not result.stdout.strip():
        return states
    for line in result.stdout.strip().splitlines():
        try:
            obj = json.loads(line)
            svc = obj.get("Service", "")
            if svc:
                states[svc] = {
                    "status": obj.get("State", "unknown"),
                    "health": obj.get("Health", ""),
                }
        except (json.JSONDecodeError, KeyError):
            pass
    return states


def up(
    serve: bool = typer.Option(False, "--serve", help="Also start the API server (serve profile)"),
    build: bool = typer.Option(False, "--build", help="Rebuild images before starting"),
):
    """Start Docker services (embeddings + heartbeat, optionally + serve)."""
    args = ["up", "-d"]
    if build:
        args.append("--build")

    result = _run_compose(*args, profile=serve)
    if result.returncode != 0:
        console.print(result.stderr)
        raise typer.Exit(result.returncode)

    services_started = ["embeddings", "heartbeat"]
    if serve:
        services_started.append("serve")
    console.print(f"  Started: {', '.join(services_started)}")

    # Health-poll embeddings
    import time

    import httpx

    emb_url = get("embedding.docker.url", "http://localhost:8766")
    console.print(f"  Waiting for embeddings at {emb_url} ...", end=" ")
    for _ in range(20):
        try:
            resp = httpx.get(f"{emb_url}/health", timeout=2.0)
            if resp.status_code == 200:
                console.print("[green]ready[/green]")
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        console.print("[yellow]timeout[/yellow]")
        console.print("  Embeddings may still be starting (model download can take a few minutes).")

    if serve:
        serve_port = 8013
        console.print(f"  API server: http://localhost:{serve_port}")

    console.print("  Run [bold]g docker status[/bold] to check all services.")


def down(
    serve: bool = typer.Option(False, "--serve", help="Include serve profile containers"),
):
    """Stop all Docker services."""
    result = _run_compose("down", profile=serve)
    if result.returncode == 0:
        console.print("  [green]✓[/green] All Docker services stopped.")
    else:
        console.print(result.stderr)
        raise typer.Exit(result.returncode)


def restart(
    service: Optional[str] = typer.Argument(
        None, help="Service to restart: embeddings, heartbeat, serve (default: all)"
    ),
):
    """Restart one or all Docker services."""
    args = ["restart"]
    if service:
        if service not in _SERVICES:
            console.print(f"[red]Unknown service '{service}'. Choose from: {', '.join(_SERVICES)}[/red]")
            raise typer.Exit(1)
        args.append(service)
    result = _run_compose(*args, profile=(service == "serve" or service is None))
    if result.returncode == 0:
        target = service or "all services"
        console.print(f"  [green]✓[/green] Restarted {target}.")
    else:
        console.print(result.stderr)
        raise typer.Exit(result.returncode)


def docker_status():
    """Show status of all Docker services."""
    compose = _compose_file()
    if not compose.exists():
        console.print("[dim]No docker-compose.yml at ~/.grove/ — Docker stack not configured.[/dim]")
        console.print("  Run [bold]g init[/bold] and select Docker embedding provider.")
        return

    states = _container_states()

    table = Table(title="Docker Services", show_header=True, header_style="bold")
    table.add_column("Service", style="bold")
    table.add_column("State")
    table.add_column("Health")
    table.add_column("Notes")

    # Embeddings
    emb = states.get("embeddings", {})
    emb_state = emb.get("status", "stopped")
    emb_health = ""
    emb_note = ""
    if emb_state == "running":
        import httpx
        emb_url = get("embedding.docker.url", "http://localhost:8766")
        try:
            resp = httpx.get(f"{emb_url}/health", timeout=2.0)
            if resp.status_code == 200:
                data = resp.json()
                emb_health = "[green]healthy[/green]"
                emb_note = f"model: {data.get('model', 'unknown')}"
            else:
                emb_health = f"[yellow]{resp.status_code}[/yellow]"
        except Exception:
            emb_health = "[red]unreachable[/red]"
            emb_note = f"http://localhost:8766"
        state_str = "[green]running[/green]"
    else:
        state_str = "[dim]stopped[/dim]"
        emb_note = "g docker up"
    table.add_row("embeddings", state_str, emb_health, emb_note)

    # Heartbeat
    hb = states.get("heartbeat", {})
    hb_state = hb.get("status", "stopped")
    hb_health = ""
    hb_note = ""
    if hb_state == "running":
        hb_state_str = "[green]running[/green]"
        # Check last heartbeat run from state file
        try:
            import json as _json
            import time

            state_file = paths.heartbeat_state(paths.active_agent())
            if state_file.exists():
                hb_data = _json.loads(state_file.read_text())
                last_run = hb_data.get("last_run", 0)
                if last_run:
                    ago = int(time.time() - last_run)
                    if ago < 60:
                        hb_note = f"last run: {ago}s ago"
                    elif ago < 3600:
                        hb_note = f"last run: {ago // 60}m ago"
                    else:
                        hb_note = f"last run: {ago // 3600}h ago"
        except Exception:
            pass
    else:
        hb_state_str = "[dim]stopped[/dim]"
        hb_note = "g docker up"
    table.add_row("heartbeat", hb_state_str, hb_health, hb_note)

    # Serve
    srv = states.get("serve", {})
    srv_state = srv.get("status", "stopped")
    if srv_state == "running":
        srv_state_str = "[green]running[/green]"
        serve_port = 8013
        import httpx
        try:
            resp = httpx.get(f"http://localhost:{serve_port}/health", timeout=2.0)
            srv_health = "[green]healthy[/green]" if resp.status_code == 200 else f"[yellow]{resp.status_code}[/yellow]"
        except Exception:
            srv_health = "[red]unreachable[/red]"
        srv_note = f"http://localhost:{serve_port}"
    else:
        srv_state_str = "[dim]stopped[/dim]"
        srv_health = ""
        srv_note = "g docker up --serve"
    table.add_row("serve", srv_state_str, srv_health, srv_note)

    console.print(table)


def logs(
    service: Optional[str] = typer.Argument(
        None, help="Service to show logs for: embeddings, heartbeat, serve (default: all)"
    ),
    follow: bool = typer.Option(False, "-f", "--follow", help="Stream logs"),
    tail: int = typer.Option(50, "--tail", help="Number of lines to show"),
):
    """Show container logs (all services or one)."""
    if service and service not in _SERVICES:
        console.print(f"[red]Unknown service '{service}'. Choose from: {', '.join(_SERVICES)}[/red]")
        raise typer.Exit(1)

    args = ["logs", f"--tail={tail}"]
    if follow:
        args.append("-f")
    if service:
        args.append(service)

    result = _run_compose(*args, profile=True)
    if result.returncode != 0:
        raise typer.Exit(result.returncode)
