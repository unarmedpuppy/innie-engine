"""grove task — Tasks API native CLI client.

TasksClient is importable by other grove commands (e.g. roots) — use it directly
rather than shelling out or duplicating HTTP logic.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console()

_DEFAULT_URL = "https://tasks-api.server.unarmedpuppy.com"

# Tasks API uses legacy agent names. Map current grove agent names → API values.
# Update this as the Tasks API schema is migrated.
_AGENT_ALIASES: dict[str, str] = {
    "oak": "avery",
    "ash": "avery",       # update when ash gets its own API slot
    "elm": "gilfoyle",
    "willow": "ralph",
}

_PRIORITY_COLORS = {"P0": "red", "P1": "yellow", "P2": "cyan", "P3": "dim"}
_STATUS_COLORS = {
    "OPEN": "green",
    "IN_PROGRESS": "yellow",
    "CLOSED": "dim",
}
_STATUS_ALIASES = {
    "open": "OPEN",
    "in-progress": "IN_PROGRESS",
    "in_progress": "IN_PROGRESS",
    "closed": "CLOSED",
    "done": "CLOSED",
}


def _api_url() -> str:
    return (os.environ.get("TASKS_API_URL") or _DEFAULT_URL).rstrip("/")


def _age(dt_str: str) -> str:
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - dt
        if delta.days > 0:
            return f"{delta.days}d"
        hours = delta.seconds // 3600
        if hours > 0:
            return f"{hours}h"
        return f"{delta.seconds // 60}m"
    except Exception:
        return "?"


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:40].strip("-")


def _priority_color(p: str) -> str:
    return f"[{_PRIORITY_COLORS.get(p, 'white')}]{p}[/]"


def _status_color(s: str) -> str:
    return f"[{_STATUS_COLORS.get(s, 'white')}]{s}[/]"


class TasksClient:
    """Thin, importable client for the Tasks API.

    Usage from other grove commands::

        from grove.commands.task import TasksClient
        client = TasksClient()
        task = client.get("mercury-003")
        client.tag("mercury-003", "roots_state", "running")
    """

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or _api_url()).rstrip("/")

    # ── internal helpers ────────────────────────────────────────────────────

    def _get(self, path: str, **params) -> dict:
        import httpx
        r = httpx.get(
            f"{self.base_url}{path}",
            params={k: v for k, v in params.items() if v is not None},
            timeout=10.0,
        )
        if r.status_code == 422:
            detail = r.json().get("detail", r.text)
            raise ValueError(f"Tasks API rejected params: {detail}")
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, data: dict) -> dict:
        import httpx
        r = httpx.post(f"{self.base_url}{path}", json=data, timeout=10.0)
        r.raise_for_status()
        return r.json()

    def _patch(self, path: str, data: dict) -> dict:
        import httpx
        r = httpx.patch(f"{self.base_url}{path}", json=data, timeout=10.0)
        r.raise_for_status()
        return r.json()

    # ── public API ──────────────────────────────────────────────────────────

    def get(self, task_id: str) -> dict:
        """Fetch a single task by ID. Raises httpx.HTTPStatusError if not found."""
        return self._get(f"/v1/tasks/{task_id}")

    def list(
        self,
        status: str | None = None,
        assignee: str | None = None,
        type: str | None = None,
        repo: str | None = None,
        priority: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Return a list of tasks matching the given filters.

        Note: the Tasks API uses legacy agent names (avery, gilfoyle, ralph).
        Client-side filtering is applied for agent-name aliases.
        """
        tasks = self._get(
            "/v1/tasks",
            status=status,
            # assignee sent only if it looks like an API-native value
            assignee=assignee if assignee and assignee not in _AGENT_ALIASES else None,
            type=type,
            repo=repo,
            priority=priority,
        ).get("tasks", [])
        # Client-side assignee filter for agent aliases
        if assignee and assignee in _AGENT_ALIASES:
            api_name = _AGENT_ALIASES[assignee]
            tasks = [t for t in tasks if t.get("assignee") == api_name]
        elif assignee:
            tasks = [t for t in tasks if t.get("assignee") == assignee]
        return tasks[:limit]

    def create(self, **fields) -> dict:
        """Create a new task. Required fields: id, title, priority, repo, type."""
        return self._post("/v1/tasks", fields)

    def update(self, task_id: str, **fields) -> dict:
        """Patch arbitrary fields on a task."""
        return self._patch(f"/v1/tasks/{task_id}", fields)

    def close(self, task_id: str) -> dict:
        """Close a task."""
        return self._post(f"/v1/tasks/{task_id}/close", {})

    def claim(self, task_id: str) -> dict:
        """Set task to IN_PROGRESS."""
        return self._post(f"/v1/tasks/{task_id}/claim", {})

    def tag(self, task_id: str, key: str, value: str) -> dict:
        """Set a metadata key on a task (merged, not replaced)."""
        return self._patch(f"/v1/tasks/{task_id}", {"metadata": {key: value}})

    def untag(self, task_id: str, key: str) -> dict:
        """Remove a metadata key from a task."""
        task = self.get(task_id)
        meta = dict(task.get("metadata") or {})
        meta.pop(key, None)
        return self._patch(f"/v1/tasks/{task_id}", {"metadata": meta})

    def note(self, task_id: str, text: str) -> dict:
        """Append a timestamped note to the task description."""
        task = self.get(task_id)
        existing = (task.get("description") or "").rstrip()
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        sep = "\n\n---\n\n" if existing else ""
        new_desc = f"{existing}{sep}**Note ({ts}):** {text}"
        return self._patch(f"/v1/tasks/{task_id}", {"description": new_desc})


