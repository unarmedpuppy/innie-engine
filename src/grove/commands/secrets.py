"""innie secrets — scan the knowledge base for accidentally committed secrets."""

import typer
from rich.console import Console
from rich.table import Table

from grove.core import paths

console = Console()


def scan(
    agent: str = typer.Option("", "--agent", "-a", help="Agent name (default: active agent)"),
    all_dirs: bool = typer.Option(False, "--all", help="Scan all dirs including state/ (default: data/ only)"),
):
    """Scan knowledge base files for secrets before committing to git."""
    from grove.core.secrets import scan_directory

    target_agent = agent or paths.active_agent()
    console.print(f"Scanning agent: [bold]{target_agent}[/bold]\n")

    dirs_to_scan = [paths.data_dir(target_agent)]
    if all_dirs:
        dirs_to_scan.append(paths.sessions_dir(target_agent))
        ctx = paths.context_file(target_agent)
        if ctx.exists():
            dirs_to_scan.append(ctx.parent)

    all_findings = []
    for d in dirs_to_scan:
        if d.exists():
            findings = scan_directory(d)
            all_findings.extend(findings)

    if not all_findings:
        console.print("[green]✓ No secrets detected.[/green]")
        return

    table = Table(title=f"{len(all_findings)} potential secret(s) found", show_lines=True)
    table.add_column("File", style="dim", max_width=50)
    table.add_column("Line", justify="right", style="dim")
    table.add_column("Type", style="yellow")
    table.add_column("Snippet", max_width=60)

    home = paths.home().parent
    for f in all_findings:
        try:
            from pathlib import Path
            display_path = str(Path(f.file).relative_to(home))
        except ValueError:
            display_path = f.file

        table.add_row(
            display_path,
            str(f.line_number) if f.line_number else "—",
            f.pattern_name,
            f.snippet,
        )

    console.print(table)
    console.print(
        "\n[yellow]These files are excluded from the search index but may exist in git history.[/yellow]"
    )
    console.print("  Review and remove secrets, then run: [bold]innie index[/bold]")
    raise typer.Exit(1)
