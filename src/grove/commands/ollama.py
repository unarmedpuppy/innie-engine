"""Ollama local model management commands."""

import json
import re

import httpx
import typer
from rich.console import Console
from rich.table import Table

console = Console()

_DEFAULT_URL = "http://localhost:11434"


def _url() -> str:
    from grove.core.config import get

    return get("ollama.url", _DEFAULT_URL).rstrip("/")


def status() -> None:
    """Check if Ollama is running and reachable."""
    url = _url()
    try:
        resp = httpx.get(f"{url}/api/version", timeout=3.0)
        resp.raise_for_status()
        version = resp.json().get("version", "?")
        console.print(f"[green]✓[/green] Ollama running at {url} — version {version}")
    except Exception as e:
        console.print(f"[red]✗[/red] Ollama not reachable at {url}: {e}")
        raise typer.Exit(1)


def list_models() -> None:
    """List available local Ollama models."""
    url = _url()
    try:
        resp = httpx.get(f"{url}/api/tags", timeout=5.0)
        resp.raise_for_status()
        models = resp.json().get("models", [])
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    if not models:
        console.print("No models installed.")
        return

    table = Table("Model", "Size", "Modified")
    for m in models:
        size_gb = m.get("size", 0) / 1e9
        table.add_row(m["name"], f"{size_gb:.1f} GB", (m.get("modified_at") or "")[:10])
    console.print(table)


def pull(
    model: str = typer.Argument(..., help="Model name, e.g. llama3.1:8b"),
) -> None:
    """Pull a model from Ollama registry."""
    url = _url()
    console.print(f"Pulling [bold]{model}[/bold] from {url}...")
    try:
        with httpx.stream(
            "POST",
            f"{url}/api/pull",
            json={"name": model, "stream": True},
            timeout=600.0,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                status_msg = data.get("status", "")
                total = data.get("total", 0)
                completed = data.get("completed", 0)
                if total and completed:
                    pct = int(completed / total * 100)
                    console.print(f"  {status_msg}: {pct}%", end="\r")
                else:
                    console.print(f"  {status_msg}")
    except Exception as e:
        console.print(f"[red]Pull failed:[/red] {e}")
        raise typer.Exit(1)
    console.print(f"\n[green]✓[/green] {model} pulled successfully.")


def use(
    model: str = typer.Argument(..., help="Model name to set as heartbeat extraction provider"),
    docker: bool = typer.Option(
        False, "--docker", help="Use host.docker.internal (for container scheduler)"
    ),
) -> None:
    """Set a local Ollama model as the heartbeat extraction provider."""
    from grove.core.config import clear_cache
    from grove.core.paths import config_file

    host = "host.docker.internal" if docker else "localhost"
    external_url = f"http://{host}:11434"

    cfg_path = config_file()
    if not cfg_path.exists():
        console.print(f"[red]Config not found at {cfg_path}[/red]")
        raise typer.Exit(1)

    text = cfg_path.read_text()
    for field, value in (
        ("provider", "external"),
        ("external_url", external_url),
        ("model", model),
    ):
        text = re.sub(
            rf"^({re.escape(field)}\s*=\s*).*$",
            f'{field} = "{value}"',
            text,
            flags=re.MULTILINE,
        )

    cfg_path.write_text(text)
    clear_cache()
    console.print(
        f"[green]✓[/green] Heartbeat provider set to Ollama at {external_url} "
        f"with model [bold]{model}[/bold]"
    )
    console.print("  Run [bold]g heartbeat run[/bold] to test.")
