"""Check command implementation for readiness checks."""

from pathlib import Path
from typing import Optional

import typer

from ...config.validator import perform_readiness_check
from ...exceptions import ConfigError
from ..output import format_readiness_check_json, format_readiness_check_table


def run(config: Optional[Path], output: str) -> None:
    """
    Run readiness checks and display results.

    Args:
        config: Optional path to config file
        output: Output format ("table" or "json")
    """
    try:
        # Perform all readiness checks
        result = perform_readiness_check(config)

        # Format output
        if output == "json":
            typer.echo(format_readiness_check_json(result))
        else:
            format_readiness_check_table(result)

        # Exit with appropriate code
        if result.ready:
            raise typer.Exit(0)
        else:
            # Check if any check failed completely
            if any(check.status == "fail" for check in result.checks):
                # Configuration error if config-related checks failed
                config_checks = ["Configuration File Found", "Configuration Valid"]
                if any(
                    check.name in config_checks and check.status == "fail"
                    for check in result.checks
                ):
                    raise typer.Exit(2)
            # General not ready
            raise typer.Exit(1)

    except ConfigError as e:
        typer.echo(f"Configuration error: {e}", err=True)
        raise typer.Exit(2)
    except KeyboardInterrupt:
        typer.echo("\nInterrupted by user", err=True)
        raise typer.Exit(130)
    except Exception as e:
        typer.echo(f"Unexpected error: {e}", err=True)
        raise typer.Exit(1)
