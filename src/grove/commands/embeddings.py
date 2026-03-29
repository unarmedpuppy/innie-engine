"""innie embeddings — manage the local embedding service (Docker)."""

import subprocess
from pathlib import Path

import typer
from rich.console import Console

from grove.core import paths
from grove.core.config import get

console = Console()


def _compose_file() -> Path:
    return paths.home() / "docker-compose.yml"


def _run_compose(*args: str, capture: bool = False) -> subprocess.CompletedProcess:
    compose = _compose_file()
    if not compose.exists():
        console.print("[red]docker-compose.yml not found at ~/.innie/docker-compose.yml[/red]")
        console.print("  Re-run [bold]innie init[/bold] with embedding provider = docker.")
        raise typer.Exit(1)
    cmd = ["docker", "compose", "-f", str(compose), *args]
    return subprocess.run(cmd, capture_output=capture, text=True)


def up(
    build: bool = typer.Option(False, "--build", help="Rebuild image before starting"),
):
    """Start the embedding service."""
    provider = get("embedding.provider", "none")
    if provider != "docker":
        console.print("[yellow]embedding.provider is not 'docker' in config.toml[/yellow]")
        console.print("  Set [bold]provider = \"docker\"[/bold] under [embedding] to use this.")
        raise typer.Exit(1)

    args = ["up", "-d"]
    if build:
        args.append("--build")

    result = _run_compose(*args)
    if result.returncode != 0:
        raise typer.Exit(result.returncode)

    # Quick health poll
    import time

    import httpx

    url = get("embedding.docker.url", "http://localhost:8766")
    console.print(f"  Waiting for service at {url} ...", end=" ")
    for _ in range(20):
        try:
            resp = httpx.get(f"{url}/health", timeout=2.0)
            if resp.status_code == 200:
                console.print("[green]ready[/green]")
                console.print(f"\n  [green]✓[/green] Embedding service is up.")
                console.print("  Run [bold]innie index[/bold] to build semantic vectors.")
                return
        except Exception:
            pass
        time.sleep(1)

    console.print("[yellow]timeout[/yellow]")
    console.print("  Service may still be starting (model download on first run can take a few minutes).")
    console.print(f"  Check: [bold]innie embeddings status[/bold]")


def down():
    """Stop the embedding service."""
    result = _run_compose("down")
    if result.returncode == 0:
        console.print("  [green]✓[/green] Embedding service stopped.")
    else:
        raise typer.Exit(result.returncode)


def emb_status():
    """Show embedding service health and container state."""
    provider = get("embedding.provider", "none")
    console.print(f"  Provider: [bold]{provider}[/bold]")

    if provider == "none":
        console.print("  Configured for keyword search only — no embedding service needed.")
        return

    if provider == "external":
        url = get("embedding.external.url", "")
        console.print(f"  Endpoint: {url}")
    else:
        url = get("embedding.docker.url", "http://localhost:8766")
        console.print(f"  Endpoint: {url}")

        # Container state
        result = _run_compose("ps", "--format", "json", capture=True)
        if result.returncode == 0 and result.stdout.strip():
            console.print(f"  Container: [dim]{result.stdout.strip()[:120]}[/dim]")
        else:
            console.print("  Container: [dim]not running or unknown[/dim]")

    # Health check
    try:
        import httpx

        resp = httpx.get(f"{url}/health", timeout=3.0)
        if resp.status_code == 200:
            data = resp.json()
            model = data.get("model", "unknown")
            console.print(f"  Health:   [green]healthy[/green]  (model: {model})")
        else:
            console.print(f"  Health:   [yellow]{resp.status_code}[/yellow]")
    except Exception as e:
        console.print(f"  Health:   [red]unreachable[/red]  ({e})")
        if provider == "docker":
            console.print("  Start it: [bold]innie embeddings up[/bold]")


def logs(
    follow: bool = typer.Option(False, "-f", "--follow", help="Stream logs"),
    tail: int = typer.Option(50, "--tail", help="Number of lines to show"),
):
    """Show embedding service container logs."""
    args = ["logs", f"--tail={tail}"]
    if follow:
        args.append("-f")
    result = _run_compose(*args)
    if result.returncode != 0:
        raise typer.Exit(result.returncode)
