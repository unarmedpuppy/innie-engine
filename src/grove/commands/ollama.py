"""Ollama local model management commands."""

import json
import platform
import re
import subprocess
import sys

import httpx
import typer
from rich.console import Console
from rich.table import Table

console = Console()

_DEFAULT_URL = "http://localhost:11434"

# Curated fallback model catalog — (ollama_name, approx_gb_needed_for_inference)
# Listed smallest to largest. All are instruction-tuned qwen2.5 variants.
_FALLBACK_MODELS: list[tuple[str, float]] = [
    ("qwen2.5:0.5b", 0.4),
    ("qwen2.5:1.5b", 1.0),
    ("qwen2.5:3b",   2.0),
    ("qwen2.5:7b",   4.7),
    ("qwen2.5:14b",  9.0),
]


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


# ── setup ──────────────────────────────────────────────────────────────────────


def _detect_memory_gb() -> tuple[float, str]:
    """Return (available_gb, source) where source is 'vram', 'ram', or 'unknown'."""
    # NVIDIA VRAM
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            total_mb = sum(int(x.strip()) for x in r.stdout.strip().splitlines() if x.strip().isdigit())
            if total_mb > 0:
                return total_mb / 1024, "vram"
    except Exception:
        pass

    # macOS — total RAM (Apple Silicon shares GPU/CPU memory)
    if platform.system() == "Darwin":
        try:
            r = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True)
            if r.returncode == 0:
                return int(r.stdout.strip()) / 1e9, "ram"
        except Exception:
            pass

    # Linux — /proc/meminfo
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1e6, "ram"
    except Exception:
        pass

    return 8.0, "unknown"


def _pick_model(memory_gb: float) -> str:
    """Pick the largest model that fits within 20% of available memory."""
    budget = memory_gb * 0.20
    chosen = _FALLBACK_MODELS[0][0]
    for name, req in _FALLBACK_MODELS:
        if req <= budget:
            chosen = name
    return chosen


def _ollama_is_running() -> bool:
    try:
        httpx.get(f"{_DEFAULT_URL}/api/version", timeout=2.0)
        return True
    except Exception:
        return False


def _install_ollama() -> bool:
    """Try to install ollama. Returns True if successful."""
    if platform.system() == "Darwin":
        console.print("Installing ollama via Homebrew...")
        r = subprocess.run(["brew", "install", "ollama"], capture_output=False)
        return r.returncode == 0
    else:
        console.print(
            "[yellow]Auto-install not supported on this platform.[/yellow]\n"
            "Install ollama manually: https://ollama.com/download\n"
            "Then re-run: g ollama setup"
        )
        return False