# ── CLI commands ─────────────────────────────────────────────────────────────


def new(
    title: str = typer.Argument(..., help="Task title"),
    repo: str = typer.Option("engineering", "--repo", "-r", help="Repo/domain (e.g. polyjuiced, home-server, personal)"),
    type: str = typer.Option("engineering", "--type", "-t", help="Task type: engineering, personal, home, family, research"),
    priority: str = typer.Option("P2", "--priority", "-p", help="Priority: P0, P1, P2, P3"),
    assignee: str = typer.Option(None, "--assignee", "-a", help="Assignee (default: active agent)"),
    description: str = typer.Option("", "--description", "-d", help="Task description (markdown)"),
    task_id: str = typer.Option(None, "--id", help="Task ID (auto-generated if omitted)"),
    building_type: str = typer.Option(None, "--building-type", help="aoe-canvas category"),
) -> None:
    """Create a new task in the Tasks API."""
    from grove.core import paths

    if not task_id:
        today = datetime.now().strftime("%Y-%m-%d")
        slug = _slugify(title)
        task_id = f"{_slugify(repo)}-{today}-{slug}"

    if not assignee:
        assignee = paths.active_agent()
    # Map current grove agent name → Tasks API legacy name if needed
    api_assignee = _AGENT_ALIASES.get(assignee, assignee)

    if not building_type:
        _btypes = {
            "engineering": "barracks",
            "personal": "town-center",
            "home": "town-center",
            "family": "town-center",
            "research": "university",
        }
        building_type = _btypes.get(type, "barracks")

    client = TasksClient()
    try:
        task = client.create(
            id=task_id,
            title=title,
            priority=priority,
            repo=repo,
            type=type,
            assignee=api_assignee,
            source=paths.active_agent(),
            description=description,
            building_type=building_type,
        )
        console.print(f"[green]Created[/green] {task['id']}: {task['title']}")
    except Exception as e:
        console.print(f"[red]Failed to create task:[/red] {e}")
        raise typer.Exit(1)


