"""Typer CLI entry point for innie-engine."""

import subprocess
import sys

import typer

app = typer.Typer(
    name="innie",
    help="Persistent memory and identity for AI coding assistants.",
    no_args_is_help=False,
    invoke_without_command=True,
)


def _launch() -> None:
    """Detect active backend, inject context, and launch it."""
    from innie.backends.registry import discover_backends
    from innie.commands.alias import build_context
    from innie.core import paths

    agent = paths.active_agent()
    backends = discover_backends()

    for _name, cls in backends.items():
        instance = cls()
        if instance.detect():
            try:
                context = build_context(agent)
                instance.inject_context(agent, context)
            except Exception:
                pass
            cmd = instance.launch_cmd(agent)
            result = subprocess.run(cmd)
            sys.exit(result.returncode)

    typer.echo("No AI backend detected. Install Claude Code, Cursor, or OpenCode.")
    raise typer.Exit(1)


@app.callback()
def _main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _launch()


def _register_commands():
    from innie.commands import (
        agent,
        alias,
        backend,
        docker_services,
        doctor,
        edit,
        env,
        fleet,
        git_cmd,
        heartbeat,
        inbox,
        init,
        migrate,
        search,
        secrets,
        serve,
        skills,
        trace,
        update,
    )

    app.command("init")(init.init)
    app.command("create")(agent.create)
    app.command("list")(agent.list_agents)
    app.command("delete")(agent.delete)
    app.command("switch")(agent.switch)
    app.command("search")(search.search)
    app.command("index")(search.index)
    app.command("context")(search.context)
    app.command("log")(search.log)
    app.command("handle")(init.handle)
    app.command("status")(doctor.status)
    app.command("doctor")(doctor.doctor)
    app.command("serve")(serve.serve)
    app.command("decay")(doctor.decay)
    app.command("migrate")(migrate.migrate)
    app.command("update")(update.update)
    app.command("secrets")(secrets.scan)

    # Inbox subcommands
    inbox_app = typer.Typer(help="Async A2A inbox — read and send messages between agents.")
    inbox_app.command("list")(inbox.list_inbox)
    inbox_app.command("read")(inbox.read_message)
    inbox_app.command("send")(inbox.send)
    inbox_app.command("archive")(inbox.archive)
    app.add_typer(inbox_app, name="inbox")

    # Docker subcommands
    docker_app = typer.Typer(help="Manage the full Docker services stack (embeddings, heartbeat, serve).")
    docker_app.command("up")(docker_services.up)
    docker_app.command("down")(docker_services.down)
    docker_app.command("restart")(docker_services.restart)
    docker_app.command("status")(docker_services.docker_status)
    docker_app.command("logs")(docker_services.logs)
    app.add_typer(docker_app, name="docker")

    # Alias subcommands
    alias_app = typer.Typer(help="Manage shell aliases.")
    alias_app.command("add")(alias.add)
    alias_app.command("show")(alias.show)
    alias_app.command("remove")(alias.remove)
    app.add_typer(alias_app, name="alias")

    # Backend subcommands
    backend_app = typer.Typer(help="Manage AI backend integrations.")
    backend_app.command("install")(backend.install)
    backend_app.command("uninstall")(backend.uninstall)
    backend_app.command("list")(backend.list_backends)
    backend_app.command("check")(backend.check)
    app.add_typer(backend_app, name="backend")

    # Heartbeat subcommands
    hb_app = typer.Typer(help="Automated memory extraction pipeline.")
    hb_app.command("run")(heartbeat.run)
    hb_app.command("enable")(heartbeat.enable)
    hb_app.command("disable")(heartbeat.disable)
    hb_app.command("status")(heartbeat.hb_status)
    hb_app.command("reset-state")(heartbeat.reset_state)
    app.add_typer(hb_app, name="heartbeat")

    # Fleet subcommands
    fleet_app = typer.Typer(help="Fleet gateway for multi-machine agent coordination.")
    fleet_app.command("start")(fleet.start)
    fleet_app.command("agents")(fleet.agents)
    fleet_app.command("stats")(fleet.stats)
    app.add_typer(fleet_app, name="fleet")

    # Git subcommands
    git_app = typer.Typer(help="Manage git backup settings (auto-commit, auto-push).")
    git_app.command("auto-push")(git_cmd.auto_push)
    git_app.command("auto-commit")(git_cmd.auto_commit)
    git_app.command("status")(git_cmd.status)
    app.add_typer(git_app, name="git")

    # Env subcommands
    env_app = typer.Typer(help="Manage per-agent secrets in a gitignored .env file.")
    env_app.command("set")(env.env_set)
    env_app.command("get")(env.env_get)
    env_app.command("list")(env.env_list)
    env_app.command("unset")(env.env_unset)
    app.add_typer(env_app, name="env")

    # Edit subcommands
    edit_app = typer.Typer(help="Edit agent identity files (SOUL.md, CONTEXT.md, user.md).")
    edit_app.command("soul")(edit.soul)
    edit_app.command("context")(edit.context)
    edit_app.command("user")(edit.user)
    app.add_typer(edit_app, name="edit")

    # Skill subcommands
    skill_app = typer.Typer(help="Knowledge base skills (slash commands).")
    skill_app.command("list")(skills.list_skills)
    skill_app.command("run")(skills.run_skill)
    skill_app.command("install")(skills.install_skill)
    skill_app.command("show")(skills.show_skill)
    skill_app.command("remove")(skills.remove_skill)
    app.add_typer(skill_app, name="skill")

    # Trace subcommands
    trace_app = typer.Typer(help="Session traces and observability.")
    trace_app.command("list")(trace.list_traces)
    trace_app.command("show")(trace.show)
    trace_app.command("stats")(trace.stats)
    app.add_typer(trace_app, name="trace")


_register_commands()

if __name__ == "__main__":
    app()
