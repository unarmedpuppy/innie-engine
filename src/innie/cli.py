"""Typer CLI entry point for innie-engine."""

import typer

app = typer.Typer(
    name="innie",
    help="Persistent memory and identity for AI coding assistants.",
    no_args_is_help=True,
)


def _register_commands():
    from innie.commands import (
        agent,
        alias,
        backend,
        docker_services,
        doctor,
        fleet,
        heartbeat,
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

    # Skill subcommands
    skill_app = typer.Typer(help="Knowledge base skills (slash commands).")
    skill_app.command("list")(skills.list_skills)
    skill_app.command("run")(skills.run_skill)
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
