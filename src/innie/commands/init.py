"""innie init — interactive setup wizard and hook event handler."""

import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console

from innie.core import paths
from innie.core.config import DEFAULT_CONFIG

console = Console()


def init(
    local: bool = typer.Option(
        False, "--local", help="Local-only mode (no Docker, no embeddings, keyword search only)"
    ),
    yes: bool = typer.Option(False, "-y", "--yes", help="Accept all defaults non-interactively"),
):
    """Create ~/.innie/, run setup wizard, install hooks, create default agent."""
    if not yes and not local:
        from innie.tui.detect import is_interactive

        if is_interactive():
            from innie.tui.apps.intro import IntroApp
            from innie.tui.apps.init_wizard import run_init_wizard

            IntroApp().run()
            data = run_init_wizard(local=local)
            if data is None:
                raise typer.Abort()
            _execute_setup(
                innie_home=paths.home(),
                **{k: v for k, v in data.items() if k not in ("mode",)},
            )
            return

    console.print("\n  [bold]innie-engine[/bold] — persistent memory for AI coding assistants\n")

    innie_home = paths.home()
    if innie_home.exists() and (innie_home / "config.toml").exists():
        if yes:
            pass  # Overwrite silently
        elif not typer.confirm("  ~/.innie already exists. Reconfigure?", default=False):
            raise typer.Abort()

    # ── Step 1: Identity ─────────────────────────────────────────────────

    if yes:
        name = os.environ.get("USER", "user")
        tz = "America/Chicago"
    else:
        name = typer.prompt("  Your name", default=os.environ.get("USER", ""))
        tz = typer.prompt("  Timezone", default="America/Chicago")

    # ── Step 2: Agent ────────────────────────────────────────────────────

    if yes:
        agent_name = "innie"
        role = "Work Second Brain"
    else:
        agent_name = typer.prompt("\n  Agent name", default="innie")
        role = typer.prompt("  Role", default="Work Second Brain")

    # ── Step 3: Setup mode ───────────────────────────────────────────────

    embed_provider = "none"
    enable_heartbeat = False
    enable_git = False
    selected_backends: list[str] = []

    if local:
        console.print("  [dim]Local-only mode: keyword search, no Docker, no heartbeat[/dim]")
        embed_provider = "none"
        enable_heartbeat = False
    elif yes:
        embed_provider = "none"
        enable_heartbeat = False
    else:
        # Setup mode selection
        console.print("\n  [bold]How do you want to use innie?[/bold]")
        console.print("  [1] Full — semantic search (Docker), heartbeat, everything")
        console.print("  [2] Lightweight — keyword search only, no Docker required")
        console.print("  [3] Custom — choose each feature")
        mode = typer.prompt("  Choice", default="2")

        if mode == "1":
            embed_provider = "docker"
            enable_heartbeat = True
            enable_git = True
        elif mode == "2":
            embed_provider = "none"
            enable_heartbeat = False
            enable_git = False
        else:
            # Custom mode — pick each feature
            embed_provider, enable_heartbeat, enable_git = _custom_setup()

    # ── Step 4: Backend detection ────────────────────────────────────────

    from innie.backends.registry import discover_backends

    backends = discover_backends()

    if yes or local:
        # Auto-select detected backends
        for bname, cls in backends.items():
            if cls().detect():
                selected_backends.append(bname)
        if selected_backends:
            console.print(f"  Auto-detected backends: {', '.join(selected_backends)}")
    else:
        console.print("\n  [bold]AI tools to integrate:[/bold]")
        for bname, cls in backends.items():
            instance = cls()
            detected = instance.detect()
            marker = "[green]detected[/green]" if detected else "[dim]not found[/dim]"
            if typer.confirm(f"    {bname} ({marker})", default=detected):
                selected_backends.append(bname)

    # ── Step 5: Git backup ───────────────────────────────────────────────

    if not yes and not local and enable_git is False:
        # Only ask if not already set by mode selection
        console.print("\n  [bold]Version control for knowledge base?[/bold]")
        console.print("  Git-tracking data/ lets you back up and sync your knowledge base.")
        enable_git = typer.confirm("  Initialize git repo in ~/.innie?", default=False)

    # ── Step 6: Update source ────────────────────────────────────────────

    _GITHUB_URL = "git+https://github.com/joshuajenquist/innie-engine.git"

    if yes or local:
        update_source = _GITHUB_URL
        update_installer = "uv"
    else:
        console.print("\n  [bold]Update source for `innie update`[/bold]")
        console.print(f"  [1] GitHub           {_GITHUB_URL}")
        console.print("  [2] Custom git URL   (private Gitea, GitLab, etc.)")
        console.print("  [3] Local path       (editable install — auto-updates from source)")
        console.print("  [4] Skip             (configure later in config.toml)")
        src_choice = typer.prompt("  Choice", default="1")

        if src_choice == "2":
            update_source = typer.prompt("  Git URL", default="")
        elif src_choice == "3":
            update_source = typer.prompt("  Path to local clone", default=str(Path.home() / "workspace/innie-engine"))
        elif src_choice == "4":
            update_source = ""
        else:
            update_source = _GITHUB_URL

        if update_source and not update_source.startswith("/") and not update_source.startswith("~"):
            update_installer = "uv" if typer.confirm("  Use uv (recommended)?", default=True) else "pip"
        else:
            update_installer = "uv"

    # ── Create everything ────────────────────────────────────────────────

    console.print()
    _execute_setup(
        innie_home=innie_home,
        name=name,
        tz=tz,
        agent_name=agent_name,
        role=role,
        embed_provider=embed_provider,
        enable_heartbeat=enable_heartbeat,
        enable_git=enable_git,
        selected_backends=selected_backends,
        update_source=update_source,
        update_installer=update_installer,
    )


