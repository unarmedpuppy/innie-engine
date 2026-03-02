"""innie serve — start the FastAPI server."""

import typer


def serve(
    host: str = typer.Option("0.0.0.0", help="Bind address"),
    port: int = typer.Option(8013, help="Port number"),
    reload: bool = typer.Option(False, help="Auto-reload on code changes"),
):
    """Start the innie API server (jobs, chat completions, memory)."""
    try:
        import uvicorn
    except ImportError:
        typer.echo("Missing serve dependencies. Install with: pip install innie-engine[serve]")
        raise typer.Exit(1)

    typer.echo(f"Starting innie server on {host}:{port}")
    uvicorn.run(
        "innie.serve.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
