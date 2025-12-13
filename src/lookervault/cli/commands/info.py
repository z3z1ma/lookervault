"""Info command implementation for Looker instance information."""

from pathlib import Path

import typer

from ...config.loader import load_config
from ...exceptions import ConfigError
from ...looker.connection import connect_and_get_info
from ..output import format_instance_info_json, format_instance_info_table


def run(config: Path | None, output: str) -> None:
    """
    Connect to Looker instance and display information.

    Args:
        config: Optional path to config file
        output: Output format ("table" or "json")
    """
    try:
        # Load configuration
        try:
            cfg = load_config(config)
        except ConfigError as e:
            typer.echo(f"Configuration error: {e}", err=True)
            typer.echo("\nTroubleshooting:", err=True)
            typer.echo("  - Check that config file exists and is valid TOML", err=True)
            typer.echo("  - Ensure api_url is a valid HTTPS URL", err=True)
            raise typer.Exit(2)

        # Connect to Looker and get instance info
        status = connect_and_get_info(cfg)

        # Format and display output
        if output == "json":
            typer.echo(format_instance_info_json(status))
        else:
            format_instance_info_table(status)

        # Exit with appropriate code
        if status.connected and status.authenticated:
            raise typer.Exit(0)
        else:
            # Connection or authentication failed
            raise typer.Exit(3)

    except typer.Exit:
        # Re-raise typer exits
        raise
    except KeyboardInterrupt:
        typer.echo("\nInterrupted by user", err=True)
        raise typer.Exit(130)
    except Exception as e:
        typer.echo(f"Unexpected error: {e}", err=True)
        typer.echo("\nTroubleshooting:", err=True)
        typer.echo("  - Check network connectivity to Looker instance", err=True)
        typer.echo("  - Verify credentials are correct and not expired", err=True)
        typer.echo("  - Ensure api_url does not include /api/* path", err=True)
        raise typer.Exit(3)