def _custom_setup() -> tuple[str, bool, bool]:
    """Interactive custom feature selection. Returns (embed_provider, heartbeat, git)."""

    # Semantic search
    console.print("\n  [bold]Semantic search[/bold] (vector similarity + keyword)")
    console.print("  [1] Docker embedding service (recommended — sandboxed, ~500MB)")
    console.print("  [2] External endpoint (Ollama, OpenAI, etc.)")
    console.print("  [3] Skip (keyword search only — still works great, no setup)")
    embed_choice = typer.prompt("  Choice", default="3")
    embed_provider = {"1": "docker", "2": "external", "3": "none"}.get(embed_choice, "none")

    if embed_provider == "external":
        console.print(
            "\n  [dim]Configure the endpoint in ~/.innie/config.toml"
            " under [embedding.external][/dim]"
        )

    # Heartbeat
    console.print("\n  [bold]Heartbeat[/bold] (auto-extracts memories from sessions)")
    console.print("  Runs every 30 min: collects session data, AI extracts learnings,")
    console.print("  routes to journal/learnings/projects.")

    from pathlib import Path as _Path

    has_openclaw = (_Path.home() / ".openclaw" / "openclaw.json").exists()
    if has_openclaw:
        console.print("  [1] Yes — install cron job (OpenClaw provider detected)")
    else:
        console.print("  [1] Yes — install cron job (requires Anthropic API key or external URL)")
    console.print("  [2] No — I'll run `innie heartbeat run` manually")
    hb_choice = typer.prompt("  Choice", default="1" if has_openclaw else "2")
    enable_heartbeat = hb_choice == "1"

    # Git
    console.print("\n  [bold]Git backup[/bold]")
    console.print("  Initialize ~/.innie as a git repo? Your knowledge base (data/)")
    console.print("  will be version-controlled. Push to a remote for backup.")
    enable_git = typer.confirm("  Enable git?", default=False)

    return embed_provider, enable_heartbeat, enable_git


