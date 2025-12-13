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


if __name__ == "__main__":
    app()
