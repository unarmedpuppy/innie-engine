"""grove fleet — manage multiple grove agents across machines."""

from __future__ import annotations

import os
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def _fleet_url() -> str:
    url = os.environ.get("GROVE_FLEET_URL") or os.environ.get("INNIE_FLEET_URL", "")
    if not url:
        console.print("[red]GROVE_FLEET_URL not set — cannot reach fleet[/red]")
        raise typer.Exit(1)
    return url


def _get_agents(fleet_url: str) -> list[dict]:
    import httpx
    try:
        resp = httpx.get(f"{fleet_url}/api/agents", timeout=5.0)
        resp.raise_for_status()
        return resp.json().get("agents", [])
    except Exception as e:
        console.print(f"[red]Fleet gateway unreachable: {e}[/red]")
        raise typer.Exit(1)


def _agent_token(name: str) -> str:
    return (
        os.environ.get(f"GROVE_AGENT_{name.upper()}_TOKEN")
        or os.environ.get(f"INNIE_AGENT_{name.upper()}_TOKEN", "")
    )


def status() -> None:
    """Show health status of all fleet agents."""
    import httpx

    fleet_url = _fleet_url()
    agents = _get_agents(fleet_url)

    table = Table(title="Fleet Status")
    table.add_column("Agent", style="cyan")
    table.add_column("Version", width=10)
    table.add_column("Status")
    table.add_column("Jobs", width=6)
    table.add_column("Endpoint")

    for ag in agents:
        name = ag.get("name", "?")
        direct_url = ag.get("direct_url") or ag.get("endpoint", "")
        if not direct_url:
            table.add_row(name, "—", "[dim]no endpoint[/dim]", "—", "—")
            continue
        try:
            r = httpx.get(f"{direct_url.rstrip('/')}/health", timeout=4.0)
            if r.status_code == 200:
                h = r.json()
                version = h.get("version", "?")
                jobs = str(h.get("jobs", {}).get("completed", "?"))
                table.add_row(name, f"v{version}", "[green]healthy[/green]", jobs, direct_url)
            else:
                table.add_row(name, "—", f"[yellow]HTTP {r.status_code}[/yellow]", "—", direct_url)
        except Exception as e:
            table.add_row(name, "—", f"[red]unreachable[/red]", "—", direct_url)

    console.print(table)


def upgrade(
    agent_name: Optional[str] = typer.Argument(None, help="Agent to upgrade (default: all fleet agents)"),
) -> None:
    """Trigger self-upgrade on fleet agents. Agents install the latest version and restart.

    Each agent derives its own install command from dist-info — no configuration needed.
    """
    import httpx

    fleet_url = _fleet_url()

    if agent_name:
        agents = [a for a in _get_agents(fleet_url) if a.get("name") == agent_name]
        if not agents:
            console.print(f"[red]Agent '{agent_name}' not found in fleet[/red]")
            raise typer.Exit(1)
    else:
        agents = _get_agents(fleet_url)

    for ag in agents:
        name = ag.get("name", "?")
        direct_url = ag.get("direct_url") or ag.get("endpoint", "")
        if not direct_url:
            console.print(f"[dim]{name}: no endpoint — skipped[/dim]")
            continue
        token = _agent_token(name)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            r = httpx.post(
                f"{direct_url.rstrip('/')}/v1/agent/upgrade",
                headers=headers,
                timeout=10.0,
            )
            if r.status_code == 200:
                data = r.json()
                console.print(f"[green]{name}[/green]: upgrading from v{data.get('current_version', '?')} → latest")
            else:
                console.print(f"[yellow]{name}[/yellow]: HTTP {r.status_code} — {r.text[:80]}")
        except Exception as e:
            console.print(f"[red]{name}[/red]: unreachable ({e})")
