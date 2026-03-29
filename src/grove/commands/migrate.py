"""innie migrate — import data from other AI memory systems.

Supports:
  - agent-harness: ~/.agent-harness/
  - openclaw: ~/.openclaw/
  - Generic directory: any directory with .md files, session logs, etc.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console

from grove.core import paths

console = Console()


# ── Source detection ─────────────────────────────────────────────────────────


def _detect_sources() -> list[dict]:
    """Auto-detect migratable sources on this machine."""
    sources = []

    # agent-harness
    harness_home = Path.home() / ".agent-harness"
    harness_repo = Path.home() / "workspace" / "agent-harness"
    if harness_home.exists() or harness_repo.exists():
        profiles = []
        if harness_repo.exists():
            profiles_dir = harness_repo / "profiles"
            if profiles_dir.exists():
                profiles = [p.name for p in profiles_dir.iterdir() if p.is_dir()]
        sources.append(
            {
                "type": "agent-harness",
                "home": str(harness_home),
                "repo": str(harness_repo),
                "profiles": profiles,
                "label": f"agent-harness ({len(profiles)} profiles)",
            }
        )

    # openclaw
    openclaw_home = Path.home() / ".openclaw"
    if openclaw_home.exists():
        sources.append(
            {
                "type": "openclaw",
                "home": str(openclaw_home),
                "label": "openclaw",
            }
        )

    return sources


# ── agent-harness migration ────────────────────────────────────────────────


def _migrate_agent_harness(
    source: dict,
    agents: list[str] | None = None,
    dry_run: bool = False,
):
    """Migrate from agent-harness to innie-engine."""
    harness_home = Path(source["home"])
    harness_repo = Path(source["repo"])
    profiles_dir = harness_repo / "profiles" if harness_repo.exists() else None

    available = source.get("profiles", [])
    to_migrate = agents or available

    for agent_name in to_migrate:
        console.print(f"\n  [bold]Migrating agent: {agent_name}[/bold]")

        profile_src = profiles_dir / agent_name if profiles_dir else None
        memory_src = harness_home / "memory" / agent_name

        if not (profile_src and profile_src.exists()) and not memory_src.exists():
            console.print("    [yellow]Skipped — no data found[/yellow]")
            continue

        agent_dst = paths.agent_dir(agent_name)

        if dry_run:
            console.print(f"    Would create: {agent_dst}")
            if profile_src and profile_src.exists():
                _preview_copy(profile_src, agent_dst, "identity files")
            if memory_src.exists():
                _preview_copy(memory_src, agent_dst, "memory data")
            continue

        # Ensure agent scaffold exists
        _ensure_agent_scaffold(agent_name)

        # 1. Copy identity files from profiles/
        if profile_src and profile_src.exists():
            identity_files = {
                "SOUL.md": "SOUL.md",
                "IDENTITY.md": "SOUL.md",  # Merge IDENTITY into SOUL
                "CLAUDE.md": "CLAUDE.md",
                "USER.md": None,  # Goes to ~/.innie/user.md if not exists
                "TOOLS.md": "TOOLS.md",
                "HEARTBEAT.md": "HEARTBEAT.md",
                "MEMORY.md": None,  # Route to data/learnings/
            }

            for src_name, dst_name in identity_files.items():
                src_file = profile_src / src_name
                if not src_file.exists():
                    continue

                if dst_name is None:
                    if src_name == "USER.md":
                        user_dst = paths.user_file()
                        if not user_dst.exists():
                            shutil.copy2(src_file, user_dst)
                            console.print(f"    [green]✓[/green] {src_name} → user.md")
                    elif src_name == "MEMORY.md":
                        # Import as a learning
                        _import_memory_md(src_file, agent_name)
                elif dst_name == "SOUL.md" and src_name == "IDENTITY.md":
                    # Append IDENTITY.md to SOUL.md if both exist
                    soul_dst = agent_dst / "SOUL.md"
                    if soul_dst.exists():
                        existing = soul_dst.read_text()
                        identity = src_file.read_text()
                        soul_dst.write_text(f"{existing}\n\n---\n\n# Identity\n\n{identity}")
                        console.print(f"    [green]✓[/green] {src_name} → appended to SOUL.md")
                    else:
                        shutil.copy2(src_file, soul_dst)
                        console.print(f"    [green]✓[/green] {src_name} → SOUL.md")
                else:
                    shutil.copy2(src_file, agent_dst / dst_name)
                    console.print(f"    [green]✓[/green] {src_name} → {dst_name}")

            # Copy profile.yaml
            profile_yaml = profile_src / "profile.yaml"
            if profile_yaml.exists():
                shutil.copy2(profile_yaml, agent_dst / "profile.yaml")
                console.print("    [green]✓[/green] profile.yaml")

            # Copy dcg-config.toml if present (destructive command guard)
            dcg_config = profile_src / "dcg-config.toml"
            if dcg_config.exists():
                shutil.copy2(dcg_config, agent_dst / "dcg-config.toml")
                console.print("    [green]✓[/green] dcg-config.toml (destructive command guard)")

        # 2. Copy memory data
        if memory_src.exists():
            # CONTEXT.md
            ctx_src = memory_src / "CONTEXT.md"
            if ctx_src.exists():
                shutil.copy2(ctx_src, agent_dst / "CONTEXT.md")
                console.print("    [green]✓[/green] CONTEXT.md")

            # Session logs → state/sessions/
            sessions_src = memory_src / "sessions"
            if sessions_src.exists():
                sessions_dst = paths.sessions_dir(agent_name)
                sessions_dst.mkdir(parents=True, exist_ok=True)
                count = 0
                for f in sessions_src.glob("*.md"):
                    shutil.copy2(f, sessions_dst / f.name)
                    count += 1
                if count:
                    console.print(f"    [green]✓[/green] {count} session logs")

            # heartbeat-state.json → state/
            hb_src = memory_src / "heartbeat-state.json"
            if hb_src.exists():
                shutil.copy2(hb_src, paths.heartbeat_state(agent_name))
                console.print("    [green]✓[/green] heartbeat-state.json")

            # .index/memory.db → state/.index/ (compatible format)
            idx_src = memory_src / ".index" / "memory.db"
            if idx_src.exists():
                idx_dst = paths.index_db(agent_name)
                idx_dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(idx_src, idx_dst)
                console.print("    [green]✓[/green] semantic index (memory.db)")

            # Any other .md files → data/inbox/
            _import_loose_files(memory_src, agent_name)

        console.print(f"    [green]Agent '{agent_name}' migrated[/green]")


# ── openclaw migration ──────────────────────────────────────────────────────


def _migrate_openclaw(source: dict, agent_name: str = "innie", dry_run: bool = False):
    """Migrate from openclaw to innie-engine."""
    openclaw_home = Path(source["home"])
    workspace = openclaw_home / "workspace"

    if dry_run:
        console.print(f"\n  [bold]Would migrate openclaw → agent '{agent_name}'[/bold]")
        if workspace.exists():
            _preview_copy(workspace, paths.agent_dir(agent_name), "workspace")
        return

    console.print(f"\n  [bold]Migrating openclaw → agent '{agent_name}'[/bold]")

    _ensure_agent_scaffold(agent_name)
    agent_dst = paths.agent_dir(agent_name)

    # 1. Identity files from workspace/
    if workspace.exists():
        for src_name in [
            "SOUL.md",
            "IDENTITY.md",
            "CLAUDE.md",
            "TOOLS.md",
            "HEARTBEAT.md",
            "AGENTS.md",
            "BOOT.md",
        ]:
            src_file = workspace / src_name
            if src_file.exists():
                shutil.copy2(src_file, agent_dst / src_name)
                console.print(f"    [green]✓[/green] {src_name}")

        # MEMORY.md → import as learning
        memory_md = workspace / "MEMORY.md"
        if memory_md.exists():
            _import_memory_md(memory_md, agent_name)

        # workspace/memory/ → sessions and state
        mem_dir = workspace / "memory"
        if mem_dir.exists():
            sessions_dst = paths.sessions_dir(agent_name)
            sessions_dst.mkdir(parents=True, exist_ok=True)
            count = 0
            for f in mem_dir.glob("*.md"):
                shutil.copy2(f, sessions_dst / f.name)
                count += 1
            if count:
                console.print(f"    [green]✓[/green] {count} memory/session files")

            hb = mem_dir / "heartbeat-state.json"
            if hb.exists():
                shutil.copy2(hb, paths.heartbeat_state(agent_name))
                console.print("    [green]✓[/green] heartbeat-state.json")

    # 2. Skills
    skills_src = openclaw_home / "skills"
    if skills_src.exists():
        skills_dst = paths.skills_dir(agent_name)
        skills_dst.mkdir(parents=True, exist_ok=True)
        count = 0
        for skill_dir in skills_src.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                dst = skills_dst / skill_dir.name
                if not dst.exists():
                    shutil.copytree(skill_dir, dst)
                    count += 1
        if count:
            console.print(f"    [green]✓[/green] {count} skills")

    # 3. Config extraction (best-effort from openclaw.json)
    config_file = openclaw_home / "openclaw.json"
    if config_file.exists():
        try:
            oc_config = json.loads(config_file.read_text())
            _extract_openclaw_config(oc_config)
        except Exception as e:
            console.print(f"    [yellow]![/yellow] Could not parse openclaw.json: {e}")

    console.print(f"    [green]Agent '{agent_name}' migrated from openclaw[/green]")


def _extract_openclaw_config(oc_config: dict):
    """Extract useful config from openclaw.json into notes."""
    # Just log what was found — user can manually configure
    channels = oc_config.get("channels", {})
    models = oc_config.get("models", {})

    notes = []
    if "mattermost" in channels:
        mm = channels["mattermost"]
        notes.append(f"Mattermost: {mm.get('baseUrl', 'unknown')}")
    if "bluebubbles" in channels:
        notes.append("BlueBubbles: configured")
    if models:
        providers = models.get("providers", {})
        for name in providers:
            notes.append(f"Model provider: {name}")

    if notes:
        console.print(f"    [dim]Found config: {', '.join(notes)}[/dim]")
        console.print("    [dim]Transfer these settings manually to config.toml[/dim]")


# ── Generic directory migration ─────────────────────────────────────────────


def _migrate_directory(
    source_dir: Path,
    agent_name: str,
    dry_run: bool = False,
):
    """Migrate from any directory containing .md files."""
    if not source_dir.exists():
        console.print(f"  [red]Directory not found: {source_dir}[/red]")
        return

    md_files = list(source_dir.rglob("*.md"))
    json_files = list(source_dir.rglob("*.json"))
    yaml_files = list(source_dir.rglob("*.yaml")) + list(source_dir.rglob("*.yml"))

    console.print(f"\n  [bold]Migrating directory → agent '{agent_name}'[/bold]")
    console.print(
        f"    Found: {len(md_files)} .md, {len(json_files)} .json, {len(yaml_files)} .yaml files"
    )

    if dry_run:
        console.print(f"    Would import to: {paths.agent_dir(agent_name)}")
        return

    _ensure_agent_scaffold(agent_name)

    # Categorize files by name patterns
    imported = 0
    for f in md_files:
        name_lower = f.name.lower()
        rel = f.relative_to(source_dir)

        if name_lower in ("soul.md", "identity.md"):
            dst = paths.agent_dir(agent_name) / "SOUL.md"
            if not dst.exists():
                shutil.copy2(f, dst)
            else:
                # Append
                existing = dst.read_text()
                dst.write_text(f"{existing}\n\n---\n\n{f.read_text()}")
            imported += 1
        elif name_lower == "context.md":
            shutil.copy2(f, paths.agent_dir(agent_name) / "CONTEXT.md")
            imported += 1
        elif name_lower == "heartbeat.md":
            shutil.copy2(f, paths.agent_dir(agent_name) / "HEARTBEAT.md")
            imported += 1
        elif name_lower in ("user.md",):
            user_dst = paths.user_file()
            if not user_dst.exists():
                shutil.copy2(f, user_dst)
            imported += 1
        elif _is_session_file(f.name):
            # Looks like a session log (YYYY-MM-DD.md)
            sessions_dst = paths.sessions_dir(agent_name)
            sessions_dst.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, sessions_dst / f.name)
            imported += 1
        elif _is_journal_entry(f):
            # Route to journal
            journal_dst = paths.journal_dir(agent_name)
            # Preserve relative path structure
            dest = journal_dst / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            imported += 1
        else:
            # Default: import to inbox
            inbox_dst = paths.inbox_dir(agent_name)
            inbox_dst.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, inbox_dst / f.name)
            imported += 1

    console.print(f"    [green]✓[/green] Imported {imported} files")


# ── Helpers ─────────────────────────────────────────────────────────────────


def _ensure_agent_scaffold(agent_name: str):
    """Create agent directory structure if it doesn't exist."""
    agent_dir = paths.agent_dir(agent_name)
    if agent_dir.exists():
        return

    from grove.commands.init import _create_agent

    _create_agent(agent_name, "Migrated Agent")


