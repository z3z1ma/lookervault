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
from rich.prompt import Confirm
from rich.table import Table

from lookervault.cli.rich_logging import configure_rich_logging, console, print_error
from lookervault.cli.types import parse_content_type
from lookervault.config.loader import get_db_path, load_config
from lookervault.config.models import RestorationConfig
from lookervault.exceptions import (
    ConfigError,
    DeserializationError,
    NotFoundError,
    RestorationError,
    ValidationError,
)
from lookervault.extraction.metrics import ThreadSafeMetrics
from lookervault.extraction.rate_limiter import AdaptiveRateLimiter
from lookervault.looker.client import LookerClient
from lookervault.restoration.dead_letter_queue import DeadLetterQueue
from lookervault.restoration.deserializer import ContentDeserializer
from lookervault.restoration.parallel_orchestrator import ParallelRestorationOrchestrator
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
    db_path: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    json_output: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    debug: bool = False,
) -> None:
    """Restore a single content item by type and ID.

    Args:
        content_type: Content type to restore (dashboard, look, folder, etc.)
        content_id: ID of the content item to restore
        config: Optional path to config file
        db_path: Path to SQLite backup database (default: LOOKERVAULT_DB_PATH or "looker.db")
        dry_run: Validate and show what would be restored without making changes
        force: Skip confirmation prompts
        json_output: Output results in JSON format
        verbose: Enable verbose logging
        quiet: Suppress all non-error output
        debug: Enable debug logging

    Environment Variables:
        LOOKERVAULT_DB_PATH: Default database path
        LOOKER_BASE_URL or LOOKERVAULT_API_URL: Looker instance URL
        LOOKER_CLIENT_ID or LOOKERVAULT_CLIENT_ID: API client ID
        LOOKER_CLIENT_SECRET or LOOKERVAULT_CLIENT_SECRET: API client secret

    Exit codes:
        0: Success
        1: General error
        2: Content not found in backup
        3: Validation error
        4: API error (rate limit, authentication, etc.)
    """
    # Resolve database path from CLI arg > env var > default
    resolved_db_path = get_db_path(db_path)

    # Configure logging (quiet overrides verbose)
    if quiet:
        log_level = logging.ERROR
    elif debug:
        log_level = logging.DEBUG
    elif verbose:
        log_level = logging.INFO
    else:
        log_level = logging.WARNING

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

        repository = SQLiteContentRepository(db_path=resolved_db_path)
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
    db_path: str | None = None,
    workers: int | None = None,
    rate_limit_per_minute: int | None = None,
    rate_limit_per_second: int | None = None,
    checkpoint_interval: int | None = None,
    max_retries: int | None = None,
    skip_if_modified: bool = False,
    dry_run: bool = False,
    json_output: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    debug: bool = False,
) -> None:
    """Restore all content items of a specific type in bulk.

    Args:
        content_type: Content type to restore (dashboard, look, folder, etc.)
        config: Optional path to config file
        db_path: Path to SQLite backup database (default: LOOKERVAULT_DB_PATH or "looker.db")
        workers: Number of parallel workers (default: config file or 8)
        rate_limit_per_minute: API rate limit per minute (default: config file or 120)
        rate_limit_per_second: Burst rate limit per second (default: config file or 10)
        checkpoint_interval: Save checkpoint every N items (default: config file or 100)
        max_retries: Maximum retry attempts for transient errors (default: config file or 5)
        skip_if_modified: Skip items modified in destination since backup
        dry_run: Validate and show what would be restored without making changes
        json_output: Output results in JSON format
        verbose: Enable verbose logging
        quiet: Suppress all non-error output
        debug: Enable debug logging

    Environment Variables:
        LOOKERVAULT_DB_PATH: Default database path
        LOOKER_BASE_URL or LOOKERVAULT_API_URL: Looker instance URL
        LOOKER_CLIENT_ID or LOOKERVAULT_CLIENT_ID: API client ID
        LOOKER_CLIENT_SECRET or LOOKERVAULT_CLIENT_SECRET: API client secret

    Exit codes:
        0: Success
        1: General error
        2: Content not found in backup
        3: Validation error
        4: API error (rate limit, authentication, etc.)
    """
    # Resolve database path from CLI arg > env var > default
    resolved_db_path = get_db_path(db_path)

    # Configure logging (quiet overrides verbose)
    if quiet:
        log_level = logging.ERROR
    elif debug:
        log_level = logging.DEBUG
    elif verbose:
        log_level = logging.INFO
    else:
        log_level = logging.WARNING

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

        # Use config file defaults if CLI args not provided (CLI > env > config > hardcoded)
        final_workers = workers if workers is not None else cfg.restore.workers
        final_rate_limit_per_minute = (
            rate_limit_per_minute
            if rate_limit_per_minute is not None
            else cfg.restore.rate_limit_per_minute
        )
        final_rate_limit_per_second = (
            rate_limit_per_second
            if rate_limit_per_second is not None
            else cfg.restore.rate_limit_per_second
        )
        final_checkpoint_interval = (
            checkpoint_interval
            if checkpoint_interval is not None
            else cfg.restore.checkpoint_interval
        )
        final_max_retries = max_retries if max_retries is not None else cfg.restore.max_retries

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

        repository = SQLiteContentRepository(db_path=resolved_db_path)

        # Create rate limiter
        rate_limiter = AdaptiveRateLimiter(
            requests_per_minute=final_rate_limit_per_minute,
            requests_per_second=final_rate_limit_per_second,
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
            workers=final_workers,
            rate_limit_per_minute=final_rate_limit_per_minute,
            rate_limit_per_second=final_rate_limit_per_second,
            checkpoint_interval=final_checkpoint_interval,
            max_retries=final_max_retries,
            dry_run=dry_run,
            skip_if_modified=skip_if_modified,
        )
        restoration_config.session_id = session_id  # type: ignore

        # Display start message
        if not json_output and not quiet:
            console.print(f"\n[bold]Bulk restoring {content_type_name.title()}...[/bold]")
            if dry_run:
                console.print("[dim](Dry run mode - no changes will be made)[/dim]\n")
            if final_workers > 1:
                console.print(
                    f"[dim]Using {final_workers} worker threads for parallel restoration[/dim]\n"
                )

        # Choose parallel or sequential restoration based on worker count
        if final_workers > 1:
            # Use parallel orchestrator
            # Create required dependencies
            metrics = ThreadSafeMetrics()

            # Create orchestrator
            # Note: repository implements DeadLetterQueue Protocol (save_dead_letter_item)
            orchestrator = ParallelRestorationOrchestrator(
                restorer=restorer,
                repository=repository,
                config=restoration_config,
                rate_limiter=rate_limiter,
                metrics=metrics,
                dlq=repository,  # Repository implements the DLQ Protocol
            )

            # Call parallel restore with progress tracking
            if not json_output:
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

                    # Call orchestrator.restore()
                    summary = orchestrator.restore(content_type_enum, session_id)

                    # Update progress bar
                    progress.update(task, completed=summary.total_items, total=summary.total_items)
            else:
                # No progress bar for JSON output
                summary = orchestrator.restore(content_type_enum, session_id)
        else:
            # Use sequential restoration (backward compatible)
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
            else:
                # No progress bar for JSON output
                summary = restorer.restore_bulk(content_type_enum, restoration_config)

        # Display summary
        if not json_output:
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
    except KeyboardInterrupt:
        # Graceful Ctrl+C handling - checkpoint already saved by orchestrator/restorer
        if not json_output and not quiet:
            console.print("\n[yellow]⚠ Interrupted by user (Ctrl+C)[/yellow]")
            console.print(
                "[dim]Progress has been saved. Run the same command with --resume to continue.[/dim]"
            )
        logger.info("Restoration interrupted by user (KeyboardInterrupt)")
        raise typer.Exit(130) from None
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
            if workers > 1:
                console.print(
                    f"[dim]Using {workers} worker threads for parallel restoration[/dim]\n"
                )

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

        # Step 2: Choose parallel or sequential restoration based on worker count
        if workers > 1:
            # Use parallel orchestrator for resume
            metrics = ThreadSafeMetrics()

            # Create orchestrator
            # Note: repository implements DeadLetterQueue Protocol (save_dead_letter_item)
            orchestrator = ParallelRestorationOrchestrator(
                restorer=restorer,
                repository=repository,
                config=restoration_config,
                rate_limiter=rate_limiter,
                metrics=metrics,
                dlq=repository,  # Repository implements the DLQ Protocol
            )

            # Call orchestrator.resume()
            # Checkpoint must have session_id - use it or fall back to current session_id
            resume_session_id = checkpoint.session_id if checkpoint.session_id else session_id
            if resume_session_id is None:
                logger.error("Cannot resume: checkpoint has no session_id")
                raise typer.Exit(EXIT_VALIDATION_ERROR)
            summary = orchestrator.resume(content_type_enum, resume_session_id)
        else:
            # Use sequential restoration (backward compatible)
            # Call restore_bulk with checkpoint (will filter out completed IDs)
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


