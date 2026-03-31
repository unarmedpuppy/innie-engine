"""grove serve — start the FastAPI server."""

import logging
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

    os.environ["GROVE_SERVE_PORT"] = str(port)

    # Configure root logger so grove.* module logs are visible in the serve log
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    typer.echo(f"Starting grove server on {host}:{port}")
    uvicorn.run(
        "grove.serve.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