def _execute_setup(
    *,
    innie_home: Path,
    name: str,
    tz: str,
    agent_name: str,
    role: str,
    embed_provider: str,
    enable_heartbeat: bool,
    enable_git: bool,
    auto_push: bool = False,
    selected_backends: list[str] | None = None,
    install_alias: bool = False,
    alias_text: str = "",
    user_md: str = "",
    soul_content: str = "",
    context_content: str = "",
    update_source: str = "",
    update_installer: str = "uv",
):
    """Execute all setup steps after wizard is complete."""

    # 1. Config
    innie_home.mkdir(parents=True, exist_ok=True)
    # Build config from template — use unique markers to avoid ambiguous replaces
    config_content = DEFAULT_CONFIG
    config_content = config_content.replace('name = ""', f'name = "{name}"', 1)
    config_content = config_content.replace('timezone = "UTC"', f'timezone = "{tz}"', 1)
    config_content = config_content.replace('agent = "innie"', f'agent = "{agent_name}"', 1)
    config_content = config_content.replace(
        'provider = "docker"', f'provider = "{embed_provider}"', 1
    )
    # heartbeat.enabled is the only "enabled = false" in the template
    config_content = config_content.replace(
        "enabled = false",
        f"enabled = {'true' if enable_heartbeat else 'false'}",
        1,
    )
    config_content = config_content.replace(
        "auto_commit = false",
        f"auto_commit = {'true' if enable_git else 'false'}",
        1,
    )
    config_content = config_content.replace(
        "auto_push = false",
        f"auto_push = {'true' if auto_push else 'false'}",
        1,
    )
    config_content = config_content.replace(
        'source = ""',
        f'source = "{update_source}"',
        1,
    )
    config_content = config_content.replace(
        'installer = "uv"',
        f'installer = "{update_installer}"',
        1,
    )
    (innie_home / "config.toml").write_text(config_content)
    console.print("  [green]✓[/green] Created config.toml")

    # 2. User profile
    (innie_home / "user.md").write_text(user_md or f"# {name}\n\nTimezone: {tz}\n")
    console.print("  [green]✓[/green] Created user.md")

    # 3. Create default agent
    _create_agent(agent_name, role, soul_content=soul_content or None, context_content=context_content or None)

    # 4. Install hooks for selected backends
    hooks_dir = Path(__file__).parent.parent / "hooks"
    for bname in (selected_backends or []):
        try:
            from innie.backends.registry import get_backend

            backend = get_backend(bname)
            backend.install_hooks(hooks_dir)
            console.print(f"  [green]✓[/green] Installed hooks into {bname}")
        except Exception as e:
            console.print(f"  [yellow]![/yellow] Failed to install {bname} hooks: {e}")

    # 5. Shell alias
    if install_alias and alias_text:
        try:
            from innie.commands.alias import _get_rc_file

            rc_file = _get_rc_file()
            content = rc_file.read_text() if rc_file.exists() else ""
            prefix = f"alias {agent_name}="
            lines = [ln for ln in content.split("\n") if not ln.strip().startswith(prefix)]
            lines.append(alias_text)
            rc_file.write_text("\n".join(lines))
            console.print(f"  [green]✓[/green] Alias '{agent_name}' added to {rc_file}")
            console.print(f"  [dim]Run: source {rc_file}[/dim]")
        except Exception as e:
            console.print(f"  [yellow]![/yellow] Could not write alias: {e}")

    # 7. Docker compose for embeddings
    if embed_provider == "docker":
        _setup_docker_embeddings(innie_home)

    # 8. Heartbeat scheduler
    if enable_heartbeat:
        _install_scheduler()
        scheduler = "launchd" if sys.platform == "darwin" else "cron"
        console.print(f"  [green]✓[/green] Installed heartbeat {scheduler} (every 30 min)")

    # 9. Git init
    if enable_git:
        _setup_git(innie_home)

    # Done
    console.print("\n  [bold green]Setup complete![/bold green]")
    console.print(f"\n  Your agent's memory lives at: {paths.agent_dir(agent_name)}")

    features = []
    if embed_provider != "none":
        features.append(f"semantic search ({embed_provider})")
    else:
        features.append("keyword search")
    if enable_heartbeat:
        features.append("heartbeat")
    if enable_git:
        features.append("git backup")
    if selected_backends:
        features.append(f"hooks: {', '.join(selected_backends)}")

    console.print(f"  Features: {' | '.join(features)}")
    console.print("  Run: [bold]innie status[/bold] to verify everything\n")


