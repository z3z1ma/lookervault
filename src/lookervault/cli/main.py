"""Main Typer application for LookerVault CLI."""

from pathlib import Path
from typing import Annotated

import typer

from lookervault import __version__

app = typer.Typer(
    help="LookerVault - Backup and restore tool for Looker instances",
    add_completion=False,
)


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        typer.echo(f"LookerVault version {__version__}")
        raise typer.Exit(0)


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=version_callback,
            is_eager=True,
            help="Show version and exit",
        ),
    ] = False,
) -> None:
    """LookerVault CLI main callback."""
    pass


@app.command()
def check(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to configuration file"),
    ] = None,
    output: Annotated[
        str,
        typer.Option("--output", "-o", help='Output format: "table" or "json"'),
    ] = "table",
) -> None:
    """Perform readiness checks to validate installation and configuration."""
    from .commands import check as check_module

    check_module.run(config, output)


@app.command()
def info(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to configuration file"),
    ] = None,
    output: Annotated[
        str,
        typer.Option("--output", "-o", help='Output format: "table" or "json"'),
    ] = "table",
) -> None:
    """Display Looker instance information."""
    from .commands import info as info_module

    info_module.run(config, output)


@app.command()
def extract(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to configuration file"),
    ] = None,
    output: Annotated[
        str,
        typer.Option("--output", "-o", help='Output format: "table" or "json"'),
    ] = "table",
    db: Annotated[
        str,
        typer.Option("--db", help="Database path for storage"),
    ] = "looker.db",
    types: Annotated[
        str | None,
        typer.Option(
            "--types", "-t", help="Comma-separated content types (e.g., 'dashboards,looks')"
        ),
    ] = None,
    batch_size: Annotated[
        int,
        typer.Option("--batch-size", "-b", help="Items per batch for memory management"),
    ] = 100,
    resume: Annotated[
        bool,
        typer.Option("--resume", help="Resume incomplete extraction"),
    ] = True,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable verbose logging"),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable debug logging"),
    ] = False,
) -> None:
    """Extract all content from Looker instance to local database."""
    from .commands import extract as extract_module

    extract_module.run(config, output, db, types, batch_size, resume, verbose, debug)


if __name__ == "__main__":
    app()