def _preview_copy(src: Path, dst: Path, label: str):
    """Preview what would be copied."""
    if src.is_dir():
        files = list(src.rglob("*"))
        file_count = sum(1 for f in files if f.is_file())
        console.print(f"    Would copy {label}: {file_count} files from {src}")
    else:
        console.print(f"    Would copy {label}: {src}")


def _import_memory_md(memory_md: Path, agent_name: str):
    """Import a MEMORY.md file as a learning entry."""
    content = memory_md.read_text()
    if not content.strip():
        return

    today = datetime.now().strftime("%Y-%m-%d")
    learnings_dir = paths.learnings_dir(agent_name) / "patterns"
    learnings_dir.mkdir(parents=True, exist_ok=True)

    dst = learnings_dir / f"{today}-migrated-memory.md"
    header = f"# Migrated Memory\n\n*Imported: {today}*\n*Source: {memory_md}*\n\n"
    dst.write_text(header + content)
    console.print("    [green]✓[/green] MEMORY.md → learnings/patterns/")


def _import_loose_files(src_dir: Path, agent_name: str):
    """Import loose .md files (not already handled) to inbox."""
    handled = {"CONTEXT.md", "HEARTBEAT.md", "MEMORY.md"}
    inbox_dst = paths.inbox_dir(agent_name)
    inbox_dst.mkdir(parents=True, exist_ok=True)

    count = 0
    for f in src_dir.glob("*.md"):
        if f.name in handled:
            continue
        shutil.copy2(f, inbox_dst / f.name)
        count += 1

    if count:
        console.print(f"    [green]✓[/green] {count} loose files → inbox/")


