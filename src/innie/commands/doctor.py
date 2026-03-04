"""Health check and status commands."""

import typer
from rich.console import Console

from innie.core import paths
from innie.core.config import get

console = Console()


def status():
    """Quick overview of agent, memory stats, hook status, embedding health."""
    agent = paths.active_agent()
    console.print(f"Agent: [bold]{agent}[/bold]")

    # Agent dir check
    adir = paths.agent_dir(agent)
    if not adir.exists():
        console.print("[red]Agent directory missing! Run: innie init[/red]")
        return

    # Data stats
    data = paths.data_dir(agent)
    if data.exists():
        md_count = len(list(data.rglob("*.md")))
        console.print(f"Knowledge base: {md_count} files")
    else:
        console.print("Knowledge base: [dim]empty[/dim]")

    # Session stats
    sessions = paths.sessions_dir(agent)
    if sessions.exists():
        s_count = len(list(sessions.glob("*.md")))
        console.print(f"Session logs: {s_count}")

    # Index stats
    db_path = paths.index_db(agent)
    if db_path.exists():
        try:
            from innie.core.search import index_status, open_db

            conn = open_db(db_path)
            stats = index_status(conn)
            conn.close()
            if stats["has_embeddings"]:
                vec_label = "[green]vectors[/green]"
            else:
                vec_label = "[yellow]FTS only[/yellow]"
            console.print(f"Index: {stats['files']} files, {stats['chunks']} chunks, {vec_label}")
        except Exception:
            console.print("Index: [yellow]error reading[/yellow]")
    else:
        console.print("Index: [dim]not built[/dim]")

    # Hook status
    from innie.backends.registry import discover_backends

    for bname, cls in discover_backends().items():
        instance = cls()
        if instance.detect():
            hooks = instance.check_hooks()
            installed = sum(1 for v in hooks.values() if v)
            total = len(hooks)
            if total > 0:
                if installed == total:
                    hook_status = "[green]all[/green]"
                else:
                    hook_status = f"[yellow]{installed}/{total}[/yellow]"
                console.print(f"Hooks ({bname}): {hook_status}")

    # Trace stats
    from innie.core.trace import trace_db_path

    tdb = trace_db_path(agent)
    if tdb.exists():
        try:
            from innie.core.trace import get_stats, open_trace_db

            conn = open_trace_db(tdb)
            ts = get_stats(conn, agent_name=agent, since=None)
            conn.close()
            cost_str = f"${ts.total_cost_usd:.4f}" if ts.total_cost_usd else "$0"
            console.print(
                f"Traces: {ts.total_sessions} sessions, {ts.total_spans} spans, {cost_str} total"
            )
        except Exception:
            console.print("Traces: [yellow]error reading[/yellow]")
    else:
        console.print("Traces: [dim]no data yet[/dim]")

    # Embedding health
    provider = get("embedding.provider", "docker")
    if provider != "none":
        url = get(f"embedding.{provider}.url", get("embedding.docker.url", "http://localhost:8766"))
        try:
            import httpx

            resp = httpx.get(f"{url}/health", timeout=3.0)
            if resp.status_code == 200:
                console.print(f"Embeddings: [green]healthy[/green] ({url})")
            else:
                console.print(f"Embeddings: [yellow]{resp.status_code}[/yellow] ({url})")
        except Exception:
            console.print(f"Embeddings: [red]unreachable[/red] ({url})")


def doctor():
    """Full system health check."""
    console.print("[bold]innie doctor[/bold]\n")
    checks_passed = 0
    checks_total = 0

    def check(label: str, ok: bool, fix: str = ""):
        nonlocal checks_passed, checks_total
        checks_total += 1
        if ok:
            checks_passed += 1
            console.print(f"  [green]✓[/green] {label}")
        else:
            console.print(f"  [red]✗[/red] {label}")
            if fix:
                console.print(f"    Fix: {fix}")

    # 1. Home dir exists
    check("~/.innie exists", paths.home().exists(), "Run: innie init")

    # 2. Config exists
    check("config.toml exists", paths.config_file().exists(), "Run: innie init")

    # 3. Active agent exists
    agent = paths.active_agent()
    agent_exists = paths.agent_dir(agent).exists()
    check(f"Agent '{agent}' exists", agent_exists, f"Run: innie create {agent}")

    if agent_exists:
        # 4. Profile
        check("profile.yaml exists", paths.profile_file(agent).exists())

        # 5. SOUL.md
        check("SOUL.md exists", paths.soul_file(agent).exists())

        # 6. CONTEXT.md
        check("CONTEXT.md exists", paths.context_file(agent).exists())

        # 7. data/ structure
        check("data/ directory exists", paths.data_dir(agent).exists())
        check("data/journal/ exists", paths.journal_dir(agent).exists())

        # 8. state/ structure
        check("state/ directory exists", paths.state_dir(agent).exists())
        check("state/sessions/ exists", paths.sessions_dir(agent).exists())

    # 9. Backend hooks
    from innie.backends.registry import discover_backends

    for bname, cls in discover_backends().items():
        instance = cls()
        if instance.detect():
            hooks = instance.check_hooks()
            all_ok = all(hooks.values()) if hooks else False
            check(
                f"{bname} hooks installed",
                all_ok,
                f"Run: innie backend install {bname}",
            )

    # 10. Embedding service
    provider = get("embedding.provider", "docker")
    if provider != "none":
        url = get(f"embedding.{provider}.url", get("embedding.docker.url", "http://localhost:8766"))
        try:
            import httpx

            resp = httpx.get(f"{url}/health", timeout=3.0)
            check("Embedding service healthy", resp.status_code == 200)
        except Exception:
            check("Embedding service healthy", False, "Run: innie docker up")

    # 11. Index exists
    check("Semantic index exists", paths.index_db(agent).exists(), "Run: innie index")

    console.print(f"\n  {checks_passed}/{checks_total} checks passed.")


def decay(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without applying them"),
    context_days: int = typer.Option(30, "--context-days", help="Archive context items older than N days"),
    session_days: int = typer.Option(90, "--session-days", help="Compress/remove session logs older than N days"),
):
    """Run memory decay — archive old context items, compress sessions, deindex stale files."""

    from innie.core.decay import decay_all

    agent = paths.active_agent()
    mode = "[dim](dry run)[/dim]" if dry_run else ""
    console.print(f"[bold]Memory decay for '{agent}'[/bold] {mode}\n")

    results = decay_all(
        agent=agent,
        dry_run=dry_run,
        context_max_days=context_days,
        session_max_days=session_days,
    )

    ctx = results["context"]
    console.print(f"  Context: {ctx['archived']} items archived, {ctx['remaining']} remaining")

    sess = results["sessions"]
    console.print(
        f"  Sessions: {sess['compressed']} months compressed, {sess['removed']} files removed"
    )

    idx = results["index"]
    console.print(f"  Index: {idx['removed']} stale entries removed")

    if dry_run:
        console.print("\n[dim]No changes made (dry run). Remove --dry-run to apply.[/dim]")
