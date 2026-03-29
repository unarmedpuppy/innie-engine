"""grove inbox — read and send async A2A inbox messages."""

from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from grove.core import paths

console = Console()


def list_inbox(
    agent: str = typer.Option(None, "--agent", "-a", help="Agent name (default: active agent)"),
    all: bool = typer.Option(False, "--all", help="Include archived messages"),
) -> None:
    """List inbox messages from other agents."""
    inbox_dir = paths.inbox_dir(agent)

    dirs_to_check = [inbox_dir]
    if all:
        dirs_to_check.append(inbox_dir / "archive")

    messages = []
    for d in dirs_to_check:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.md")):
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                # Parse frontmatter
                from_agent, subject, date = "unknown", f.stem, ""
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end != -1:
                        fm = content[3:end]
                        for line in fm.splitlines():
                            if line.startswith("from:"):
                                from_agent = line.split(":", 1)[1].strip()
                            elif line.startswith("subject:"):
                                subject = line.split(":", 1)[1].strip()
                            elif line.startswith("date:"):
                                date = line.split(":", 1)[1].strip()
                archived = d.name == "archive"
                messages.append((date, from_agent, subject, f, archived))
            except Exception:
                continue

    if not messages:
        console.print("[dim]No inbox messages.[/dim]")
        return

    table = Table(title=f"Inbox — {paths.active_agent() if not agent else agent}")
    table.add_column("Date", style="dim", width=12)
    table.add_column("From", style="cyan", width=12)
    table.add_column("Subject")
    table.add_column("Status", width=10)

    for date, from_agent, subject, f, archived in messages:
        status = "[dim]archived[/dim]" if archived else "[green]unread[/green]"
        table.add_row(date, from_agent, subject, status)

    console.print(table)


def read_message(
    filename: str = typer.Argument(..., help="Filename or partial match"),
    agent: str = typer.Option(None, "--agent", "-a", help="Agent name"),
) -> None:
    """Read a specific inbox message."""
    inbox_dir = paths.inbox_dir(agent)

    # Search inbox and archive
    for search_dir in [inbox_dir, inbox_dir / "archive"]:
        if not search_dir.exists():
            continue
        for f in search_dir.glob("*.md"):
            if filename in f.name:
                console.print(f.read_text(encoding="utf-8"))
                return

    console.print(f"[red]Message not found: {filename}[/red]")
    raise typer.Exit(1)


def send(
    to: str = typer.Argument(..., help="Target agent name (elm, ralph, ash)"),
    subject: str = typer.Option(..., "--subject", "-s", help="Message subject"),
    message: str = typer.Option(None, "--message", "-m", help="Message body (or use stdin)"),
    agent: str = typer.Option(None, "--agent", "-a", help="Sender agent name"),
) -> None:
    """Send an inbox message to another agent."""
    import os
    import re
    import sys

    body = message
    if not body:
        if not sys.stdin.isatty():
            body = sys.stdin.read().strip()
        else:
            console.print("[red]Provide message via --message or stdin.[/red]")
            raise typer.Exit(1)

    sender = agent or paths.active_agent()
    today = datetime.now().strftime("%Y-%m-%d")

    # Try HTTP delivery first if fleet gateway is configured
    fleet_url = os.environ.get("GROVE_FLEET_URL") or os.environ.get("INNIE_FLEET_URL", "")
    if fleet_url:
        delivered = _send_http(to, sender, subject, body, fleet_url)
        if delivered:
            return

    # Fallback: write to local filesystem (same-machine agents)
    slug = re.sub(r"[^a-z0-9]+", "-", subject.lower().strip())[:40].strip("-")
    target_inbox = paths.agents_dir() / to / "data" / "inbox"
    target_inbox.mkdir(parents=True, exist_ok=True)

    dest = target_inbox / f"{today}-from-{sender}-{slug}.md"
    i = 1
    while dest.exists():
        dest = target_inbox / f"{today}-from-{sender}-{slug}-{i}.md"
        i += 1

    dest.write_text(
        f"---\nfrom: {sender}\nto: {to}\ndate: {today}\nsubject: {subject}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    console.print(f"[green]Sent[/green] → {dest.name}")


def _send_http(to: str, sender: str, subject: str, body: str, fleet_url: str) -> bool:
    """Attempt HTTP delivery to target agent via fleet gateway. Returns True if delivered."""
    import os
    import httpx

    try:
        resp = httpx.get(f"{fleet_url}/api/agents/{to}", timeout=3.0)
        if resp.status_code != 200:
            return False
        data = resp.json()
        endpoint = data.get("direct_url") or data.get("endpoint", "")
        if not endpoint:
            return False

        token = (
            os.environ.get(f"GROVE_AGENT_{to.upper()}_TOKEN")
            or os.environ.get(f"INNIE_AGENT_{to.upper()}_TOKEN", "")
        )
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        r = httpx.post(
            f"{endpoint.rstrip('/')}/v1/inbox",
            json={"from": sender, "to": to, "subject": subject, "body": body},
            headers=headers,
            timeout=10.0,
        )
        if r.status_code == 201:
            result = r.json()
            console.print(f"[green]Sent[/green] → {result.get('filename', to)} (HTTP)")
            return True
        console.print(f"[yellow]HTTP delivery failed ({r.status_code}), falling back to filesystem[/yellow]")
        return False
    except Exception as e:
        console.print(f"[dim]HTTP delivery unavailable ({e}), falling back to filesystem[/dim]")
        return False


def archive(
    filename: str = typer.Argument(..., help="Filename or partial match to archive"),
    agent: str = typer.Option(None, "--agent", "-a", help="Agent name"),
) -> None:
    """Manually archive an inbox message."""
    inbox_dir = paths.inbox_dir(agent)
    archive_dir = inbox_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    for f in inbox_dir.glob("*.md"):
        if filename in f.name:
            dest = archive_dir / f.name
            f.rename(dest)
            console.print(f"[green]Archived[/green] → {dest.name}")
            return

    console.print(f"[red]Message not found: {filename}[/red]")
    raise typer.Exit(1)
