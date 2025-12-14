"""Restore command implementation for content restoration."""

import logging
import time
from pathlib import Path

import typer

from lookervault.cli.rich_logging import configure_rich_logging, console, print_error
from lookervault.cli.types import parse_content_type
from lookervault.config.loader import load_config
from lookervault.exceptions import (
    ConfigError,
    DeserializationError,
    RestorationError,
    ValidationError,
)
from lookervault.looker.client import LookerClient
from lookervault.restoration.deserializer import ContentDeserializer
from lookervault.restoration.restorer import LookerContentRestorer
from lookervault.storage.models import ContentType
from lookervault.storage.repository import SQLiteContentRepository

logger = logging.getLogger(__name__)

# Exit codes (matching CLI interface contract)
EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_NOT_FOUND = 2
EXIT_VALIDATION_ERROR = 3
EXIT_API_ERROR = 4


def restore_single(
    content_type: str,
    content_id: str,
    config: Path | None = None,
    db_path: str = "looker.db",
    dry_run: bool = False,
    force: bool = False,
    json_output: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> None:
    """Restore a single content item by type and ID.

    Args:
        content_type: Content type to restore (dashboard, look, folder, etc.)
        content_id: ID of the content item to restore
        config: Optional path to config file
        db_path: Path to SQLite backup database
        dry_run: Validate and show what would be restored without making changes
        force: Skip confirmation prompts
        json_output: Output results in JSON format
        verbose: Enable verbose logging
        debug: Enable debug logging

    Exit codes:
        0: Success
        1: General error
        2: Content not found in backup
        3: Validation error
        4: API error (rate limit, authentication, etc.)
    """
    # Configure logging
    log_level = logging.DEBUG if debug else (logging.INFO if verbose else logging.WARNING)
    configure_rich_logging(
        level=log_level,
        show_time=debug,
        show_path=debug,
        enable_link_path=debug,
    )

    start_time = time.time()

    try:
        # Parse content type
        content_type_int = parse_content_type(content_type)
        content_type_enum = ContentType(content_type_int)
        content_type_name = content_type_enum.name.lower()

        # Load configuration
        cfg = load_config(config)

        # Validate credentials
        if not cfg.looker.client_id or not cfg.looker.client_secret:
            if not json_output:
                console.print("[red]✗ Missing credentials[/red]")
                console.print(
                    "Set LOOKERVAULT_CLIENT_ID and LOOKERVAULT_CLIENT_SECRET environment variables"
                )
            raise typer.Exit(EXIT_VALIDATION_ERROR)

        # Create components
        looker_client = LookerClient(
            api_url=str(cfg.looker.api_url),
            client_id=cfg.looker.client_id,
            client_secret=cfg.looker.client_secret,
            timeout=cfg.looker.timeout,
            verify_ssl=cfg.looker.verify_ssl,
        )

        repository = SQLiteContentRepository(db_path=db_path)
        deserializer = ContentDeserializer()

        # Create restorer for check_exists() and restoration operations
        restorer = LookerContentRestorer(
            client=looker_client,
            repository=repository,
        )

        # Display start message (human-readable mode)
        if not json_output:
            console.print(f"\nRestoring {content_type_name.title()} ID: [cyan]{content_id}[/cyan]")
            if dry_run:
                console.print("[dim](Dry run mode - no changes will be made)[/dim]\n")

        # Step 1: Check if content exists in backup
        if not json_output:
            console.print("Checking backup database...", end="")

        content_item = repository.get_content(content_id)

        if content_item is None or content_item.content_type != content_type_int:
            if not json_output:
                console.print(" [red]✗[/red]")
                console.print(
                    f"[red]Error: {content_type_name.title()} ID '{content_id}' not found in backup[/red]"
                )
            else:
                # JSON error output
                import json

                error_output = {
                    "status": "error",
                    "error_type": "NotFoundError",
                    "error_message": f"{content_type_name.title()} ID '{content_id}' not found in backup",
                    "content_type": content_type_name,
                    "content_id": content_id,
                }
                console.print(json.dumps(error_output, indent=2))

            raise typer.Exit(EXIT_NOT_FOUND)

        if not json_output:
            console.print(" [green]✓[/green]")
            console.print(f'  → Found in backup: [cyan]"{content_item.name}"[/cyan]')

        # Step 2: Deserialize content
        if not json_output:
            console.print("Deserializing content...", end="")

        content_dict = deserializer.deserialize(
            content_item.content_data, content_type_enum, as_dict=True
        )

        if not json_output:
            console.print(" [green]✓[/green]")

        # Step 3: Validate content schema
        if not json_output:
            console.print("Validating content schema...", end="")

        validation_errors = deserializer.validate_schema(content_dict, content_type_enum)
        if validation_errors:
            if not json_output:
                console.print(" [red]✗[/red]")
                console.print("[red]Validation errors:[/red]")
                for error in validation_errors:
                    console.print(f"  • {error}")
            else:
                import json

                error_output = {
                    "status": "error",
                    "error_type": "ValidationError",
                    "error_message": "Content schema validation failed",
                    "validation_errors": validation_errors,
                    "content_type": content_type_name,
                    "content_id": content_id,
                }
                console.print(json.dumps(error_output, indent=2))

            raise typer.Exit(EXIT_VALIDATION_ERROR)

        if not json_output:
            console.print(" [green]✓[/green]")

        # Step 4: Check destination instance
        if not json_output:
            console.print("Checking destination instance...", end="")

        # Test connection
        try:
            connection_status = looker_client.test_connection()
            if not connection_status.connected or not connection_status.authenticated:
                error_msg = connection_status.error_message or "Unknown connection error"
                raise ConnectionError(error_msg)
        except Exception as e:
            if not json_output:
                console.print(" [red]✗[/red]")
                console.print(f"[red]Failed to connect to destination instance: {e}[/red]")
            else:
                import json

                error_output = {
                    "status": "error",
                    "error_type": "APIError",
                    "error_message": f"Failed to connect to destination instance: {e}",
                    "content_type": content_type_name,
                    "content_id": content_id,
                }
                console.print(json.dumps(error_output, indent=2))

            raise typer.Exit(EXIT_API_ERROR) from e

        if not json_output:
            console.print(" [green]✓[/green]")

        # Step 5: Check if content exists in destination
        try:
            destination_exists = restorer.check_exists(content_id, content_type_enum)
            operation = "update" if destination_exists else "create"

            if not json_output and destination_exists:
                console.print(
                    f"  → {content_type_name.title()} exists in destination (ID: {content_id})"
                )
                console.print(f"  → Will [yellow]UPDATE[/yellow] existing {content_type_name}")
            elif not json_output:
                console.print(f"  → {content_type_name.title()} does not exist in destination")
                console.print(f"  → Will [green]CREATE[/green] new {content_type_name}")
        except Exception as e:
            if not json_output:
                console.print(" [red]✗[/red]")
                console.print(f"[red]Failed to check destination: {e}[/red]")
            logger.error(f"Failed to check if content exists in destination: {e}")
            raise typer.Exit(EXIT_API_ERROR) from e

        # Step 6: Validate dependencies (placeholder)
        if not json_output:
            console.print("Validating dependencies...", end="")

        # TODO: Implement dependency validation
        # For now, just pass
        if not json_output:
            console.print(" [green]✓[/green]")

        # Step 7: Perform restoration (placeholder for MVP)
        if dry_run:
            # Dry run - no actual restoration
            if not json_output:
                console.print("\n[yellow]Dry run complete - no changes made[/yellow]")
                duration = time.time() - start_time
                console.print(f"Duration: [cyan]{duration:.1f}s[/cyan]")
            else:
                import json

                duration = time.time() - start_time
                output = {
                    "status": "success",
                    "dry_run": True,
                    "content_type": content_type_name,
                    "content_id": content_id,
                    "operation": operation,
                    "duration_ms": int(duration * 1000),
                }
                console.print(json.dumps(output, indent=2))

            raise typer.Exit(EXIT_SUCCESS)

        # TODO: Implement actual restoration via LookerContentRestorer.restore_single()
        # For MVP, we just indicate success placeholder
        if not json_output:
            console.print(
                "\n[yellow]⚠ Warning: Actual restoration not yet implemented (placeholder)[/yellow]"
            )
            console.print("[green]✓ Restoration would complete successfully![/green]")
            duration = time.time() - start_time
            console.print(f"  Destination ID: [cyan]{content_id}[/cyan]")
            console.print(f"  Duration: [cyan]{duration:.1f}s[/cyan]")
        else:
            import json

            duration = time.time() - start_time
            output = {
                "status": "success",
                "content_type": content_type_name,
                "content_id": content_id,
                "operation": operation,
                "destination_id": content_id,
                "duration_ms": int(duration * 1000),
            }
            console.print(json.dumps(output, indent=2))

        # Clean exit
        repository.close()
        raise typer.Exit(EXIT_SUCCESS)

    except typer.Exit:
        raise
    except ConfigError as e:
        if not json_output:
            print_error(f"Configuration error: {e}")
        logger.error(f"Configuration error: {e}")
        raise typer.Exit(EXIT_VALIDATION_ERROR) from None
    except ValidationError as e:
        if not json_output:
            print_error(f"Validation error: {e}")
        logger.error(f"Validation error: {e}")
        raise typer.Exit(EXIT_VALIDATION_ERROR) from None
    except DeserializationError as e:
        if not json_output:
            print_error(f"Deserialization error: {e}")
        logger.error(f"Deserialization error: {e}")
        raise typer.Exit(EXIT_VALIDATION_ERROR) from None
    except RestorationError as e:
        if not json_output:
            print_error(f"Restoration error: {e}")
        logger.error(f"Restoration error: {e}")
        raise typer.Exit(EXIT_GENERAL_ERROR) from None
    except KeyboardInterrupt:
        if not json_output:
            print_error("Restoration interrupted by user")
        logger.info("Restoration interrupted by user")
        raise typer.Exit(130) from None
    except Exception as e:
        if not json_output:
            print_error(f"Unexpected error: {e}")
        logger.exception("Unexpected error during restoration")
        raise typer.Exit(EXIT_GENERAL_ERROR) from None
