"""Project walnut commands — manage per-project 5-file context structure."""

from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown

from grove.core import paths

console = Console()


def _project_dir(project: str) -> Path:
    return paths.project_dir(project)


def log(
    project: str = typer.Argument(..., help="Project name (must match ~/workspace/<name>)"),
    entry: str = typer.Argument(..., help="Log entry text"),
) -> None:
    """Prepend a timestamped entry to the project log.md spine."""
    log_file = paths.project_log(project)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    new_entry = f"- [{timestamp}] {entry}\n"

    existing = log_file.read_text() if log_file.exists() else ""
    log_file.write_text(new_entry + existing)
    console.print(f"[green]✓[/green] Logged to {project}/log.md")


def now(
    project: str = typer.Argument(..., help="Project name"),
) -> None:
    """Print the current now.md for the project."""
    now_file = paths.project_now(project)
    if not now_file.exists():
        console.print(f"[yellow]No now.md found for {project}[/yellow]")
        raise typer.Exit(1)
    console.print(Markdown(now_file.read_text()))


def save(
    project: str = typer.Argument(..., help="Project name"),
    note: str = typer.Option("", "--note", "-n", help="Optional context note to include in synthesis"),
) -> None:
    """Synthesize a new now.md from recent log entries via LLM."""
    log_file = paths.project_log(project)
    key_file = paths.project_key(project)

    if not log_file.exists():
        console.print(f"[red]No log.md found for {project}. Run `g project log {project} <entry>` first.[/red]")
        raise typer.Exit(1)

    log_content = log_file.read_text()
    key_content = key_file.read_text() if key_file.exists() else ""

    # Take last 30 log entries for synthesis
    log_lines = [l for l in log_content.splitlines() if l.strip()][:30]
    recent_log = "\n".join(log_lines)

    try:
        from grove.heartbeat.extract import _call_openai_compatible
        from grove.core.config import get

        prompt = f"""You are synthesizing a project status document (now.md) for a software engineering project.

Key info:
{key_content if key_content else "(no key.md found)"}

Recent log entries (newest first):
{recent_log}

{"Additional context: " + note if note else ""}

Write a concise now.md with these sections:
## Current Phase
[One sentence on what phase/sprint this project is in]

## Active Context
[2-4 bullet points on what's actively being worked on or just completed]

## Next Action
[The single most important next step]

Keep it tight — this gets injected into every session. No fluff."""

        base_url = get("heartbeat.external_url", "")
        api_key = get("heartbeat.external_api_key", "")
        model = get("heartbeat.model", "auto")

        if not base_url:
            console.print("[red]heartbeat.external_url not configured — cannot synthesize now.md[/red]")
            raise typer.Exit(1)

        result = _call_openai_compatible(base_url, api_key, model, prompt, max_tokens=400)

        now_file = paths.project_now(project)
        now_file.parent.mkdir(parents=True, exist_ok=True)
        now_file.write_text(result.strip() + "\n")
        console.print(f"[green]✓[/green] now.md updated for {project}")
        console.print(Markdown(result))

    except Exception as e:
        console.print(f"[red]Synthesis failed: {e}[/red]")
        raise typer.Exit(1)


def list_projects() -> None:
    """List all projects with their current phase from now.md."""
    projects_dir = paths.projects_dir()
    if not projects_dir.exists():
        console.print("[yellow]No projects directory found[/yellow]")
        return

    projects = sorted([d for d in projects_dir.iterdir() if d.is_dir()])
    if not projects:
        console.print("[yellow]No projects found[/yellow]")
        return

    for p in projects:
        now_file = p / "now.md"
        phase = "(no now.md)"
        if now_file.exists():
            for line in now_file.read_text().splitlines():
                if line.startswith("## Current Phase"):
                    continue
                if line.strip() and not line.startswith("#"):
                    phase = line.strip()
                    break
        console.print(f"[bold]{p.name}[/bold]  {phase}")
