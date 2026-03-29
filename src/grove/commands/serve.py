"""grove serve — start the FastAPI server."""

import os

import typer


def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address"),
    port: int = typer.Option(8013, help="Port number"),
    reload: bool = typer.Option(False, help="Auto-reload on code changes"),
):
    """Start the grove API server (jobs, chat completions, memory)."""
    try:
        import uvicorn
    except ImportError:
        typer.echo("Missing serve dependencies. Install with: pip install grove[serve]")
        raise typer.Exit(1)

    os.environ["INNIE_SERVE_PORT"] = str(port)

    typer.echo(f"Starting grove server on {host}:{port}")
    uvicorn.run(
        "grove.serve.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