def restore_dlq_list(
    session_id: str | None = None,
    content_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db_path: str = "looker.db",
    json_output: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> None:
    """List dead letter queue entries.

    Args:
        session_id: Optional session ID filter
        content_type: Optional content type filter
        limit: Maximum entries to return
        offset: Pagination offset
        db_path: Path to SQLite backup database
        json_output: Output results in JSON format
        verbose: Enable verbose logging
        debug: Enable debug logging

    Exit codes:
        0: Success
        1: General error
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
        # Parse content type if provided
        content_type_enum = None
        if content_type:
            content_type_int = parse_content_type(content_type)
            content_type_enum = ContentType(content_type_int)

        # Create components
        repository = SQLiteContentRepository(db_path=db_path)
        dlq = DeadLetterQueue(repository)

        # List DLQ entries
        items = dlq.list(
            session_id=session_id,
            content_type=content_type_enum,
            limit=limit,
            offset=offset,
        )

        if json_output:
            # JSON output
            output = [
                {
                    "id": item.id,
                    "session_id": item.session_id,
                    "content_type": ContentType(item.content_type).name.lower(),
                    "content_id": item.content_id,
                    "error_type": item.error_type,
                    "error_message": item.error_message,
                    "retry_count": item.retry_count,
                    "failed_at": item.failed_at.isoformat(),
                }
                for item in items
            ]
            console.print(json_module.dumps(output, indent=2))
        else:
            # Rich table output
            if not items:
                console.print("[yellow]No DLQ entries found[/yellow]")
            else:
                table = Table(title="Dead Letter Queue")
                table.add_column("ID", style="cyan")
                table.add_column("Content Type")
                table.add_column("Content ID")
                table.add_column("Error Type", style="red")
                table.add_column("Failed At")
                table.add_column("Retries", justify="right")

                for item in items:
                    table.add_row(
                        str(item.id),
                        ContentType(item.content_type).name.lower(),
                        item.content_id,
                        item.error_type,
                        item.failed_at.strftime("%Y-%m-%d %H:%M:%S"),
                        str(item.retry_count),
                    )

                console.print(table)
                console.print(f"\nShowing {len(items)} entries (offset: {offset}, limit: {limit})")

        repository.close()
        raise typer.Exit(EXIT_SUCCESS)

    except typer.Exit:
        raise
    except Exception as e:
        if not json_output:
            print_error(f"Unexpected error: {e}")
        logger.exception("Unexpected error listing DLQ entries")
        raise typer.Exit(EXIT_GENERAL_ERROR) from None


def restore_dlq_show(
    dlq_id: int,
    db_path: str = "looker.db",
    json_output: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> None:
    """Show details of a specific DLQ entry.

    Args:
        dlq_id: DLQ entry ID
        db_path: Path to SQLite backup database
        json_output: Output results in JSON format
        verbose: Enable verbose logging
        debug: Enable debug logging

    Exit codes:
        0: Success
        2: DLQ entry not found
        1: General error
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
        # Create components
        repository = SQLiteContentRepository(db_path=db_path)
        dlq = DeadLetterQueue(repository)

        # Get DLQ entry
        item = dlq.get(dlq_id)

        if item is None:
            if not json_output:
                console.print(f"[red]DLQ entry {dlq_id} not found[/red]")
            else:
                error_output = {
                    "status": "error",
                    "error_type": "NotFoundError",
                    "error_message": f"DLQ entry {dlq_id} not found",
                }
                console.print(json_module.dumps(error_output, indent=2))
            repository.close()
            raise typer.Exit(EXIT_NOT_FOUND)

        if json_output:
            # JSON output
            output = {
                "id": item.id,
                "session_id": item.session_id,
                "content_type": ContentType(item.content_type).name.lower(),
                "content_id": item.content_id,
                "error_type": item.error_type,
                "error_message": item.error_message,
                "stack_trace": item.stack_trace,
                "retry_count": item.retry_count,
                "failed_at": item.failed_at.isoformat(),
                "metadata": item.metadata,
            }
            console.print(json_module.dumps(output, indent=2))
        else:
            # Human-readable output
            console.print(f"\n[bold]DLQ Entry {item.id}[/bold]")
            console.print(f"Session ID: [cyan]{item.session_id}[/cyan]")
            console.print(f"Content Type: {ContentType(item.content_type).name.lower()}")
            console.print(f"Content ID: [cyan]{item.content_id}[/cyan]")
            console.print(f"Error Type: [red]{item.error_type}[/red]")
            console.print(f"Error Message: {item.error_message}")
            console.print(f"Retry Count: {item.retry_count}")
            console.print(f"Failed At: {item.failed_at.strftime('%Y-%m-%d %H:%M:%S')}")

            if item.stack_trace:
                console.print("\n[bold]Stack Trace:[/bold]")
                console.print(f"[dim]{item.stack_trace}[/dim]")

            if item.metadata:
                console.print("\n[bold]Metadata:[/bold]")
                console.print(json_module.dumps(item.metadata, indent=2))

        repository.close()
        raise typer.Exit(EXIT_SUCCESS)

    except typer.Exit:
        raise
    except Exception as e:
        if not json_output:
            print_error(f"Unexpected error: {e}")
        logger.exception("Unexpected error showing DLQ entry")
        raise typer.Exit(EXIT_GENERAL_ERROR) from None


def restore_dlq_retry(
    dlq_id: int,
    config: Path | None = None,
    db_path: str = "looker.db",
    fix_dependencies: bool = False,
    force: bool = False,
    json_output: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> None:
    """Retry restoration for a failed DLQ entry.

    Args:
        dlq_id: DLQ entry ID to retry
        config: Optional path to config file
        db_path: Path to SQLite backup database
        fix_dependencies: Attempt to fix dependency issues (not implemented)
        force: Force retry even if likely to fail
        json_output: Output results in JSON format
        verbose: Enable verbose logging
        debug: Enable debug logging

    Exit codes:
        0: Retry successful
        1: Retry failed
        2: DLQ entry not found
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
        dlq = DeadLetterQueue(repository)

        # Create Looker client and restorer
        looker_client = LookerClient(
            api_url=str(cfg.looker.api_url),
            client_id=cfg.looker.client_id,
            client_secret=cfg.looker.client_secret,
            timeout=cfg.looker.timeout,
            verify_ssl=cfg.looker.verify_ssl,
        )

        rate_limiter = AdaptiveRateLimiter(
            requests_per_minute=120,
            requests_per_second=10,
        )

        restorer = LookerContentRestorer(
            client=looker_client,
            repository=repository,
            rate_limiter=rate_limiter,
        )

        # Display start message
        if not json_output:
            console.print(f"\nRetrying DLQ entry [cyan]{dlq_id}[/cyan]...")

        # Retry restoration
        try:
            result = dlq.retry(dlq_id, restorer)
        except NotFoundError as e:
            if not json_output:
                console.print(f"[red]DLQ entry {dlq_id} not found[/red]")
            else:
                error_output = {
                    "status": "error",
                    "error_type": "NotFoundError",
                    "error_message": f"DLQ entry {dlq_id} not found",
                }
                console.print(json_module.dumps(error_output, indent=2))
            repository.close()
            raise typer.Exit(EXIT_NOT_FOUND) from e

        # Check result
        if result.status in ["created", "updated"]:
            if not json_output:
                console.print(
                    f"[bold green]✓ Retry successful! ({result.status.upper()})[/bold green]"
                )
                console.print(f"  Destination ID: [cyan]{result.destination_id}[/cyan]")
                console.print(f"  Duration: [cyan]{result.duration_ms:.1f}ms[/cyan]")
            else:
                output = {
                    "status": "success",
                    "operation": result.status,
                    "destination_id": result.destination_id,
                    "duration_ms": result.duration_ms,
                }
                console.print(json_module.dumps(output, indent=2))

            repository.close()
            raise typer.Exit(EXIT_SUCCESS)
        else:
            if not json_output:
                console.print("[bold red]✗ Retry failed![/bold red]")
                console.print(f"  Error: {result.error_message}")
            else:
                output = {
                    "status": "error",
                    "error_type": "RestorationError",
                    "error_message": result.error_message,
                }
                console.print(json_module.dumps(output, indent=2))

            repository.close()
            raise typer.Exit(EXIT_GENERAL_ERROR)

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
        logger.exception("Unexpected error retrying DLQ entry")
        raise typer.Exit(EXIT_GENERAL_ERROR) from None


def restore_dlq_clear(
    session_id: str | None = None,
    content_type: str | None = None,
    all_entries: bool = False,
    force: bool = False,
    db_path: str = "looker.db",
    json_output: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> None:
    """Clear DLQ entries.

    Args:
        session_id: Optional session ID filter
        content_type: Optional content type filter
        all_entries: Clear all entries (requires force=True)
        force: Force clear without confirmation
        db_path: Path to SQLite backup database
        json_output: Output results in JSON format
        verbose: Enable verbose logging
        debug: Enable debug logging

    Exit codes:
        0: Success
        3: Validation error (missing force flag)
        1: General error
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
        # Parse content type if provided
        content_type_enum = None
        if content_type:
            content_type_int = parse_content_type(content_type)
            content_type_enum = ContentType(content_type_int)

        # If not forced, require user confirmation (unless JSON output)
        if not force and not json_output:
            # Preview what will be cleared
            repository = SQLiteContentRepository(db_path=db_path)
            dlq = DeadLetterQueue(repository)
            preview_items = dlq.list(
                session_id=session_id,
                content_type=content_type_enum,
                limit=10,
                offset=0,
            )

            if not preview_items:
                console.print("[yellow]No DLQ entries found matching filters[/yellow]")
                repository.close()
                raise typer.Exit(EXIT_SUCCESS)

            # Show preview
            console.print(f"[yellow]⚠ About to clear {len(preview_items)}+ DLQ entries[/yellow]")
            if session_id:
                console.print(f"  Session ID: {session_id}")
            if content_type:
                console.print(f"  Content Type: {content_type}")

            # Ask for confirmation
            if not Confirm.ask("\nPermanently clear these DLQ entries?", default=False):
                console.print("Operation cancelled")
                repository.close()
                raise typer.Exit(EXIT_SUCCESS)

            repository.close()
        elif not force and json_output:
            # JSON output mode requires --force flag for safety
            error_output = {
                "status": "error",
                "error_type": "ValidationError",
                "error_message": "Force flag required for safety in JSON output mode",
            }
            console.print(json_module.dumps(error_output, indent=2))
            raise typer.Exit(EXIT_VALIDATION_ERROR)

        # Create components (may already be created during confirmation)
        repository = SQLiteContentRepository(db_path=db_path)
        dlq = DeadLetterQueue(repository)

        # Clear DLQ entries
        count = dlq.clear(
            session_id=session_id,
            content_type=content_type_enum,
        )

        if json_output:
            output = {
                "status": "success",
                "cleared_count": count,
            }
            console.print(json_module.dumps(output, indent=2))
        else:
            console.print(f"[green]✓ Cleared {count} DLQ entries[/green]")

        repository.close()
        raise typer.Exit(EXIT_SUCCESS)

    except typer.Exit:
        raise
    except Exception as e:
        if not json_output:
            print_error(f"Unexpected error: {e}")
        logger.exception("Unexpected error clearing DLQ entries")
        raise typer.Exit(EXIT_GENERAL_ERROR) from None


def restore_status(
    session_id: str | None = None,
    all_sessions: bool = False,
    db_path: str = "looker.db",
    json_output: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> None:
    """Show restoration session status.

    Args:
        session_id: Optional session ID to show (None = latest session)
        all_sessions: Show all sessions
        db_path: Path to SQLite backup database
        json_output: Output results in JSON format
        verbose: Enable verbose logging
        debug: Enable debug logging

    Exit codes:
        0: Success
        2: Session not found
        1: General error
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
        # Create repository
        repository = SQLiteContentRepository(db_path=db_path)

        if all_sessions:
            # List all sessions
            sessions = repository.list_restoration_sessions(limit=100, offset=0)

            if not sessions:
                if not json_output:
                    console.print("[yellow]No restoration sessions found[/yellow]")
                else:
                    console.print(json_module.dumps([], indent=2))
                repository.close()
                raise typer.Exit(EXIT_SUCCESS)

            if json_output:
                output = [
                    {
                        "session_id": session.id,
                        "status": session.status,
                        "started_at": session.started_at.isoformat(),
                        "completed_at": session.completed_at.isoformat()
                        if session.completed_at
                        else None,
                        "duration_seconds": (
                            session.completed_at - session.started_at
                        ).total_seconds()
                        if session.completed_at
                        else None,
                        "total_items": session.total_items,
                        "success_count": session.success_count,
                        "error_count": session.error_count,
                        "source_instance": session.source_instance,
                        "destination_instance": session.destination_instance,
                    }
                    for session in sessions
                ]
                console.print(json_module.dumps(output, indent=2))
            else:
                table = Table(title="Restoration Sessions")
                table.add_column("Session ID", style="cyan")
                table.add_column("Status")
                table.add_column("Started")
                table.add_column("Duration")
                table.add_column("Progress")
                table.add_column("Errors", style="red")

                for session in sessions:
                    duration = (
                        f"{(session.completed_at - session.started_at).total_seconds():.1f}s"
                        if session.completed_at
                        else "In progress"
                    )
                    progress = f"{session.success_count}/{session.total_items}"
                    status_color = (
                        "green"
                        if session.status == "completed"
                        else "yellow"
                        if session.status == "running"
                        else "red"
                    )

                    table.add_row(
                        session.id[:8] + "...",
                        f"[{status_color}]{session.status}[/{status_color}]",
                        session.started_at.strftime("%Y-%m-%d %H:%M:%S"),
                        duration,
                        progress,
                        str(session.error_count),
                    )

                console.print(table)

        else:
            # Show single session
            if session_id:
                session = repository.get_restoration_session(session_id)
            else:
                # Get latest session
                sessions = repository.list_restoration_sessions(limit=1, offset=0)
                session = sessions[0] if sessions else None

            if session is None:
                if not json_output:
                    if session_id:
                        console.print(f"[red]Session {session_id} not found[/red]")
                    else:
                        console.print("[yellow]No restoration sessions found[/yellow]")
                else:
                    error_output = {
                        "status": "error",
                        "error_type": "NotFoundError",
                        "error_message": f"Session {session_id or 'latest'} not found",
                    }
                    console.print(json_module.dumps(error_output, indent=2))
                repository.close()
                raise typer.Exit(EXIT_NOT_FOUND)

            if json_output:
                output = {
                    "session_id": session.id,
                    "status": session.status,
                    "started_at": session.started_at.isoformat(),
                    "completed_at": session.completed_at.isoformat()
                    if session.completed_at
                    else None,
                    "duration_seconds": (session.completed_at - session.started_at).total_seconds()
                    if session.completed_at
                    else None,
                    "total_items": session.total_items,
                    "success_count": session.success_count,
                    "error_count": session.error_count,
                    "source_instance": session.source_instance,
                    "destination_instance": session.destination_instance,
                    "config": session.config,
                    "metadata": session.metadata,
                }
                console.print(json_module.dumps(output, indent=2))
            else:
                console.print(f"\n[bold]Restoration Session: {session.id}[/bold]")
                console.print(
                    f"Status: [{session.status}]{session.status.upper()}[/{session.status}]"
                )
                console.print(f"Started: {session.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
                if session.completed_at:
                    duration = (session.completed_at - session.started_at).total_seconds()
                    console.print(
                        f"Completed: {session.completed_at.strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    console.print(f"Duration: {duration:.1f}s")
                else:
                    console.print("Duration: [yellow]In progress[/yellow]")

                console.print("\n[bold]Progress:[/bold]")
                console.print(f"  Total Items: {session.total_items}")
                console.print(f"  Success: [green]{session.success_count}[/green]")
                console.print(f"  Errors: [red]{session.error_count}[/red]")

                if session.source_instance:
                    console.print(f"\nSource: {session.source_instance}")
                console.print(f"Destination: {session.destination_instance}")

                if session.metadata:
                    console.print("\n[bold]Metadata:[/bold]")
                    console.print(json_module.dumps(session.metadata, indent=2))

        repository.close()
        raise typer.Exit(EXIT_SUCCESS)

    except typer.Exit:
        raise
    except Exception as e:
        if not json_output:
            print_error(f"Unexpected error: {e}")
        logger.exception("Unexpected error showing restoration status")
        raise typer.Exit(EXIT_GENERAL_ERROR) from None