def list_tasks(
    status: str = typer.Option("OPEN", "--status", "-s", help="Status filter: OPEN, IN_PROGRESS, CLOSED, all"),
    assignee: str = typer.Option(None, "--assignee", "-a", help="Filter by assignee"),
    type: str = typer.Option(None, "--type", "-t", help="Filter by type"),
    repo: str = typer.Option(None, "--repo", "-r", help="Filter by repo"),
    priority: str = typer.Option(None, "--priority", "-p", help="Filter by priority"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max results"),
    mine: bool = typer.Option(False, "--mine", "-m", help="Filter to active agent"),
) -> None:
    """List tasks from the Tasks API."""
    from grove.core import paths

    status_param = None if status == "all" else _STATUS_ALIASES.get(status, status)
    if mine and not assignee:
        assignee = paths.active_agent()

    client = TasksClient()
    try:
        tasks = client.list(
            status=status_param,
            assignee=assignee,
            type=type,
            repo=repo,
            priority=priority,
            limit=limit,
        )
    except Exception as e:
        console.print(f"[red]Tasks API unreachable:[/red] {e}")
        raise typer.Exit(1)

    if not tasks:
        console.print("[dim]No tasks found.[/dim]")
        return

    title_str = f"Tasks"
    if assignee:
        title_str += f" — {assignee}"
    if status != "all":
        title_str += f" ({status_param or 'all'})"

    table = Table(title=title_str, show_lines=False, expand=False, box=None, pad_edge=False)
    table.add_column("ID", style="cyan", no_wrap=True, min_width=12, max_width=22)
    table.add_column("  ", no_wrap=True, width=3)   # priority
    table.add_column("Title", no_wrap=True, min_width=24, max_width=38)
    table.add_column("  ", no_wrap=True, width=4)   # age

    for t in tasks:
        p = t.get("priority", "?")
        title_text = t.get("title", "")
        if len(title_text) > 38:
            title_text = title_text[:35] + "..."
        table.add_row(
            t.get("id", "?"),
            _priority_color(p),
            title_text,
            f"[dim]{_age(t.get('created_at', ''))}[/dim]",
        )

    console.print(table)


def get_task(
    task_id: str = typer.Argument(..., help="Task ID"),
) -> None:
    """Show full detail for a task."""
    client = TasksClient()
    try:
        t = client.get(task_id)
    except Exception as e:
        console.print(f"[red]Not found:[/red] {e}")
        raise typer.Exit(1)

    p = t.get("priority", "?")
    s = t.get("status", "?")

    console.print(f"\n[bold cyan]{t['id']}[/bold cyan]  {_priority_color(p)}  {_status_color(s)}")
    console.print(f"[bold]{t['title']}[/bold]\n")
    console.print(f"  type:      {t.get('type', '—')}")
    console.print(f"  repo:      {t.get('repo', '—')}")
    console.print(f"  assignee:  {t.get('assignee', '—')}")
    console.print(f"  source:    {t.get('source', '—')}")
    console.print(f"  created:   {t.get('created_at', '—')[:10]}  ({_age(t.get('created_at', ''))} ago)")
    console.print(f"  updated:   {t.get('updated_at', '—')[:10]}")
    if t.get("epic"):
        console.print(f"  epic:      {t['epic']}")

    meta = t.get("metadata") or {}
    if meta:
        console.print("\n  [dim]metadata:[/dim]")
        for k, v in meta.items():
            console.print(f"    {k}: {v}")

    if t.get("description"):
        console.print(f"\n[dim]─── description ───[/dim]")
        console.print(t["description"])

    if t.get("verification"):
        console.print(f"\n[dim]─── verification ───[/dim]")
        console.print(t["verification"])

    console.print()


def update_task(
    task_id: str = typer.Argument(..., help="Task ID"),
    status: str = typer.Option(None, "--status", "-s", help="New status: OPEN, IN_PROGRESS, CLOSED"),
    assignee: str = typer.Option(None, "--assignee", "-a", help="New assignee"),
    priority: str = typer.Option(None, "--priority", "-p", help="New priority: P0, P1, P2, P3"),
    title: str = typer.Option(None, "--title", help="New title"),
    description: str = typer.Option(None, "--description", "-d", help="New description"),
) -> None:
    """Update fields on a task."""
    fields: dict = {}
    if status:
        fields["status"] = _STATUS_ALIASES.get(status, status)
    if assignee:
        fields["assignee"] = assignee
    if priority:
        fields["priority"] = priority
    if title:
        fields["title"] = title
    if description is not None:
        fields["description"] = description

    if not fields:
        console.print("[yellow]Nothing to update — provide at least one flag.[/yellow]")
        raise typer.Exit(1)

    client = TasksClient()
    try:
        t = client.update(task_id, **fields)
        console.print(f"[green]Updated[/green] {t['id']}")
        for k, v in fields.items():
            console.print(f"  {k}: {v}")
    except Exception as e:
        console.print(f"[red]Failed:[/red] {e}")
        raise typer.Exit(1)


def close_task(
    task_id: str = typer.Argument(..., help="Task ID"),
) -> None:
    """Close a task."""
    client = TasksClient()
    try:
        client.close(task_id)
        console.print(f"[green]Closed[/green] {task_id}")
    except Exception as e:
        console.print(f"[red]Failed:[/red] {e}")
        raise typer.Exit(1)


def note(
    task_id: str = typer.Argument(..., help="Task ID"),
    text: str = typer.Argument(..., help="Note text (appended to description with timestamp)"),
) -> None:
    """Append a timestamped note to a task's description."""
    client = TasksClient()
    try:
        client.note(task_id, text)
        console.print(f"[green]Note added[/green] to {task_id}")
    except Exception as e:
        console.print(f"[red]Failed:[/red] {e}")
        raise typer.Exit(1)


def tag(
    task_id: str = typer.Argument(..., help="Task ID"),
    key: str = typer.Argument(..., help="Metadata key"),
    value: str = typer.Argument(..., help="Metadata value"),
) -> None:
    """Set a metadata key on a task."""
    client = TasksClient()
    try:
        client.tag(task_id, key, value)
        console.print(f"[green]Tagged[/green] {task_id}: {key}={value}")
    except Exception as e:
        console.print(f"[red]Failed:[/red] {e}")
        raise typer.Exit(1)


def untag(
    task_id: str = typer.Argument(..., help="Task ID"),
    key: str = typer.Argument(..., help="Metadata key to remove"),
) -> None:
    """Remove a metadata key from a task."""
    client = TasksClient()
    try:
        client.untag(task_id, key)
        console.print(f"[green]Untagged[/green] {task_id}: removed {key}")
    except Exception as e:
        console.print(f"[red]Failed:[/red] {e}")
        raise typer.Exit(1)
