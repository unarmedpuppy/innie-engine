"""innie serve — start the FastAPI server."""

import os

import typer


def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address"),
    port: int = typer.Option(8013, help="Port number"),
    reload: bool = typer.Option(False, help="Auto-reload on code changes"),
):
    """Start the innie API server (jobs, chat completions, memory)."""
    try:
        import uvicorn
    except ImportError:
        typer.echo("Missing serve dependencies. Install with: pip install innie-engine[serve]")
        raise typer.Exit(1)

    # Expose port to the app so it can self-register with the fleet gateway
    os.environ["INNIE_SERVE_PORT"] = str(port)

    typer.echo(f"Starting innie server on {host}:{port}")
    uvicorn.run(
        "innie.serve.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