def _docker_env() -> dict:
    """Return environment dict for Docker subprocess calls, setting DOCKER_HOST for Colima if needed."""
    env = os.environ.copy()
    if "DOCKER_HOST" in env:
        return env
    colima_sock = Path.home() / ".colima" / "default" / "docker.sock"
    if colima_sock.exists():
        env["DOCKER_HOST"] = f"unix://{colima_sock}"
        env.setdefault("DOCKER_API_VERSION", "1.43")
    return env


def _setup_docker_embeddings(innie_home: Path):
    """Copy docker-compose + services/ build context and start embedding service."""
    import importlib.resources
    import shutil

    compose_dst = innie_home / "docker-compose.yml"

    # Copy docker-compose.yml
    try:
        compose_data = importlib.resources.files("innie").joinpath("docker-compose.yml").read_text()
        compose_dst.write_text(compose_data)
    except Exception:
        compose_src = Path(__file__).parent.parent / "docker-compose.yml"
        if compose_src.exists():
            shutil.copy2(compose_src, compose_dst)

    # Copy services/ build context (embeddings Dockerfile, server.py, requirements.txt)
    services_dst = innie_home / "services"
    try:
        pkg_services = importlib.resources.files("innie").joinpath("services")
        with importlib.resources.as_file(pkg_services) as services_src_path:
            shutil.copytree(str(services_src_path), str(services_dst), dirs_exist_ok=True)
    except Exception:
        # Fallback: copy from repo source tree (dev install)
        repo_services = Path(__file__).parent.parent.parent.parent / "services"
        if repo_services.exists():
            shutil.copytree(str(repo_services), str(services_dst), dirs_exist_ok=True)

    if not (services_dst / "embeddings").exists():
        console.print(
            "  [yellow]![/yellow] services/embeddings not found — "
            "copy failed. Create ~/.innie/services/embeddings/ manually."
        )
        return

    console.print("  [green]✓[/green] Copied docker-compose.yml and services/")

    # Ensure Docker daemon is running — try Colima first, then Docker Desktop
    docker_check = subprocess.run(
        ["docker", "info"], capture_output=True, text=True, env=_docker_env()
    )
    if docker_check.returncode != 0:
        started = False
        # Try Colima
        colima_check = subprocess.run(["which", "colima"], capture_output=True, text=True)
        if colima_check.returncode == 0:
            console.print("  Docker not running — starting Colima...")
            start = subprocess.run(["colima", "start"], capture_output=True, text=True)
            if start.returncode == 0:
                console.print("  [green]✓[/green] Colima started")
                started = True
            else:
                console.print(f"  [yellow]![/yellow] Colima failed to start: {start.stderr[:120]}")
        # Try Docker Desktop open (macOS)
        if not started:
            desktop_check = subprocess.run(
                ["open", "-a", "Docker"], capture_output=True, text=True
            )
            if desktop_check.returncode == 0:
                import time

                console.print("  Docker Desktop launching", end="")
                for _ in range(15):
                    time.sleep(2)
                    check = subprocess.run(["docker", "info"], capture_output=True, text=True)
                    if check.returncode == 0:
                        started = True
                        break
                    console.print(".", end="", flush=True)
                console.print()
                if started:
                    console.print("  [green]✓[/green] Docker Desktop ready")
        if not started:
            console.print("  [yellow]![/yellow] Docker unavailable. Start it manually, then run:")
            console.print("    innie docker up")
            return

    console.print("  Starting embedding service...")
    result = subprocess.run(
        ["docker", "compose", "up", "-d"],
        cwd=innie_home,
        capture_output=True,
        text=True,
        env=_docker_env(),
    )
    if result.returncode == 0:
        console.print("  [green]✓[/green] Embedding service started")
        console.print("  Manage it later with: [bold]innie docker up/down/status[/bold]")
    else:
        console.print(f"  [yellow]![/yellow] Docker compose failed: {result.stderr[:200]}")
        console.print("  You can start it later: [bold]innie docker up[/bold]")