def _is_session_file(name: str) -> bool:
    """Check if filename looks like YYYY-MM-DD.md."""
    import re

    return bool(re.match(r"^\d{4}-\d{2}-\d{2}\.md$", name))


def _is_journal_entry(filepath: Path) -> bool:
    """Check if file looks like a journal entry (in a date-structured dir)."""
    import re

    parts = filepath.parts
    for part in parts:
        if re.match(r"^\d{4}$", part):  # Year directory
            return True
    if "journal" in str(filepath).lower():
        return True
    return False


# ── CLI entry point ─────────────────────────────────────────────────────────


def migrate(
    source: str = typer.Argument(
        None,
        help="Source to migrate from: 'agent-harness', 'openclaw', or a directory path",
    ),
    agent: str = typer.Option(None, help="Target agent name (or migrate all)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without making changes"),
    all_agents: bool = typer.Option(False, "--all", help="Migrate all detected agents"),
):
    """Import data from other AI memory systems into innie."""
    console.print("\n  [bold]innie migrate[/bold]\n")

    # Ensure innie is initialized
    if not paths.home().exists():
        console.print("  [red]Run 'innie init' first to create ~/.innie/[/red]")
        raise typer.Exit(1)

    # Auto-detect if no source specified
    if source is None:
        detected = _detect_sources()
        if not detected:
            console.print("  No migratable sources detected.")
            console.print("  Specify a source: innie migrate agent-harness")
            console.print("  Or a directory:   innie migrate /path/to/data")
            raise typer.Exit(0)

        console.print("  Detected sources:")
        for i, s in enumerate(detected, 1):
            console.print(f"    [{i}] {s['label']}")

        if len(detected) == 1:
            choice = "1"
        else:
            console.print("    [a] All of the above")
            choice = typer.prompt("  Migrate", default="a")

        if choice.lower() == "a":
            for s in detected:
                _dispatch_migrate(s, agent, all_agents, dry_run)
        else:
            idx = int(choice) - 1
            if 0 <= idx < len(detected):
                _dispatch_migrate(detected[idx], agent, all_agents, dry_run)
        return

    # Named source
    if source == "agent-harness":
        detected = [s for s in _detect_sources() if s["type"] == "agent-harness"]
        if not detected:
            console.print("  [red]agent-harness not found[/red]")
            raise typer.Exit(1)
        _dispatch_migrate(detected[0], agent, all_agents, dry_run)

    elif source == "openclaw":
        detected = [s for s in _detect_sources() if s["type"] == "openclaw"]
        if not detected:
            console.print("  [red]openclaw not found[/red]")
            raise typer.Exit(1)
        _dispatch_migrate(detected[0], agent, all_agents, dry_run)

    else:
        # Treat as directory path
        source_path = Path(source).expanduser().resolve()
        target_agent = agent or source_path.name
        _migrate_directory(source_path, target_agent, dry_run)

    mode = " (dry run)" if dry_run else ""
    console.print(f"\n  [bold green]Migration complete!{mode}[/bold green]")
    console.print("  Run: [bold]innie doctor[/bold] to verify")
    console.print("  Run: [bold]innie index[/bold] to rebuild search index\n")


def _dispatch_migrate(
    source: dict,
    agent: str | None,
    all_agents: bool,
    dry_run: bool,
):
    """Route migration to the right handler."""
    if source["type"] == "agent-harness":
        agents_list = None
        if all_agents:
            agents_list = source.get("profiles", [])
        elif agent:
            agents_list = [agent]
        else:
            agents_list = source.get("profiles", [])
        _migrate_agent_harness(source, agents_list, dry_run)

    elif source["type"] == "openclaw":
        target = agent or "innie"
        _migrate_openclaw(source, target, dry_run)
