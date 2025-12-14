"""Restore all command implementation for bulk content restoration."""

import json
import logging
import time
import uuid
from collections import defaultdict
from pathlib import Path

import typer
from rich.prompt import Confirm

from lookervault.cli.rich_logging import configure_rich_logging, console, print_error
from lookervault.cli.types import parse_content_type
from lookervault.config.loader import get_db_path, load_config
from lookervault.config.models import RestorationConfig
from lookervault.exceptions import (
    ConfigError,
    DeserializationError,
    RestorationError,
    ValidationError,
)
from lookervault.extraction.metrics import ThreadSafeMetrics
from lookervault.extraction.rate_limiter import AdaptiveRateLimiter
from lookervault.looker.client import LookerClient
from lookervault.restoration.dependency_graph import DependencyGraph
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


def restore_all(
    config: Path | None = None,
    db_path: str | None = None,
    exclude_types: list[str] | None = None,
    only_types: list[str] | None = None,
    workers: int | None = None,
    rate_limit_per_minute: int | None = None,
    rate_limit_per_second: int | None = None,
    checkpoint_interval: int | None = None,
    max_retries: int | None = None,
    skip_if_modified: bool = False,
    dry_run: bool = False,
    force: bool = False,
    json_output: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    debug: bool = False,
) -> None:
    """Restore all content types in dependency order.

    Args:
        config: Optional path to config file
        db_path: Path to SQLite backup database (default: LOOKERVAULT_DB_PATH or "looker.db")
        exclude_types: Content types to exclude from restoration
        only_types: Restore only these content types (if specified, exclude_types ignored)
        workers: Number of parallel workers (default: config file or 8)
        rate_limit_per_minute: API rate limit per minute (default: config file or 120)
        rate_limit_per_second: Burst rate limit per second (default: config file or 10)
        checkpoint_interval: Save checkpoint every N items (default: config file or 100)
        max_retries: Maximum retry attempts for transient errors (default: config file or 5)
        skip_if_modified: Skip items modified in destination since backup
        dry_run: Validate and show what would be restored without making changes
        force: Skip confirmation prompt
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

        # Step 1: Use DependencyGraph to get restoration order
        dependency_graph = DependencyGraph()

        # Determine which content types to restore
        if only_types:
            # Parse only_types list
            content_types_to_restore = [parse_content_type(ct) for ct in only_types]
            requested_types = [ContentType(ct) for ct in content_types_to_restore]
        else:
            # Get all content types, then filter by exclude_types
            requested_types = None  # Will get all types from dependency graph

        # Get restoration order (dependencies first)
        ordered_types = dependency_graph.get_restoration_order(requested_types)

        # Apply exclude_types filter if specified (and only_types not specified)
        if exclude_types and not only_types:
            exclude_type_ints = [parse_content_type(ct) for ct in exclude_types]
            exclude_type_enums = {ContentType(ct) for ct in exclude_type_ints}
            ordered_types = [ct for ct in ordered_types if ct not in exclude_type_enums]

        if not ordered_types:
            if not json_output:
                console.print("[yellow]⚠ No content types to restore[/yellow]")
            raise typer.Exit(EXIT_SUCCESS)

        total_types = len(ordered_types)

        # Confirmation prompt for destructive operation (unless dry_run or force or JSON output)
        if not dry_run and not force and not json_output and not quiet:
            console.print(
                "\n[bold yellow]⚠ WARNING: Bulk restoration of ALL content types[/bold yellow]"
            )
            console.print(
                f"This will restore [cyan]{total_types}[/cyan] content types from the backup:"
            )
            for ct in ordered_types[:5]:  # Show first 5 types
                console.print(f"  • {ct.name.lower()}")
            if total_types > 5:
                console.print(f"  ... and {total_types - 5} more")
            console.print(
                "\n[dim]This may overwrite existing content in the destination instance.[/dim]"
            )

            if not Confirm.ask("\nProceed with bulk restoration?", default=False):
                console.print("Operation cancelled")
                repository.close()
                raise typer.Exit(EXIT_SUCCESS)

        # Display start message
        if not json_output and not quiet:
            console.print("\n[bold]Restoring all content types in dependency order...[/bold]")
            if dry_run:
                console.print("[dim](Dry run mode - no changes will be made)[/dim]\n")
            if final_workers > 1:
                console.print(
                    f"[dim]Using {final_workers} worker threads for parallel restoration[/dim]\n"
                )

        # Step 2: Create RestorationConfig
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

        # Add session_id to config (if not already present)
        if not hasattr(restoration_config, "session_id"):
            restoration_config.session_id = session_id  # type: ignore

        # Step 3: Choose parallel or sequential restoration based on worker count
        if final_workers > 1:
            # Use parallel orchestrator for restore_all
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

            # Call orchestrator.restore_all() with the ordered types
            try:
                summary = orchestrator.restore_all(requested_types=ordered_types)

                # Display final summary
                total_duration = time.time() - start_time

                if json_output:
                    # JSON output format
                    output = {
                        "status": "completed",
                        "session_id": session_id,
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
                        "by_content_type": {
                            ContentType(ct).name.lower(): count
                            for ct, count in summary.content_type_breakdown.items()
                        },
                        "error_breakdown": summary.error_breakdown,
                    }
                    console.print(json.dumps(output, indent=2))
                else:
                    # Human-readable output
                    console.print("\n[bold green]✓ Full restoration complete![/bold green]")
                    console.print(f"  Total: {summary.total_items} items")

                    success_rate = (
                        (summary.success_count / summary.total_items * 100)
                        if summary.total_items > 0
                        else 0.0
                    )

                    if summary.error_count > 0:
                        console.print(
                            f"  Success: {summary.success_count} ({success_rate:.1f}%) - "
                            f"[yellow]{summary.created_count} created, "
                            f"{summary.updated_count} updated[/yellow]"
                        )
                        console.print(f"  [red]Failed: {summary.error_count}[/red]")
                    else:
                        console.print(
                            f"  Success: {summary.success_count} ({success_rate:.1f}%) - "
                            f"{summary.created_count} created, "
                            f"{summary.updated_count} updated"
                        )

                    # Format duration nicely
                    if summary.duration_seconds >= 60:
                        minutes = int(summary.duration_seconds // 60)
                        seconds = int(summary.duration_seconds % 60)
                        duration_str = f"{minutes}m {seconds}s"
                    else:
                        duration_str = f"{summary.duration_seconds:.1f}s"

                    console.print(f"  Total Duration: [cyan]{duration_str}[/cyan]")

                # Clean exit
                repository.close()

                # Exit with appropriate code
                if summary.error_count > 0:
                    raise typer.Exit(EXIT_GENERAL_ERROR)
                else:
                    raise typer.Exit(EXIT_SUCCESS)

            except Exception as e:
                if not json_output:
                    print_error(f"Parallel restoration error: {e}")
                logger.exception("Error during parallel restoration")
                raise typer.Exit(EXIT_GENERAL_ERROR) from None

        # Step 4: Sequential restoration (backward compatible, workers == 1)
        # Aggregate results across all types
        aggregated_results = {
            "total_items": 0,
            "success_count": 0,
            "created_count": 0,
            "updated_count": 0,
            "error_count": 0,
            "skipped_count": 0,
            "content_type_breakdown": defaultdict(int),
            "error_breakdown": defaultdict(int),
            "per_type_summaries": [],
        }

        # Step 5: Loop through types, calling restore_bulk() for each
        for idx, content_type in enumerate(ordered_types, 1):
            content_type_name = content_type.name.lower()

            if not json_output:
                console.print(
                    f"\n[{idx}/{total_types}] [cyan]{content_type_name.title()}[/cyan]..."
                )

            # Call restore_bulk() for this content type
            try:
                summary = restorer.restore_bulk(content_type, restoration_config)

                # Aggregate results
                aggregated_results["total_items"] += summary.total_items
                aggregated_results["success_count"] += summary.success_count
                aggregated_results["created_count"] += summary.created_count
                aggregated_results["updated_count"] += summary.updated_count
                aggregated_results["error_count"] += summary.error_count
                aggregated_results["skipped_count"] += summary.skipped_count

                # Merge content_type_breakdown
                for ct, count in summary.content_type_breakdown.items():
                    aggregated_results["content_type_breakdown"][ct] += count

                # Merge error_breakdown
                for error_type, count in summary.error_breakdown.items():
                    aggregated_results["error_breakdown"][error_type] += count

                # Store per-type summary
                aggregated_results["per_type_summaries"].append(
                    {
                        "content_type": content_type_name,
                        "total": summary.total_items,
                        "success": summary.success_count,
                        "errors": summary.error_count,
                        "duration_seconds": summary.duration_seconds,
                        "throughput": summary.average_throughput,
                    }
                )

                # Display per-type result
                if not json_output:
                    if summary.error_count > 0:
                        console.print(
                            f"  [yellow]✓[/yellow] {summary.success_count}/{summary.total_items} {content_type_name} restored "
                            f"({summary.duration_seconds:.1f}s, {summary.average_throughput:.1f} items/sec) "
                            f"- [red]{summary.error_count} failed[/red]"
                        )
                    else:
                        console.print(
                            f"  [green]✓[/green] {summary.success_count}/{summary.total_items} {content_type_name} restored "
                            f"({summary.duration_seconds:.1f}s, {summary.average_throughput:.1f} items/sec)"
                        )

            except Exception as e:
                # Log error but continue with next type
                logger.exception(f"Error restoring {content_type_name}: {e}")
                if not json_output:
                    console.print(f"  [red]✗ Failed to restore {content_type_name}: {e}[/red]")

        # Step 5: Display final summary
        total_duration = time.time() - start_time

        if json_output:
            # JSON output format
            output = {
                "status": "completed",
                "session_id": session_id,
                "summary": {
                    "total_items": aggregated_results["total_items"],
                    "success_count": aggregated_results["success_count"],
                    "created_count": aggregated_results["created_count"],
                    "updated_count": aggregated_results["updated_count"],
                    "error_count": aggregated_results["error_count"],
                    "skipped_count": aggregated_results["skipped_count"],
                    "duration_seconds": total_duration,
                    "average_throughput": (
                        aggregated_results["total_items"] / total_duration
                        if total_duration > 0
                        else 0.0
                    ),
                },
                "by_content_type": aggregated_results["per_type_summaries"],
                "error_breakdown": dict(aggregated_results["error_breakdown"]),
            }
            console.print(json.dumps(output, indent=2))
        else:
            # Human-readable output
            console.print("\n[bold green]✓ Full restoration complete![/bold green]")
            console.print(f"  Total: {aggregated_results['total_items']} items")

            success_rate = (
                (aggregated_results["success_count"] / aggregated_results["total_items"] * 100)
                if aggregated_results["total_items"] > 0
                else 0.0
            )

            if aggregated_results["error_count"] > 0:
                console.print(
                    f"  Success: {aggregated_results['success_count']} ({success_rate:.1f}%) - "
                    f"[yellow]{aggregated_results['created_count']} created, "
                    f"{aggregated_results['updated_count']} updated[/yellow]"
                )
                console.print(f"  [red]Failed: {aggregated_results['error_count']}[/red]")
            else:
                console.print(
                    f"  Success: {aggregated_results['success_count']} ({success_rate:.1f}%) - "
                    f"{aggregated_results['created_count']} created, "
                    f"{aggregated_results['updated_count']} updated"
                )

            # Format duration nicely
            if total_duration >= 60:
                minutes = int(total_duration // 60)
                seconds = int(total_duration % 60)
                duration_str = f"{minutes}m {seconds}s"
            else:
                duration_str = f"{total_duration:.1f}s"

            console.print(f"  Total Duration: [cyan]{duration_str}[/cyan]")

        # Clean exit
        repository.close()

        # Exit with appropriate code
        if aggregated_results["error_count"] > 0:
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
        # Graceful Ctrl+C handling - checkpoint already saved by orchestrator/restorer
        if not json_output and not quiet:
            console.print("\n[yellow]⚠ Interrupted by user (Ctrl+C)[/yellow]")
            console.print(
                "[dim]Progress has been saved. Use 'restore all' with the same options to resume.[/dim]"
            )
        logger.info("Restoration interrupted by user (KeyboardInterrupt)")
        raise typer.Exit(130) from None
    except Exception as e:
        if not json_output:
            print_error(f"Unexpected error: {e}")
        logger.exception("Unexpected error during restoration")
        raise typer.Exit(EXIT_GENERAL_ERROR) from None
