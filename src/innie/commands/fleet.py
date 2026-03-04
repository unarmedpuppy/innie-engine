"""innie fleet — fleet gateway for multi-machine agent coordination."""

import typer


def start(
    host: str = typer.Option("127.0.0.1", help="Bind address"),
    port: int = typer.Option(8080, help="Port number"),
    config: str = typer.Option(None, help="Path to fleet config YAML"),
    reload: bool = typer.Option(False, help="Auto-reload on code changes"),
):
    """Start the fleet gateway server."""
    try:
        import uvicorn
    except ImportError:
        typer.echo("Missing serve dependencies. Install with: pip install innie-engine[serve]")
        raise typer.Exit(1)

    import os

    if config:
        os.environ["INNIE_FLEET_CONFIG"] = config

    typer.echo(f"Starting fleet gateway on {host}:{port}")
    uvicorn.run(
        "innie.fleet.gateway:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


def agents():
    """List all agents in the fleet with status."""
    import httpx

    from innie.core.config import get

    gateway_url = get("fleet.gateway_url", "http://localhost:8080")
    try:
        resp = httpx.get(f"{gateway_url}/api/agents", timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        typer.echo(f"Failed to reach fleet gateway: {e}")
        raise typer.Exit(1)

    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="Fleet Agents")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Endpoint", style="dim")
    table.add_column("Response", justify="right")

    status_colors = {
        "online": "green",
        "degraded": "yellow",
        "offline": "red",
        "unknown": "dim",
    }

    for agent in data.get("agents", []):
        health = agent.get("health", {})
        status = health.get("status", "unknown")
        color = status_colors.get(status, "dim")
        rt = health.get("response_time_ms")
        rt_str = f"{rt:.0f}ms" if rt else "-"
        table.add_row(
            agent["id"],
            agent.get("name", ""),
            agent.get("agent_type", ""),
            f"[{color}]{status}[/{color}]",
            agent.get("endpoint", ""),
            rt_str,
        )

    console.print(table)


def stats():
    """Show fleet-wide statistics."""
    import httpx

    from innie.core.config import get

    gateway_url = get("fleet.gateway_url", "http://localhost:8080")
    try:
        resp = httpx.get(f"{gateway_url}/api/agents/stats", timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        typer.echo(f"Failed to reach fleet gateway: {e}")
        raise typer.Exit(1)

    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    lines = [
        f"Total agents: {data.get('total_agents', 0)}",
        f"Online: {data.get('online_count', 0)}  "
        f"Degraded: {data.get('degraded_count', 0)}  "
        f"Offline: {data.get('offline_count', 0)}",
        f"Avg response time: {data.get('avg_response_time_ms', 0):.0f}ms",
    ]
    unexpected = data.get("unexpected_offline_count", 0)
    if unexpected:
        lines.append(f"[red]Unexpected offline: {unexpected}[/red]")
    console.print(Panel("\n".join(lines), title="Fleet Stats"))