def _setup_git(innie_home: Path):
    """Initialize git repo in ~/.innie with a .gitignore."""
    git_dir = innie_home / ".git"
    if git_dir.exists():
        console.print("  [dim]Git already initialized[/dim]")
        return

    # Create .gitignore
    gitignore = innie_home / ".gitignore"
    gitignore_content = """\
# Operational state (local only, rebuildable from data/)
agents/*/state/

# Docker volumes
docker-compose.yml

# OS files
.DS_Store
*.swp
"""
    gitignore.write_text(gitignore_content)

    result = subprocess.run(["git", "init"], cwd=innie_home, capture_output=True, text=True)
    if result.returncode == 0:
        # Initial commit
        subprocess.run(["git", "add", "."], cwd=innie_home, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "innie init: initial knowledge base"],
            cwd=innie_home,
            capture_output=True,
            text=True,
        )
        console.print("  [green]✓[/green] Initialized git repo with .gitignore")
        console.print("  [dim]Add a remote: cd ~/.innie && git remote add origin <url>[/dim]")
    else:
        console.print(f"  [yellow]![/yellow] git init failed: {result.stderr[:100]}")


def _create_agent(
    name: str,
    role: str,
    soul_content: str | None = None,
    context_content: str | None = None,
):
    """Scaffold a new agent with all template files and directories."""
    from jinja2 import Environment, FileSystemLoader

    templates_dir = Path(__file__).parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))

    agent = paths.agent_dir(name)
    agent.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    ctx = {"name": name, "role": role, "date": today}

    # Render templates (allow caller-provided content to override SOUL/CONTEXT)
    overrides = {
        "SOUL.md": soul_content,
        "CONTEXT.md": context_content,
    }
    for tmpl_name, dest in [
        ("profile.yaml.j2", "profile.yaml"),
        ("SOUL.md.j2", "SOUL.md"),
        ("CONTEXT.md.j2", "CONTEXT.md"),
        ("HEARTBEAT.md.j2", "HEARTBEAT.md"),
    ]:
        if dest in overrides and overrides[dest]:
            (agent / dest).write_text(overrides[dest])
        else:
            template = env.get_template(tmpl_name)
            (agent / dest).write_text(template.render(**ctx))

    # Create data/ directory structure
    for subdir in [
        "data/journal",
        "data/projects",
        "data/learnings/debugging",
        "data/learnings/patterns",
        "data/learnings/tools",
        "data/learnings/infrastructure",
        "data/people",
        "data/meetings",
        "data/inbox",
        "data/metrics",
        "data/decisions",
        "state/sessions",
        "state/trace",
        "state/.index",
        "skills",
    ]:
        (agent / subdir).mkdir(parents=True, exist_ok=True)

    # Create .gitkeep in empty dirs
    for subdir in agent.rglob("*"):
        if subdir.is_dir() and not any(subdir.iterdir()):
            (subdir / ".gitkeep").touch()

    console.print(f"  [green]✓[/green] Created agent: {name}")


def _install_scheduler():
    """Install heartbeat scheduler (launchd on macOS, cron elsewhere)."""
    if sys.platform == "darwin":
        _install_launchd()
    else:
        _install_cron()