def setup(
    agent: str = typer.Option("", "--agent", "-a", help="Agent name (default: active)"),
    model: str = typer.Option("", "--model", "-m", help="Override automatic model selection"),
    serve_port: int = typer.Option(
        0, "--serve-port", "-p",
        help="Port grove serve runs on for this agent (sets ANTHROPIC_FALLBACK_BASE_URL)"
    ),
    notify_channel: str = typer.Option(
        "", "--notify-channel",
        help="Mattermost channel ID for fallback alerts (sets GROVE_FALLBACK_NOTIFY_MM_CHANNEL)"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts"),
) -> None:
    """Install ollama, pick a model by available memory, and configure grove's fallback circuit breaker.

    After running this, grove agents will automatically fall back to local ollama
    when the primary llm-router is unreachable, and alert you via Mattermost.
    """
    from grove.core import paths
    from grove.core.agent_env import set_env_var

    target = agent or paths.active_agent()
    if not target:
        console.print("[red]No active agent — run with --agent <name>[/red]")
        raise typer.Exit(1)

    # ── 1. Ensure ollama is installed ──────────────────────────────────────────
    if subprocess.run(["which", "ollama"], capture_output=True).returncode != 0:
        console.print("[yellow]ollama not found.[/yellow]")
        if not yes and not typer.confirm("Install ollama now?", default=True):
            raise typer.Exit(0)
        if not _install_ollama():
            raise typer.Exit(1)
    else:
        console.print("[green]✓[/green] ollama already installed")

    # ── 2. Start ollama serve if not running ───────────────────────────────────
    if not _ollama_is_running():
        console.print("Starting ollama serve...")
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        import time
        for _ in range(10):
            time.sleep(1)
            if _ollama_is_running():
                break
        else:
            console.print("[red]ollama serve did not start in time[/red]")
            raise typer.Exit(1)
    console.print("[green]✓[/green] ollama running")

    # ── 3. Pick model ──────────────────────────────────────────────────────────
    if model:
        chosen = model
        console.print(f"Using specified model: [bold]{chosen}[/bold]")
    else:
        mem_gb, mem_src = _detect_memory_gb()
        chosen = _pick_model(mem_gb)
        budget = mem_gb * 0.20
        console.print(
            f"Detected {mem_gb:.1f} GB {mem_src} → 20% budget = {budget:.1f} GB → "
            f"selected [bold]{chosen}[/bold]"
        )

    if not yes and not typer.confirm(f"Pull and use [bold]{chosen}[/bold] as fallback model?", default=True):
        raise typer.Exit(0)

    # ── 4. Pull model if not already present ───────────────────────────────────
    try:
        resp = httpx.get(f"{_DEFAULT_URL}/api/tags", timeout=5.0)
        existing = [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        existing = []

    if any(chosen == m or chosen == m.split(":")[0] for m in existing):
        console.print(f"[green]✓[/green] {chosen} already pulled")
    else:
        console.print(f"Pulling [bold]{chosen}[/bold]...")
        try:
            with httpx.stream(
                "POST", f"{_DEFAULT_URL}/api/pull",
                json={"name": chosen, "stream": True}, timeout=600.0,
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
        console.print(f"\n[green]✓[/green] {chosen} ready")

    # ── 5. Write env vars ──────────────────────────────────────────────────────
    # GROVE_OLLAMA_MODEL and GROVE_FALLBACK_MODEL go in the SHARED env — ollama is a
    # machine-level install shared by all agents. Per-agent vars (URL, notify channel)
    # go in the agent-specific env so each agent can have its own serve port.
    set_env_var("GROVE_OLLAMA_MODEL", chosen, shared=True)
    console.print(f"[green]✓[/green] GROVE_OLLAMA_MODEL={chosen} → {paths.shared_env_file()} (shared)")

    set_env_var("GROVE_FALLBACK_MODEL", chosen, shared=True)
    console.print(f"[green]✓[/green] GROVE_FALLBACK_MODEL={chosen} (shared)")

    if serve_port:
        fallback_url = f"http://127.0.0.1:{serve_port}"
        set_env_var("ANTHROPIC_FALLBACK_BASE_URL", fallback_url, target)
        console.print(f"[green]✓[/green] ANTHROPIC_FALLBACK_BASE_URL={fallback_url}")
    else:
        console.print(
            "\n[yellow]ANTHROPIC_FALLBACK_BASE_URL not set.[/yellow]\n"
            "Set it to your grove serve port so agents route through the built-in proxy:\n"
            f"  g env set ANTHROPIC_FALLBACK_BASE_URL http://127.0.0.1:<port> --agent {target}"
        )

    if notify_channel:
        set_env_var("GROVE_FALLBACK_NOTIFY_MM_CHANNEL", notify_channel, target)
        console.print(f"[green]✓[/green] GROVE_FALLBACK_NOTIFY_MM_CHANNEL={notify_channel}")
    else:
        console.print(
            "\n[dim]Tip: set --notify-channel <mm-channel-id> to get Mattermost alerts "
            "when the fallback activates.[/dim]"
        )

    console.print(
        f"\n[bold green]Done.[/bold green] Agent [bold]{target}[/bold] will fall back to "
        f"local ollama ([bold]{chosen}[/bold]) when the primary inference URL is unreachable."
    )
    if serve_port:
        console.print("Restart grove serve to pick up the new env vars.")
