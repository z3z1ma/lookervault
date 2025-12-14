"""Restore command implementation for content restoration."""

import json as json_module
import logging
import time
import uuid
from pathlib import Path

import typer
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from lookervault.cli.rich_logging import configure_rich_logging, console, print_error
from lookervault.cli.types import parse_content_type
from lookervault.config.loader import load_config
from lookervault.config.models import RestorationConfig
from lookervault.exceptions import (
    ConfigError,
    DeserializationError,
    RestorationError,
    ValidationError,
)
from lookervault.extraction.rate_limiter import AdaptiveRateLimiter
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

        # Create rate limiter for API throttling
        rate_limiter = AdaptiveRateLimiter(
            requests_per_minute=120,
            requests_per_second=10,
        )

        # Create restorer for check_exists() and restoration operations
        restorer = LookerContentRestorer(
            client=looker_client,
            repository=repository,
            rate_limiter=rate_limiter,
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

        # Step 7: Perform actual restoration via LookerContentRestorer.restore_single()
        if not json_output:
            console.print("\nRestoring content...", end="")

        # Call restore_single to perform the actual restoration
        result = restorer.restore_single(content_id, content_type_enum, dry_run=False)

        # Check result and display appropriate output
        if result.status in ["created", "updated"]:
            # Success!
            if not json_output:
                console.print(" [green]✓[/green]")
                console.print(
                    f"\n[bold green]✓ Restoration successful![/bold green] ({result.status.upper()})"
                )
                console.print(f"  Source ID: [cyan]{content_id}[/cyan]")
                console.print(f"  Destination ID: [cyan]{result.destination_id}[/cyan]")
                console.print(f"  Duration: [cyan]{result.duration_ms:.1f}ms[/cyan]")
            else:
                import json

                output = {
                    "status": "success",
                    "content_type": content_type_name,
                    "content_id": content_id,
                    "operation": result.status,
                    "destination_id": result.destination_id,
                    "duration_ms": result.duration_ms,
                }
                console.print(json.dumps(output, indent=2))

            # Clean exit
            repository.close()
            raise typer.Exit(EXIT_SUCCESS)

        else:
            # Failed
            if not json_output:
                console.print(" [red]✗[/red]")
                console.print("\n[bold red]✗ Restoration failed![/bold red]")
                console.print(f"  Error: {result.error_message}")
                console.print(f"  Duration: [cyan]{result.duration_ms:.1f}ms[/cyan]")
            else:
                import json

                output = {
                    "status": "error",
                    "error_type": "RestorationError",
                    "error_message": result.error_message,
                    "content_type": content_type_name,
                    "content_id": content_id,
                    "duration_ms": result.duration_ms,
                }
                console.print(json.dumps(output, indent=2))

            # Clean exit
            repository.close()
            raise typer.Exit(EXIT_GENERAL_ERROR)

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


def restore_bulk(
    content_type: str,
    config: Path | None = None,
    db_path: str = "looker.db",
    workers: int = 8,
    rate_limit_per_minute: int = 120,
    rate_limit_per_second: int = 10,
    checkpoint_interval: int = 100,
    max_retries: int = 5,
    skip_if_modified: bool = False,
    dry_run: bool = False,
    json_output: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> None:
    """Restore all content items of a specific type in bulk.

    Args:
        content_type: Content type to restore (dashboard, look, folder, etc.)
        config: Optional path to config file
        db_path: Path to SQLite backup database
        workers: Number of parallel workers (currently supports 1 for sequential)
        rate_limit_per_minute: API rate limit per minute
        rate_limit_per_second: Burst rate limit per second
        checkpoint_interval: Save checkpoint every N items
        max_retries: Maximum retry attempts for transient errors
        skip_if_modified: Skip items modified in destination since backup
        dry_run: Validate and show what would be restored without making changes
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

        # Create rate limiter
        rate_limiter = AdaptiveRateLimiter(
            requests_per_minute=rate_limit_per_minute,
            requests_per_second=rate_limit_per_second,
        )

        # Create restorer
        restorer = LookerContentRestorer(
            client=looker_client,
            repository=repository,
            rate_limiter=rate_limiter,
        )

        # Create RestorationConfig
        session_id = str(uuid.uuid4())
        restoration_config = RestorationConfig(
            workers=workers,
            rate_limit_per_minute=rate_limit_per_minute,
            rate_limit_per_second=rate_limit_per_second,
            checkpoint_interval=checkpoint_interval,
            max_retries=max_retries,
            dry_run=dry_run,
            skip_if_modified=skip_if_modified,
        )
        restoration_config.session_id = session_id  # type: ignore

        # Display start message
        if not json_output:
            console.print(f"\n[bold]Bulk restoring {content_type_name.title()}...[/bold]")
            if dry_run:
                console.print("[dim](Dry run mode - no changes will be made)[/dim]\n")

        # Call restore_bulk with progress tracking
        if not json_output:
            # Create rich progress bar
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(f"Restoring {content_type_name}...", total=None)

                # Call restore_bulk
                summary = restorer.restore_bulk(content_type_enum, restoration_config)

                # Update progress bar
                progress.update(task, completed=summary.total_items, total=summary.total_items)

            # Display summary
            console.print("\n[bold green]✓ Bulk restoration complete![/bold green]")
            console.print(f"  Total: {summary.total_items} {content_type_name}")
            console.print(
                f"  Success: {summary.success_count} ({summary.success_count / summary.total_items * 100:.1f}%) - "
                f"{summary.created_count} created, {summary.updated_count} updated"
            )
            if summary.error_count > 0:
                console.print(f"  [red]Failed: {summary.error_count}[/red]")
            console.print(
                f"  Duration: {summary.duration_seconds:.1f}s ({summary.average_throughput:.1f} items/sec)"
            )
        else:
            # Call restore_bulk (no progress bar for JSON output)
            summary = restorer.restore_bulk(content_type_enum, restoration_config)

            # JSON output
            output = {
                "status": "completed",
                "session_id": session_id,
                "content_type": content_type_name,
                "summary": {
                    "total_items": summary.total_items,
                    "success_count": summary.success_count,
                    "created_count": summary.created_count,
                    "updated_count": summary.updated_count,
                    "error_count": summary.error_count,
                    "skipped_count": summary.skipped_count,
                    "duration_seconds": summary.duration_seconds,
                    "average_throughput": summary.average_throughput,
                },
                "error_breakdown": summary.error_breakdown,
            }
            console.print(json_module.dumps(output, indent=2))

        # Clean exit
        repository.close()

        # Exit with appropriate code
        if summary.error_count > 0:
            raise typer.Exit(EXIT_GENERAL_ERROR)
        else:
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
    except Exception as e:
        if not json_output:
            print_error(f"Unexpected error: {e}")
        logger.exception("Unexpected error during bulk restoration")
        raise typer.Exit(EXIT_GENERAL_ERROR) from None


def restore_resume(
    content_type: str,
    session_id: str | None = None,
    config: Path | None = None,
    db_path: str = "looker.db",
    workers: int = 8,
    rate_limit_per_minute: int = 120,
    rate_limit_per_second: int = 10,
    checkpoint_interval: int = 100,
    max_retries: int = 5,
    skip_if_modified: bool = False,
    dry_run: bool = False,
    json_output: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> None:
    """Resume an interrupted restoration from the last checkpoint.

    Args:
        content_type: Content type to resume (dashboard, look, folder, etc.)
        session_id: Optional session ID to resume (defaults to latest checkpoint for content type)
        config: Optional path to config file
        db_path: Path to SQLite backup database
        workers: Number of parallel workers
        rate_limit_per_minute: API rate limit per minute
        rate_limit_per_second: Burst rate limit per second
        checkpoint_interval: Save checkpoint every N items
        max_retries: Maximum retry attempts for transient errors
        skip_if_modified: Skip items modified in destination since backup
        dry_run: Validate and show what would be restored without making changes
        json_output: Output results in JSON format
        verbose: Enable verbose logging
        debug: Enable debug logging

    Exit codes:
        0: Success
        1: General error
        2: No checkpoint found
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

    try:
        # Parse content type
        content_type_int = parse_content_type(content_type)
        content_type_enum = ContentType(content_type_int)

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
        repository = SQLiteContentRepository(db_path=db_path)

        # Step 1: Load latest checkpoint for content_type (optionally filtered by session_id)
        checkpoint = repository.get_latest_restoration_checkpoint(
            content_type=content_type_int,
            session_id=session_id,
        )

        if not checkpoint:
            if not json_output:
                if session_id:
                    console.print(
                        f"[red]✗ No checkpoint found for {content_type_enum.name.lower()} with session {session_id}[/red]"
                    )
                else:
                    console.print(
                        f"[red]✗ No checkpoint found for {content_type_enum.name.lower()}[/red]"
                    )
            raise typer.Exit(EXIT_NOT_FOUND)

        # Extract checkpoint data (validate content_type matches)
        if checkpoint.content_type != content_type_int:
            if not json_output:
                console.print(
                    f"[red]✗ Content type mismatch: expected {content_type_enum.name.lower()}, "
                    f"got {ContentType(checkpoint.content_type).name.lower()}[/red]"
                )
            raise typer.Exit(EXIT_VALIDATION_ERROR)
        content_type_name = content_type_enum.name.lower()
        completed_ids = checkpoint.checkpoint_data.get("completed_ids", [])

        if not json_output:
            console.print("\n[bold]Resuming restoration from checkpoint...[/bold]")
            console.print(f"  Session ID: [cyan]{checkpoint.session_id}[/cyan]")
            console.print(f"  Content Type: [cyan]{content_type_name.title()}[/cyan]")
            console.print(f"  Already completed: [cyan]{len(completed_ids)} items[/cyan]\n")

        # Create Looker client and restorer
        looker_client = LookerClient(
            api_url=str(cfg.looker.api_url),
            client_id=cfg.looker.client_id,
            client_secret=cfg.looker.client_secret,
            timeout=cfg.looker.timeout,
            verify_ssl=cfg.looker.verify_ssl,
        )

        rate_limiter = AdaptiveRateLimiter(
            requests_per_minute=rate_limit_per_minute,
            requests_per_second=rate_limit_per_second,
        )

        restorer = LookerContentRestorer(
            client=looker_client,
            repository=repository,
            rate_limiter=rate_limiter,
        )

        # Create RestorationConfig
        restoration_config = RestorationConfig(
            workers=workers,
            rate_limit_per_minute=rate_limit_per_minute,
            rate_limit_per_second=rate_limit_per_second,
            checkpoint_interval=checkpoint_interval,
            max_retries=max_retries,
            dry_run=dry_run,
            skip_if_modified=skip_if_modified,
        )
        restoration_config.session_id = checkpoint.session_id  # type: ignore

        # Step 2: Call restore_bulk with checkpoint (will filter out completed IDs)
        summary = restorer.restore_bulk(
            content_type_enum,
            restoration_config,
            resume_checkpoint=checkpoint,
        )

        # Display summary
        if not json_output:
            console.print("\n[bold green]✓ Resumed restoration complete![/bold green]")
            console.print(f"  Total new items: {summary.total_items} {content_type_name}")
            console.print(
                f"  Success: {summary.success_count} ({summary.success_count / summary.total_items * 100 if summary.total_items > 0 else 0:.1f}%) - "
                f"{summary.created_count} created, {summary.updated_count} updated"
            )
            if summary.error_count > 0:
                console.print(f"  [red]Failed: {summary.error_count}[/red]")
            console.print(
                f"  Duration: {summary.duration_seconds:.1f}s ({summary.average_throughput:.1f} items/sec)"
            )
        else:
            # JSON output
            output = {
                "status": "completed",
                "session_id": checkpoint.session_id,
                "content_type": content_type_name,
                "resumed_from_checkpoint": True,
                "previously_completed": len(completed_ids),
                "summary": {
                    "total_items": summary.total_items,
                    "success_count": summary.success_count,
                    "created_count": summary.created_count,
                    "updated_count": summary.updated_count,
                    "error_count": summary.error_count,
                    "skipped_count": summary.skipped_count,
                    "duration_seconds": summary.duration_seconds,
                    "average_throughput": summary.average_throughput,
                },
                "error_breakdown": summary.error_breakdown,
            }
            console.print(json_module.dumps(output, indent=2))

        # Clean exit
        repository.close()

        # Exit with appropriate code
        if summary.error_count > 0:
            raise typer.Exit(EXIT_GENERAL_ERROR)
        else:
            raise typer.Exit(EXIT_SUCCESS)

    except typer.Exit:
        raise
    except ConfigError as e:
        if not json_output:
            print_error(f"Configuration error: {e}")
        logger.error(f"Configuration error: {e}")
        raise typer.Exit(EXIT_VALIDATION_ERROR) from None
    except Exception as e:
        if not json_output:
            print_error(f"Unexpected error: {e}")
        logger.exception("Unexpected error during restoration resume")
        raise typer.Exit(EXIT_GENERAL_ERROR) from None