def _install_launchd():
    """Install heartbeat as a launchd plist (macOS)."""
    import os

    innie_path = Path(sys.executable).parent / "innie"
    log_dir = Path.home() / ".innie" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "heartbeat.log"

    # Build PATH with common tool locations
    path_extras = [
        str(Path.home() / ".local" / "bin"),
        str(Path.home() / ".opencode" / "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    path_str = ":".join([p for p in path_extras if p not in os.environ.get("PATH", "")])
    full_path = f"{path_str}:{os.environ.get('PATH', '/usr/bin:/bin')}"

    plist_label = "com.innie-engine.heartbeat"
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{plist_label}.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{plist_label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{innie_path}</string>
        <string>heartbeat</string>
        <string>run</string>
    </array>
    <key>StartInterval</key>
    <integer>1800</integer>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{full_path}</string>
    </dict>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
"""
    plist_path.write_text(plist_content)

    # Unload existing (ignore errors) then load
    subprocess.run(
        ["launchctl", "unload", str(plist_path)],
        capture_output=True,
    )
    subprocess.run(
        ["launchctl", "load", str(plist_path)],
        check=True,
    )


def _install_cron():
    """Install heartbeat cron job (non-macOS)."""
    innie_path = Path(sys.executable).parent / "innie"

    cron_line = f"*/30 * * * * {innie_path} heartbeat run 2>&1 | logger -t innie-heartbeat"

    # Read current crontab
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = result.stdout if result.returncode == 0 else ""

    # Remove existing innie entries
    lines = [ln for ln in existing.strip().split("\n") if ln and "innie" not in ln]
    lines.append(cron_line)

    # Install
    new_crontab = "\n".join(lines) + "\n"
    subprocess.run(["crontab", "-"], input=new_crontab, text=True, check=True)


def handle(event: str):
    """Internal: called by bash shims to process hook events."""
    if event == "session-init":
        cwd = os.environ.get("PWD", os.getcwd())
        try:
            from innie.core.context import build_session_context

            output = build_session_context(cwd=cwd)
            sys.stdout.write(output)
        except Exception as e:
            # Never block the backend — output minimal context on error
            sys.stderr.write(f"[innie] session-init error: {e}\n")

        # Record trace session start
        try:
            from innie.core.trace import open_trace_db, start_session

            session_id = os.environ.get("CLAUDE_SESSION_ID")
            model = os.environ.get("CLAUDE_MODEL")
            conn = open_trace_db()
            start_session(
                conn,
                session_id=session_id,
                model=model,
                cwd=cwd,
                interactive=True,
            )
            conn.close()
        except Exception:
            pass  # Never block the backend

        # Background index refresh
        def _run_index():
            try:
                from innie.core.search import collect_files, index_files, open_db

                conn = open_db(agent=paths.active_agent())
                files = collect_files(paths.active_agent())
                index_files(conn, files, changed_only=True)
                conn.close()
            except Exception:
                pass

        threading.Thread(target=_run_index, daemon=True).start()

    elif event == "prompt-submit":
        # UserPromptSubmit hook — proactive memory injection before model responds.
        # Reads JSON from stdin, extracts prompt text, runs FTS search,
        # injects high-score results as <memory-context> block.
        try:
            import json as _json
            import re as _re

            raw = sys.stdin.read()
            data = _json.loads(raw) if raw.strip() else {}
            prompt_text = data.get("prompt", "")
            session_id = data.get("session_id", "unknown")

            if not prompt_text.strip():
                sys.exit(0)

            from innie.core.config import get
            from innie.core import paths as _paths

            threshold = get("hook.prompt_submit_threshold", 0.08)
            limit = int(get("hook.prompt_submit_limit", 3))

            # Build a safe FTS5 query from the prompt — strip operators and special chars
            safe_query = _re.sub(r"[^\w\s]", " ", prompt_text[:300])
            safe_query = _re.sub(r"\b(AND|OR|NOT)\b", " ", safe_query, flags=_re.IGNORECASE)
            safe_query = " ".join(safe_query.split()[:20])
            if not safe_query.strip():
                sys.exit(0)

            db_path = _paths.index_db()
            if not db_path.exists():
                sys.exit(0)

            from innie.core.search import open_db, search_keyword, format_results

            conn = open_db(db_path)
            results = search_keyword(conn, safe_query, limit=limit * 4)
            conn.close()

            if not results:
                sys.exit(0)

            # Dedup against already-injected files this session
            cache_file = _paths.hook_cache_file(session_id)
            injected: set[str] = set()
            if cache_file.exists():
                try:
                    injected = set(cache_file.read_text().splitlines())
                except OSError:
                    pass

            fresh = [r for r in results if r["score"] >= threshold and r["file_path"] not in injected]
            fresh = fresh[:limit]

            if not fresh:
                sys.exit(0)

            # Output injection block
            output = format_results(fresh)
            sys.stdout.write(
                f'<system-reminder>\n'
                f'Memory retrieved for current prompt:\n\n'
                f'{output}'
                f'</system-reminder>\n'
            )

            # Update session dedup cache
            new_paths = "\n".join(r["file_path"] for r in fresh)
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                if cache_file.exists():
                    existing = cache_file.read_text()
                    cache_file.write_text(existing + "\n" + new_paths)
                else:
                    cache_file.write_text(new_paths)
            except OSError:
                pass

        except Exception as e:
            sys.stderr.write(f"[innie] prompt-submit error: {e}\n")
            sys.exit(0)

    elif event == "pre-compact":
        try:
            from innie.core.context import build_precompact_warning

            sys.stdout.write(build_precompact_warning())
        except Exception as e:
            sys.stderr.write(f"[innie] pre-compact error: {e}\n")

    elif event == "session-end":
        # Append to today's session log
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            ts = datetime.now().strftime("%H:%M")
            session_dir = paths.sessions_dir()
            session_dir.mkdir(parents=True, exist_ok=True)

            log_file = session_dir / f"{today}.md"
            if not log_file.exists():
                log_file.write_text(f"# Sessions — {today}\n\n")

            session_id = os.environ.get("CLAUDE_SESSION_ID", "unknown")

            with open(log_file, "a") as f:
                f.write(f"\n## {ts} (session: {session_id})\n\n")
                f.write("- Work Done: (to be filled by heartbeat)\n")
                f.write("- Key Decisions: \n")
                f.write("- Notes: \n\n")
        except Exception as e:
            sys.stderr.write(f"[innie] session-end log error: {e}\n")
            session_id = os.environ.get("CLAUDE_SESSION_ID", "unknown")

        # Close trace session with metrics from env
        try:
            from innie.core.trace import end_session, open_trace_db

            cost = os.environ.get("CLAUDE_COST_USD")
            in_tok = os.environ.get("CLAUDE_INPUT_TOKENS")
            out_tok = os.environ.get("CLAUDE_OUTPUT_TOKENS")
            turns = os.environ.get("CLAUDE_NUM_TURNS")

            conn = open_trace_db()
            end_session(
                conn,
                session_id=session_id,
                cost_usd=float(cost) if cost else None,
                input_tokens=int(in_tok) if in_tok else None,
                output_tokens=int(out_tok) if out_tok else None,
                num_turns=int(turns) if turns else None,
            )
            conn.close()
        except Exception:
            pass  # Never block the backend

        # Update CONTEXT.md timestamp
        try:
            ctx_file = paths.context_file()
            if ctx_file.exists():
                import re

                content = ctx_file.read_text()
                content = re.sub(
                    r"\*Last updated:.*?\*",
                    f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
                    content,
                )
                ctx_file.write_text(content)
        except Exception:
            pass  # Never block the backend

    elif event == "tool-use":
        # Record a tool span from PostToolUse hook (called from observability.sh)
        try:
            import json as _json

            tool_input = os.environ.get("TOOL_INPUT", "{}")
            data = _json.loads(tool_input) if tool_input else {}
            tool_name = os.environ.get("TOOL_NAME", data.get("tool_name", "unknown"))
            session_id = os.environ.get("CLAUDE_SESSION_ID", "unknown")

            from innie.core.trace import open_trace_db, record_span

            conn = open_trace_db()
            record_span(
                conn,
                session_id=session_id,
                tool_name=tool_name,
                input_json=tool_input[:2000] if tool_input else None,
                output_summary=os.environ.get("TOOL_OUTPUT", "")[:500] or None,
                status="ok",
            )
            conn.close()
        except Exception:
            pass  # Never block the backend

    else:
        console.print(f"[yellow]Unknown event: {event}[/yellow]", err=True)
        raise typer.Exit(1)
