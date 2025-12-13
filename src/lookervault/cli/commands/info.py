"""Info command implementation for Looker instance information."""

from pathlib import Path

import typer

from lookervault.cli.output import format_instance_info_json, format_instance_info_table
from lookervault.cli.rich_logging import console, print_error
from lookervault.config.loader import load_config
from lookervault.exceptions import ConfigError
from lookervault.looker.connection import connect_and_get_info


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
            print_error(f"Configuration error: {e}")
            console.print("\n[bold]Troubleshooting:[/bold]")
            console.print("  - Check that config file exists and is valid TOML")
            console.print("  - Ensure api_url is a valid HTTPS URL")
            raise typer.Exit(2) from None

        # Connect to Looker and get instance info
        status = connect_and_get_info(cfg)

        # Format and display output
        if output == "json":
            # Use print() for JSON to ensure it goes to stdout
            print(format_instance_info_json(status))
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
        print_error("Interrupted by user")
        raise typer.Exit(130) from None
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        console.print("\n[bold]Troubleshooting:[/bold]")
        console.print("  - Check network connectivity to Looker instance")
        console.print("  - Verify credentials are correct and not expired")
        console.print("  - Ensure api_url does not include /api/* path")
        raise typer.Exit(3) from None
