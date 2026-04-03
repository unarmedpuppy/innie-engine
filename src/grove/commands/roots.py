"""grove roots — per-task git worktrees with persistent agent sessions.

Each Tasks API task gets an isolated git worktree, a named tmux session, and a
deterministic port. Task state is synced back to the Tasks API so the fleet
knows what's in-flight on this machine.

State layout:
  ~/.grove/roots/state/<task-id>.json   — local workstream state
  ~/.grove/roots/worktrees/<project>/<task-id>/  — git worktrees
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console()


# ── paths ────────────────────────────────────────────────────────────────────


def _roots_home() -> Path:
    from grove.core import paths
    p = paths.home() / "roots"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _state_dir() -> Path:
    d = _roots_home() / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _worktrees_dir() -> Path:
    d = _roots_home() / "worktrees"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_file(task_id: str) -> Path:
    return _state_dir() / f"{task_id}.json"


# ── data model ───────────────────────────────────────────────────────────────


@dataclass
class Workstream:
    task_id: str
    title: str
    project_dir: str
    project_slug: str
    worktree_path: str
    branch: str
    tmux_session: str
    port: int
    agent_type: str         # "shell" | "claude-code" | "grove-agent"
    model: str              # "auto" | "claude-sonnet-4-6" | etc.
    state: str              # "running" | "stopped" | "archived"
    machine: str
    created_at: str
    updated_at: str
    pr_url: str = ""

    def save(self) -> None:
        _state_file(self.task_id).write_text(
            json.dumps(asdict(self), indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, task_id: str) -> "Workstream":
        p = _state_file(task_id)
        if not p.exists():
            raise FileNotFoundError(f"No workstream found for task: {task_id}")
        return cls(**json.loads(p.read_text(encoding="utf-8")))

    @classmethod
    def load_all(cls) -> list["Workstream"]:
        results = []
        for f in sorted(_state_dir().glob("*.json")):
            try:
                results.append(cls(**json.loads(f.read_text(encoding="utf-8"))))
            except Exception:
                continue
        return results


# ── helpers ──────────────────────────────────────────────────────────────────


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:40].strip("-")


def _allocate_port(worktree_path: str) -> int:
    """Deterministic port from DJB2 hash of worktree path. Range: 50001-59999."""
    h = 5381
    for c in worktree_path.encode():
        h = ((h << 5) + h) + c
    return 50001 + (abs(h) % 9999)


def _git_root(path: str) -> str:
    """Return the git root for the given path, or raise."""
    result = subprocess.run(
        ["git", "-C", path, "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"{path} is not inside a git repository")
    return result.stdout.strip()


def _project_slug(project_dir: str) -> str:
    return Path(project_dir).name


def _base_branch(project_dir: str) -> str:
    """Resolve base branch: .grove-roots.json > main > master."""
    config_file = Path(project_dir) / ".grove-roots.json"
    if config_file.exists():
        try:
            cfg = json.loads(config_file.read_text())
            if cfg.get("base_branch"):
                return cfg["base_branch"]
        except Exception:
            pass
    # Detect whether main or master exists
    for candidate in ("main", "master"):
        r = subprocess.run(
            ["git", "-C", project_dir, "rev-parse", "--verify", candidate],
            capture_output=True,
        )
        if r.returncode == 0:
            return candidate
    return "main"


def _tmux_session_name(task_id: str) -> str:
    # tmux session names: alphanumeric + dash/dot/underscore only to be safe
    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", task_id)
    return f"roots-{safe}"


def _tmux_session_exists(session: str) -> bool:
    r = subprocess.run(
        ["tmux", "has-session", "-t", session],
        capture_output=True,
    )
    return r.returncode == 0


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


def _git_dirty(worktree_path: str) -> bool:
    r = subprocess.run(
        ["git", "-C", worktree_path, "status", "--porcelain"],
        capture_output=True, text=True,
    )
    return bool(r.stdout.strip())


def _run_script(script: str, cwd: str, env: dict) -> int:
    """Run a lifecycle script in a subprocess. Returns exit code."""
    result = subprocess.run(
        script, shell=True, cwd=cwd,
        env={**os.environ, **env},
    )
    return result.returncode


# ── lifecycle ─────────────────────────────────────────────────────────────────


def _load_project_config(project_dir: str) -> dict:
    for name in (".grove-roots.json", ".factoryfloor.json"):
        p = Path(project_dir) / name
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
    return {}


def _build_env(ws: Workstream) -> dict:
    return {
        "GR_TASK_ID": ws.task_id,
        "GR_PROJECT": ws.project_slug,
        "GR_PROJECT_DIR": ws.project_dir,
        "GR_WORKTREE_DIR": ws.worktree_path,
        "GR_PORT": str(ws.port),
        "GR_BRANCH": ws.branch,
        "GR_AGENT_TYPE": ws.agent_type,
        "GR_MODEL": ws.model,
        "GR_MACHINE": ws.machine,
    }


# ── CLI commands ──────────────────────────────────────────────────────────────


def new(
    task_id: str = typer.Argument(..., help="Tasks API task ID"),
    project: str = typer.Option(None, "--project", "-p", help="Path to git repo (default: current directory)"),
    agent: str = typer.Option("shell", "--agent", "-a", help="Agent type: shell, claude-code, grove-agent"),
    model: str = typer.Option("auto", "--model", "-m", help="Model: auto, claude-sonnet-4-6, etc."),
    force: bool = typer.Option(False, "--force", help="Re-create if workstream already exists"),
) -> None:
    """Create a worktree + tmux session for a task."""
    from grove.commands.task import TasksClient
    from grove.core import paths

    # Check for existing workstream
    state_path = _state_file(task_id)
    if state_path.exists() and not force:
        ws = Workstream.load(task_id)
        console.print(f"[yellow]Workstream already exists[/yellow] for {task_id}")
        console.print(f"  worktree: {ws.worktree_path}")
        console.print(f"  branch:   {ws.branch}")
        console.print(f"  session:  {ws.tmux_session}")
        console.print(f"\nRun [cyan]g roots open {task_id}[/cyan] to attach, or use [cyan]--force[/cyan] to recreate.")
        raise typer.Exit(0)

    # Fetch task
    client = TasksClient()
    try:
        task = client.get(task_id)
    except Exception as e:
        console.print(f"[red]Task not found:[/red] {task_id} ({e})")
        raise typer.Exit(1)

    console.print(f"[bold]{task['title']}[/bold]  [{task.get('priority', '?')}]")

    # Resolve project directory
    project_dir = project or os.getcwd()
    try:
        project_dir = _git_root(project_dir)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    slug = _project_slug(project_dir)
    base_branch = _base_branch(project_dir)
    cfg = _load_project_config(project_dir)

    # Agent type from config if not explicitly set
    if agent == "shell" and cfg.get("agent"):
        agent = cfg["agent"]
    if model == "auto" and cfg.get("model"):
        model = cfg["model"]

    # Paths
    worktree_path = str(_worktrees_dir() / slug / task_id)
    branch = f"roots/{task_id}"
    tmux_session = _tmux_session_name(task_id)
    port = _allocate_port(worktree_path)
    machine = os.uname().nodename

    console.print(f"  project:  {project_dir}")
    console.print(f"  worktree: {worktree_path}")
    console.print(f"  branch:   {branch}  (from {base_branch})")
    console.print(f"  port:     {port}")

    # Create worktree
    Path(worktree_path).parent.mkdir(parents=True, exist_ok=True)
    console.print(f"\n[dim]Creating worktree...[/dim]")

    r = subprocess.run(
        ["git", "-C", project_dir, "worktree", "add", "-b", branch, worktree_path, base_branch],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        # Branch may already exist — try without -b
        r2 = subprocess.run(
            ["git", "-C", project_dir, "worktree", "add", worktree_path, branch],
            capture_output=True, text=True,
        )
        if r2.returncode != 0:
            console.print(f"[red]git worktree add failed:[/red]\n{r.stderr}\n{r2.stderr}")
            raise typer.Exit(1)

    # Build workstream record
    now = datetime.now(timezone.utc).isoformat()
    ws = Workstream(
        task_id=task_id,
        title=task["title"],
        project_dir=project_dir,
        project_slug=slug,
        worktree_path=worktree_path,
        branch=branch,
        tmux_session=tmux_session,
        port=port,
        agent_type=agent,
        model=model,
        state="running",
        machine=machine,
        created_at=now,
        updated_at=now,
    )

    # Run setup script
    setup = cfg.get("setup") or (cfg.get("setupScript") if cfg else None)
    if setup:
        console.print(f"[dim]Running setup: {setup}[/dim]")
        code = _run_script(setup, worktree_path, _build_env(ws))
        if code != 0:
            console.print(f"[yellow]Setup exited {code} — continuing anyway[/yellow]")

    # Launch tmux session
    console.print(f"[dim]Starting tmux session: {tmux_session}[/dim]")
    env_args = []
    for k, v in _build_env(ws).items():
        env_args += ["-e", f"{k}={v}"]

    if agent == "claude-code":
        shell_cmd = "claude --dangerously-skip-permissions"
    elif agent == "grove-agent":
        shell_cmd = f"g serve --model {model}"
    else:
        shell_cmd = os.environ.get("SHELL", "/bin/zsh")

    subprocess.run([
        "tmux", "new-session", "-d",
        "-s", tmux_session,
        "-c", worktree_path,
        *env_args,
        shell_cmd,
    ])

    # Save state
    ws.save()

    # Tag Tasks API
    try:
        client.tag(task_id, "roots_state", "running")
        client.tag(task_id, "roots_machine", machine)
        client.tag(task_id, "roots_worktree", worktree_path)
        client.tag(task_id, "roots_branch", branch)
        client.tag(task_id, "roots_port", str(port))
    except Exception as e:
        console.print(f"[yellow]Warning: could not update Tasks API tags: {e}[/yellow]")

    console.print(f"\n[green]✓ Workstream ready[/green]")
    console.print(f"  [cyan]g roots open {task_id}[/cyan]  — attach to session")
    console.print(f"  [cyan]g roots rm {task_id}[/cyan]    — teardown when done")


def open_workstream(
    task_id: str = typer.Argument(..., help="Task ID"),
) -> None:
    """Attach to the tmux session for a task."""
    try:
        ws = Workstream.load(task_id)
    except FileNotFoundError:
        console.print(f"[red]No workstream for {task_id}.[/red] Run [cyan]g roots new {task_id}[/cyan] first.")
        raise typer.Exit(1)

    if not _tmux_session_exists(ws.tmux_session):
        console.print(f"[yellow]Session {ws.tmux_session} not running.[/yellow] Starting it...")
        env_args = []
        for k, v in _build_env(ws).items():
            env_args += ["-e", f"{k}={v}"]
        shell = os.environ.get("SHELL", "/bin/zsh")
        subprocess.run([
            "tmux", "new-session", "-d",
            "-s", ws.tmux_session,
            "-c", ws.worktree_path,
            *env_args,
            shell,
        ])

    result = subprocess.run(["tmux", "attach-session", "-t", ws.tmux_session])
    sys.exit(result.returncode)


def list_workstreams(
    all: bool = typer.Option(False, "--all", help="Include archived workstreams"),
) -> None:
    """List active workstreams on this machine."""
    workstreams = Workstream.load_all()
    if not all:
        workstreams = [w for w in workstreams if w.state != "archived"]

    if not workstreams:
        console.print("[dim]No active workstreams.[/dim]")
        return

    table = Table(title=f"Roots — {os.uname().nodename}", show_lines=False, expand=False, box=None, pad_edge=False)
    table.add_column("Task", style="cyan", no_wrap=True, min_width=10, max_width=22)
    table.add_column("  ", no_wrap=True, width=5)    # session state
    table.add_column("  ", no_wrap=True, width=6)    # dirty
    table.add_column("Title", no_wrap=True, min_width=20, max_width=32)
    table.add_column("Branch", no_wrap=True, min_width=14, max_width=24)
    table.add_column("  ", no_wrap=True, width=4)    # age

    for ws in workstreams:
        session_live = _tmux_session_exists(ws.tmux_session)
        session_str = "[green]live[/green]" if session_live else "[dim]dead[/dim]"
        worktree_exists = Path(ws.worktree_path).exists()
        dirty = worktree_exists and _git_dirty(ws.worktree_path)
        dirty_str = "[yellow]dirty[/yellow]" if dirty else "[dim]clean[/dim]"
        title = ws.title if len(ws.title) <= 32 else ws.title[:29] + "..."
        table.add_row(
            ws.task_id,
            session_str,
            dirty_str,
            title,
            ws.branch,
            f"[dim]{_age(ws.created_at)}[/dim]",
        )

    console.print(table)


def rm(
    task_id: str = typer.Argument(..., help="Task ID"),
    force: bool = typer.Option(False, "--force", help="Skip teardown script and force remove"),
) -> None:
    """Tear down a workstream: teardown script, remove worktree, kill session."""
    try:
        ws = Workstream.load(task_id)
    except FileNotFoundError:
        console.print(f"[red]No workstream for {task_id}.[/red]")
        raise typer.Exit(1)

    # Run teardown script
    if not force:
        cfg = _load_project_config(ws.project_dir)
        teardown = cfg.get("teardown") or (cfg.get("teardownScript") if cfg else None)
        if teardown and Path(ws.worktree_path).exists():
            console.print(f"[dim]Running teardown: {teardown}[/dim]")
            _run_script(teardown, ws.worktree_path, _build_env(ws))

    # Kill tmux session
    if _tmux_session_exists(ws.tmux_session):
        subprocess.run(["tmux", "kill-session", "-t", ws.tmux_session], capture_output=True)
        console.print(f"[dim]Killed session {ws.tmux_session}[/dim]")

    # Remove worktree
    if Path(ws.worktree_path).exists():
        r = subprocess.run(
            ["git", "-C", ws.project_dir, "worktree", "remove", "--force", ws.worktree_path],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            console.print(f"[yellow]worktree remove warning:[/yellow] {r.stderr.strip()}")
        else:
            console.print(f"[dim]Removed worktree {ws.worktree_path}[/dim]")

    # Update state to archived and persist
    ws.state = "archived"
    ws.updated_at = datetime.now(timezone.utc).isoformat()
    ws.save()

    # Update Tasks API
    from grove.commands.task import TasksClient
    try:
        TasksClient().tag(task_id, "roots_state", "archived")
    except Exception as e:
        console.print(f"[yellow]Warning: could not update Tasks API: {e}[/yellow]")

    console.print(f"[green]✓ Workstream {task_id} archived[/green]")


def status(
    task_id: str = typer.Argument(None, help="Task ID (omit for all)"),
) -> None:
    """Show workstream status. Omit task-id to show all."""
    if task_id:
        _status_single(task_id)
    else:
        list_workstreams()


def _status_single(task_id: str) -> None:
    try:
        ws = Workstream.load(task_id)
    except FileNotFoundError:
        console.print(f"[red]No workstream for {task_id}.[/red]")
        raise typer.Exit(1)

    from grove.commands.task import TasksClient
    try:
        task = TasksClient().get(task_id)
    except Exception:
        task = {}

    session_live = _tmux_session_exists(ws.tmux_session)
    worktree_exists = Path(ws.worktree_path).exists()
    dirty = _git_dirty(ws.worktree_path) if worktree_exists else False

    console.print(f"\n[bold cyan]{ws.task_id}[/bold cyan]  [dim]{ws.state}[/dim]")
    console.print(f"  title:    {ws.title}")
    console.print(f"  project:  {ws.project_dir}")
    console.print(f"  worktree: {ws.worktree_path}  {'[yellow](dirty)[/yellow]' if dirty else '[dim](clean)[/dim]'}")
    console.print(f"  branch:   {ws.branch}")
    console.print(f"  port:     {ws.port}")
    console.print(f"  session:  {ws.tmux_session}  {'[green](live)[/green]' if session_live else '[dim](not running)[/dim]'}")
    console.print(f"  agent:    {ws.agent_type}  model={ws.model}")
    console.print(f"  machine:  {ws.machine}")
    console.print(f"  created:  {ws.created_at[:10]}  ({_age(ws.created_at)} ago)")

    if ws.pr_url:
        console.print(f"  PR:       {ws.pr_url}")

    meta = task.get("metadata") or {}
    roots_keys = {k: v for k, v in meta.items() if k.startswith("roots_")}
    if roots_keys:
        console.print(f"\n  [dim]tasks api tags:[/dim]")
        for k, v in roots_keys.items():
            console.print(f"    {k}: {v}")

    console.print()


def recover() -> None:
    """Find orphaned or interrupted workstreams with unsaved changes.

    Shows all non-archived workstreams whose tmux session is dead or whose
    worktree has uncommitted changes. Prints the commands to revive each one.
    """
    workstreams = [w for w in Workstream.load_all() if w.state != "archived"]

    if not workstreams:
        console.print("[dim]No active workstreams found.[/dim]")
        return

    orphaned = []
    for ws in workstreams:
        worktree_exists = Path(ws.worktree_path).exists()
        session_live = _tmux_session_exists(ws.tmux_session)
        dirty = worktree_exists and _git_dirty(ws.worktree_path)
        orphaned.append((ws, worktree_exists, session_live, dirty))

    # Only report ones worth recovering: dead session OR dirty worktree
    recoverable = [(ws, wt, sl, d) for ws, wt, sl, d in orphaned if not sl or d]

    if not recoverable:
        console.print("[green]✓ No orphaned workstreams.[/green] All sessions live and worktrees clean.")
        return

    console.print(f"\n[bold]Recoverable workstreams ({len(recoverable)})[/bold]\n")

    for ws, worktree_exists, session_live, dirty in recoverable:
        status_parts = []
        if not session_live:
            status_parts.append("[dim]session dead[/dim]")
        if dirty:
            status_parts.append("[yellow]uncommitted changes[/yellow]")
        if not worktree_exists:
            status_parts.append("[red]worktree missing[/red]")

        console.print(f"  [cyan]{ws.task_id}[/cyan]  {ws.title[:48]}")
        console.print(f"    {' · '.join(status_parts)}")
        console.print(f"    branch: {ws.branch}  |  {ws.worktree_path}")

        if worktree_exists and dirty:
            # Show a summary of what's dirty
            r = subprocess.run(
                ["git", "-C", ws.worktree_path, "status", "--short"],
                capture_output=True, text=True,
            )
            for line in r.stdout.strip().splitlines()[:5]:
                console.print(f"    [dim]{line}[/dim]")

        console.print(f"    → [cyan]g roots open {ws.task_id}[/cyan]    (reattach)")
        if worktree_exists and dirty:
            console.print(f"    → [cyan]g roots commit {ws.task_id} --all[/cyan]  (save changes)")
        console.print()


# ── Gitea client ──────────────────────────────────────────────────────────────


_GITEA_URL = "https://gitea.server.unarmedpuppy.com"


class GiteaClient:
    """Thin Gitea API client. Token from GITEA_TOKEN env."""

    def __init__(self) -> None:
        self.base_url = (os.environ.get("GITEA_URL") or _GITEA_URL).rstrip("/")
        self.token = os.environ.get("GITEA_TOKEN", "")
        if not self.token:
            raise RuntimeError("GITEA_TOKEN not set — add it to ~/.grove/.env")

    def _headers(self) -> dict:
        return {"Authorization": f"token {self.token}", "Content-Type": "application/json"}

    def _get(self, path: str, **params) -> dict | list:
        import httpx
        r = httpx.get(f"{self.base_url}/api/v1{path}", headers=self._headers(),
                      params={k: v for k, v in params.items() if v is not None}, timeout=10.0)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, data: dict) -> dict:
        import httpx
        r = httpx.post(f"{self.base_url}/api/v1{path}", headers=self._headers(),
                       json=data, timeout=10.0)
        r.raise_for_status()
        return r.json()

    def get_repo(self, owner: str, repo: str) -> dict:
        return self._get(f"/repos/{owner}/{repo}")

    def create_pr(self, owner: str, repo: str, title: str, body: str,
                  head: str, base: str) -> dict:
        return self._post(f"/repos/{owner}/{repo}/pulls", {
            "title": title, "body": body, "head": head, "base": base,
        })

    def get_pr_for_branch(self, owner: str, repo: str, branch: str) -> dict | None:
        prs = self._get(f"/repos/{owner}/{repo}/pulls", state="open", head=branch)
        if isinstance(prs, list) and prs:
            return prs[0]
        return None

    def get_ci_statuses(self, owner: str, repo: str, sha: str) -> list:
        try:
            return self._get(f"/repos/{owner}/{repo}/statuses/{sha}") or []
        except Exception:
            return []


def _gitea_owner_repo(project_dir: str) -> tuple[str, str]:
    """Parse (owner, repo) from git remote origin URL."""
    r = subprocess.run(
        ["git", "-C", project_dir, "remote", "get-url", "origin"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise ValueError("No git remote origin found")
    url = r.stdout.strip().rstrip("/")
    url = re.sub(r"\.git$", "", url)
    m = re.search(r"/([^/:]+/[^/]+)$", url)
    if not m:
        raise ValueError(f"Cannot parse owner/repo from remote: {url}")
    parts = m.group(1).split("/")
    return parts[0], parts[1]


# ── LLM helper ────────────────────────────────────────────────────────────────


def _call_llm(prompt: str, model: str = "auto") -> str:
    """Call the llm-router OpenAI-compatible API. Falls back to claude CLI."""
    llm_url = os.environ.get("LLM_ROUTER_URL", "https://homelab-ai-api.server.unarmedpuppy.com")
    llm_key = os.environ.get("LLM_ROUTER_API_KEY", "")

    if llm_url and llm_key:
        try:
            import httpx
            r = httpx.post(
                f"{llm_url.rstrip('/')}/v1/chat/completions",
                headers={"Authorization": f"Bearer {llm_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 512, "temperature": 0.2},
                timeout=15.0,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            console.print(f"[dim]llm-router unavailable ({type(e).__name__}), falling back to claude...[/dim]")

    # Fallback: claude CLI — unset CLAUDECODE to allow nested invocation
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    r = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "text",
         "--no-session-persistence", "--dangerously-skip-permissions"],
        capture_output=True, text=True, timeout=60, env=env,
    )
    if r.returncode == 0:
        return r.stdout.strip()
    raise RuntimeError(f"LLM call failed: {r.stderr.strip()}")


# ── Phase 2: run / stop / init ────────────────────────────────────────────────


def run_dev(
    task_id: str = typer.Argument(..., help="Task ID"),
) -> None:
    """Start the 'run' dev server script for a workstream."""
    try:
        ws = Workstream.load(task_id)
    except FileNotFoundError:
        console.print(f"[red]No workstream for {task_id}.[/red]")
        raise typer.Exit(1)

    cfg = _load_project_config(ws.project_dir)
    run_script = cfg.get("run")
    if not run_script:
        console.print(f"[yellow]No 'run' script in .grove-roots.json for {ws.project_slug}[/yellow]")
        raise typer.Exit(1)

    env = _build_env(ws)
    console.print(f"[dim]Running on port {ws.port}: {run_script}[/dim]")

    # Run inside the tmux session's window so it's visible when attached
    if _tmux_session_exists(ws.tmux_session):
        cmd = f"cd {ws.worktree_path}"
        for k, v in env.items():
            cmd += f" && export {k}={v}"
        cmd += f" && {run_script}"
        subprocess.run(["tmux", "send-keys", "-t", ws.tmux_session, cmd, "Enter"])
        console.print(f"[green]Started in session {ws.tmux_session}[/green] — attach with [cyan]g roots open {task_id}[/cyan]")
    else:
        console.print(f"[yellow]Session not running — use [cyan]g roots open {task_id}[/cyan] first[/yellow]")


def init(
    project: str = typer.Option(None, "--project", "-p", help="Project dir (default: cwd)"),
) -> None:
    """Create a .grove-roots.json config in the current project."""
    project_dir = project or os.getcwd()
    config_path = Path(project_dir) / ".grove-roots.json"

    if config_path.exists():
        console.print(f"[yellow].grove-roots.json already exists at {config_path}[/yellow]")
        raise typer.Exit(0)

    cfg = {
        "setup": "",
        "run": "PORT=$GR_PORT npm run dev",
        "teardown": "",
        "agent": "claude-code",
        "model": "auto",
        "base_branch": "main",
    }
    config_path.write_text(json.dumps(cfg, indent=2) + "\n")
    console.print(f"[green]Created[/green] {config_path}")
    console.print("Edit it to add your setup/run/teardown scripts.")


# ── Phase 4: commit / push / pr / ci ─────────────────────────────────────────


def commit(
    task_id: str = typer.Argument(..., help="Task ID"),
    all: bool = typer.Option(False, "--all", "-a", help="Stage all changes before committing"),
    message: str = typer.Option(None, "--message", "-m", help="Commit message (skip LLM generation)"),
) -> None:
    """LLM-assisted commit in the task worktree."""
    try:
        ws = Workstream.load(task_id)
    except FileNotFoundError:
        console.print(f"[red]No workstream for {task_id}.[/red]")
        raise typer.Exit(1)

    wt = ws.worktree_path
    if not Path(wt).exists():
        console.print(f"[red]Worktree not found: {wt}[/red]")
        raise typer.Exit(1)

    if all:
        subprocess.run(["git", "-C", wt, "add", "-A"], check=True)

    # Check for staged changes
    r = subprocess.run(["git", "-C", wt, "diff", "--staged", "--stat"], capture_output=True, text=True)
    if not r.stdout.strip():
        console.print("[yellow]Nothing staged. Use --all to stage all changes.[/yellow]")
        raise typer.Exit(1)

    if not message:
        diff = subprocess.run(
            ["git", "-C", wt, "diff", "--staged", "--stat"],
            capture_output=True, text=True,
        ).stdout.strip()
        diff_body = subprocess.run(
            ["git", "-C", wt, "diff", "--staged", "--unified=2"],
            capture_output=True, text=True,
        ).stdout.strip()[:3000]

        console.print("[dim]Generating commit message...[/dim]")
        prompt = (
            f"Write a conventional commit message for these changes.\n"
            f"Task: {ws.title}\n\n"
            f"Changed files:\n{diff}\n\n"
            f"Diff (truncated):\n{diff_body}\n\n"
            f"Output ONLY the commit message. One subject line (max 72 chars), "
            f"optionally a blank line and body. Use conventional commits format "
            f"(feat/fix/refactor/docs/chore). No markdown, no quotes."
        )
        message = _call_llm(prompt, model=ws.model)
        console.print(f"\n[bold]{message}[/bold]\n")

    result = subprocess.run(["git", "-C", wt, "commit", "-m", message])
    if result.returncode != 0:
        raise typer.Exit(1)


def push(
    task_id: str = typer.Argument(..., help="Task ID"),
) -> None:
    """Push the task branch to Gitea."""
    try:
        ws = Workstream.load(task_id)
    except FileNotFoundError:
        console.print(f"[red]No workstream for {task_id}.[/red]")
        raise typer.Exit(1)

    console.print(f"[dim]Pushing {ws.branch} → origin...[/dim]")
    r = subprocess.run(
        ["git", "-C", ws.worktree_path, "push", "-u", "origin", ws.branch],
    )
    if r.returncode != 0:
        raise typer.Exit(1)
    console.print(f"[green]Pushed[/green] {ws.branch}")


def pr(
    task_id: str = typer.Argument(..., help="Task ID"),
    draft: bool = typer.Option(False, "--draft", help="Create as draft PR"),
) -> None:
    """Create a Gitea PR with LLM-generated description."""
    try:
        ws = Workstream.load(task_id)
    except FileNotFoundError:
        console.print(f"[red]No workstream for {task_id}.[/red]")
        raise typer.Exit(1)

    # Check for existing PR
    try:
        owner, repo_name = _gitea_owner_repo(ws.project_dir)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    gitea = GiteaClient()
    existing = gitea.get_pr_for_branch(owner, repo_name, ws.branch)
    if existing:
        pr_url = existing.get("html_url", "")
        console.print(f"[yellow]PR already exists:[/yellow] {pr_url}")
        raise typer.Exit(0)

    # Ensure branch is pushed
    console.print(f"[dim]Pushing {ws.branch}...[/dim]")
    subprocess.run(
        ["git", "-C", ws.worktree_path, "push", "-u", "origin", ws.branch],
        capture_output=True,
    )

    # Get commits and diff stats
    base = _base_branch(ws.project_dir)
    log = subprocess.run(
        ["git", "-C", ws.worktree_path, "log", f"{base}..HEAD", "--oneline"],
        capture_output=True, text=True,
    ).stdout.strip()
    stat = subprocess.run(
        ["git", "-C", ws.worktree_path, "diff", "--stat", f"{base}..HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()

    # Fetch task description for context
    from grove.commands.task import TasksClient
    try:
        task = TasksClient().get(task_id)
        task_desc = (task.get("description") or "")[:500]
    except Exception:
        task_desc = ""

    # Generate PR title + body
    console.print("[dim]Generating PR description...[/dim]")
    prompt = (
        f"Write a GitHub pull request title and description for this change.\n\n"
        f"Task: {ws.title}\n"
        f"Task description: {task_desc}\n\n"
        f"Commits:\n{log or '(no commits yet)'}\n\n"
        f"Changed files:\n{stat or '(no changes)'}\n\n"
        f"Output format — first line is the PR title (conventional commits style, max 70 chars), "
        f"then a blank line, then the PR body in markdown. "
        f"Include a ## Summary section and ## Test plan section. "
        f"Reference the task ID: {task_id}. No extra commentary."
    )
    llm_output = _call_llm(prompt, model=ws.model)

    lines = llm_output.strip().splitlines()
    pr_title = lines[0].strip()
    pr_body = "\n".join(lines[2:]).strip() if len(lines) > 2 else ""

    console.print(f"\n[bold]{pr_title}[/bold]")

    # Create PR
    result = gitea.create_pr(owner, repo_name, pr_title, pr_body, ws.branch, base)
    pr_url = result.get("html_url", "")

    # Update workstream and task
    ws.pr_url = pr_url
    ws.updated_at = datetime.now(timezone.utc).isoformat()
    ws.save()

    try:
        TasksClient().tag(task_id, "roots_pr_url", pr_url)
        TasksClient().update(task_id, status="IN_PROGRESS")
    except Exception:
        pass

    console.print(f"\n[green]PR created:[/green] {pr_url}")


def ci(
    task_id: str = typer.Argument(..., help="Task ID"),
) -> None:
    """Check CI status for the task branch."""
    try:
        ws = Workstream.load(task_id)
    except FileNotFoundError:
        console.print(f"[red]No workstream for {task_id}.[/red]")
        raise typer.Exit(1)

    try:
        owner, repo_name = _gitea_owner_repo(ws.project_dir)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    sha = subprocess.run(
        ["git", "-C", ws.worktree_path, "rev-parse", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()

    if not sha:
        console.print("[yellow]No commits on branch yet.[/yellow]")
        raise typer.Exit(0)

    gitea = GiteaClient()
    statuses = gitea.get_ci_statuses(owner, repo_name, sha)

    if not statuses:
        console.print(f"[dim]No CI status for {sha[:8]} — pipeline may not have run yet.[/dim]")
        return

    for s in statuses[:5]:
        state = s.get("status", "?")
        context = s.get("context", "?")
        color = {"success": "green", "failure": "red", "pending": "yellow"}.get(state, "white")
        console.print(f"  [{color}]{state}[/{color}]  {context}  [dim]{sha[:8]}[/dim]")
