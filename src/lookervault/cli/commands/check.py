"""Check command implementation for readiness checks."""

from pathlib import Path

import typer

from lookervault.cli.output import format_readiness_check_json, format_readiness_check_table
from lookervault.cli.rich_logging import console, print_error
from lookervault.config.validator import perform_readiness_check
from lookervault.exceptions import ConfigError


def run(config: Path | None, output: str) -> None:
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
            # Use print() for JSON to ensure it goes to stdout
            print(format_readiness_check_json(result))
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

    except typer.Exit:
        # Re-raise typer exits
        raise
    except ConfigError as e:
        print_error(f"Configuration error: {e}")
        raise typer.Exit(2) from None
    except KeyboardInterrupt:
        print_error("Interrupted by user")
        raise typer.Exit(130) from None
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        raise typer.Exit(1) from None
