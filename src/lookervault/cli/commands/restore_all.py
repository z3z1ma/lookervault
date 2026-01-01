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
    NotFoundError,
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


def should_show_confirmation_prompt(
    dry_run: bool, force: bool, json_output: bool, quiet: bool
) -> bool:
    """Determine if the confirmation prompt should be shown.

    The prompt is shown when none of the flags that suppress it are active.

    Args:
        dry_run: Dry run mode (no changes, so no confirmation needed)
        force: Force mode (skip confirmation)
        json_output: JSON output mode (no interactive prompts)
        quiet: Quiet mode (minimal output, no prompts)

    Returns:
        True if the confirmation prompt should be shown, False otherwise
    """
    return not any([dry_run, force, json_output, quiet])


def should_use_console_output(json_output: bool, quiet: bool) -> bool:
    """Determine if human-readable console output should be displayed.

    Console output is used when neither JSON output nor quiet mode is active.

    Args:
        json_output: JSON output mode (suppresses console output)
        quiet: Quiet mode (suppresses most output)

    Returns:
        True if console output should be displayed, False otherwise
    """
    return not json_output and not quiet


def should_show_progress(json_output: bool, quiet: bool) -> bool:
    """Determine if progress indicators should be shown.

    Progress is shown when in console mode (not JSON, not quiet).

    Args:
        json_output: JSON output mode (no progress bars)
        quiet: Quiet mode (no progress indicators)

    Returns:
        True if progress should be shown, False otherwise
    """
    return should_use_console_output(json_output, quiet)


def output_error_message(
    message: str,
    json_output: bool,
    error_type: str = "Error",
    troubleshooting: str | None = None,
) -> None:
    """Output an error message in the appropriate format.

    Args:
        message: The error message to display
        json_output: Whether to output in JSON format
        error_type: Type of error (for JSON output)
        troubleshooting: Optional troubleshooting tips (for console output)
    """
    if json_output:
        error_output = {
            "status": "error",
            "error_type": error_type,
            "error_message": message,
        }
        console.print(json.dumps(error_output, indent=2))
    else:
        console.print(f"[red]✗ {message}[/red]")
        if troubleshooting:
            console.print(f"\nTroubleshooting:\n  {troubleshooting}")


def calculate_success_rate(success_count: int, total_count: int) -> float:
    """Calculate success rate as a percentage.

    Args:
        success_count: Number of successful items
        total_count: Total number of items

    Returns:
        Success rate as a percentage (0.0 to 100.0)
    """
    if total_count > 0:
        return success_count / total_count * 100
    return 0.0


def format_duration(seconds: float) -> str:
    """Format duration in a human-readable way.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted duration string (e.g., "5m 30s" or "45.2s")
    """
    if seconds >= 60:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    return f"{seconds:.1f}s"


def display_restoration_summary(
    total_items: int,
    success_count: int,
    created_count: int,
    updated_count: int,
    error_count: int,
    duration_seconds: float,
    json_output: bool,
) -> None:
    """Display restoration summary in the appropriate format.

    Args:
        total_items: Total number of items processed
        success_count: Number of successfully restored items
        created_count: Number of newly created items
        updated_count: Number of updated items
        error_count: Number of failed items
        duration_seconds: Total duration in seconds
        json_output: Whether to output in JSON format
    """
    success_rate = calculate_success_rate(success_count, total_items)

    if json_output:
        # JSON output would be handled by the caller with more context
        return

    console.print("\n[bold green]✓ Full restoration complete![/bold green]")
    console.print(f"  Total: {total_items} items")

    if error_count > 0:
        console.print(
            f"  Success: {success_count} ({success_rate:.1f}%) - "
            f"[yellow]{created_count} created, {updated_count} updated[/yellow]"
        )
        console.print(f"  [red]Failed: {error_count}[/red]")
    else:
        console.print(
            f"  Success: {success_count} ({success_rate:.1f}%) - "
            f"{created_count} created, {updated_count} updated"
        )

    console.print(f"  Total Duration: [cyan]{format_duration(duration_seconds)}[/cyan]")


def cleanup_snapshot_if_needed(snapshot_path: Path | None) -> None:
    """Clean up temporary snapshot file if it exists.

    Args:
        snapshot_path: Path to temporary snapshot file, or None
    """
    if snapshot_path:
        from lookervault.restoration.snapshot_integration import cleanup_temp_snapshot

        cleanup_temp_snapshot(snapshot_path)


def restore_all(
    config: Path | None = None,
    db_path: str | None = None,
    from_snapshot: str | None = None,
    exclude_types: list[str] | None = None,
    only_types: list[str] | None = None,
    workers: int | None = None,
    rate_limit_per_minute: int | None = None,
    rate_limit_per_second: int | None = None,
    checkpoint_interval: int | None = None,
    max_retries: int | None = None,
    dry_run: bool = False,
    force: bool = False,
    json_output: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    debug: bool = False,
    folder_ids: str | None = None,
    recursive: bool = False,
) -> None:
    """Restore all content types in dependency order.

    Args:
        config: Optional path to config file
        db_path: Path to SQLite backup database (default: LOOKERVAULT_DB_PATH or "looker.db")
        from_snapshot: Restore from cloud snapshot (index like "1" or timestamp like "2025-12-14T10:30:00")
        exclude_types: Content types to exclude from restoration
        only_types: Restore only these content types (if specified, exclude_types ignored)
        workers: Number of parallel workers (default: config file or 8)
        rate_limit_per_minute: API rate limit per minute (default: config file or 120)
        rate_limit_per_second: Burst rate limit per second (default: config file or 10)
        checkpoint_interval: Save checkpoint every N items (default: config file or 100)
        max_retries: Maximum retry attempts for transient errors (default: config file or 5)
        dry_run: Validate and show what would be restored without making changes
        force: Skip confirmation prompt
        json_output: Output results in JSON format
        verbose: Enable verbose logging
        quiet: Suppress all non-error output
        debug: Enable debug logging
        folder_ids: Comma-separated folder IDs to filter restoration (only dashboard, look, board, folder)
        recursive: Include subfolders when using folder_ids

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
    # Handle snapshot download if --from-snapshot provided
    temp_snapshot_path = None
    snapshot_metadata = None

    if from_snapshot:
        try:
            # Import here to avoid circular dependency
            from lookervault.restoration.snapshot_integration import (
                download_snapshot_to_temp,
            )

            # Download snapshot to temp location
            if should_show_progress(json_output, quiet):
                console.print(f"\nDownloading snapshot: [cyan]{from_snapshot}[/cyan]")

            temp_snapshot_path, snapshot_metadata = download_snapshot_to_temp(
                snapshot_ref=from_snapshot,
                verify_checksum=True,
                show_progress=should_show_progress(json_output, quiet),
            )

            # Display snapshot metadata
            if should_show_progress(json_output, quiet):
                from datetime import UTC, datetime

                console.print(f"  Snapshot: [cyan]{snapshot_metadata.filename}[/cyan]")
                console.print(
                    f"  Created: {snapshot_metadata.created.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                )
                console.print(f"  Size: {snapshot_metadata.size_bytes:,} bytes")
                age_days = (datetime.now(UTC) - snapshot_metadata.created).days
                console.print(f"  Age: {age_days} days")
                console.print()

            # Use temporary snapshot path as database
            db_path = str(temp_snapshot_path)

        except ValueError as e:
            output_error_message(
                f"Invalid snapshot reference: {e}",
                json_output,
                error_type="ValueError",
                troubleshooting="Run 'lookervault snapshot list' to see available snapshots.",
            )
            raise typer.Exit(EXIT_VALIDATION_ERROR) from e
        except Exception as e:
            output_error_message(
                f"Snapshot download failed: {e}",
                json_output,
                error_type="SnapshotDownloadError",
                troubleshooting=(
                    "1. Check network connectivity\n"
                    "  2. Verify GCS credentials (gcloud auth application-default login)\n"
                    "  3. Ensure snapshot exists (lookervault snapshot list)"
                ),
            )
            raise typer.Exit(EXIT_GENERAL_ERROR) from e

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
        # Parse and validate folder_ids if provided
        parsed_folder_ids: list[str] | None = None
        if folder_ids:
            # Content types that support folder filtering
            folder_filterable_types = {
                ContentType.DASHBOARD,
                ContentType.LOOK,
                ContentType.BOARD,
                ContentType.FOLDER,
            }

            # Parse comma-separated folder IDs
            parsed_folder_ids = [fid.strip() for fid in folder_ids.split(",") if fid.strip()]

            if not parsed_folder_ids:
                output_error_message(
                    "No valid folder IDs provided",
                    json_output,
                    error_type="ValidationError",
                )
                raise typer.Exit(EXIT_VALIDATION_ERROR)

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

        # Resolve folder hierarchy if recursive=True
        if parsed_folder_ids and recursive:
            try:
                from lookervault.folder.hierarchy import FolderHierarchyResolver

                resolver = FolderHierarchyResolver(repository)

                # Validate folders exist
                resolver.validate_folders_exist(parsed_folder_ids)

                # Track original count before expansion
                original_folder_count = len(parsed_folder_ids)

                # Expand to include all descendant folders
                all_folder_ids = resolver.get_all_descendant_ids(
                    parsed_folder_ids, include_roots=True
                )
                parsed_folder_ids = list(all_folder_ids)

                if should_show_progress(json_output, quiet) and verbose:
                    console.print(
                        f"[dim]Expanded {original_folder_count} folder(s) to "
                        f"{len(parsed_folder_ids)} total folder(s) (recursive)[/dim]"
                    )

            except NotFoundError as e:
                output_error_message(
                    f"Folder validation failed: {e}",
                    json_output,
                    error_type="NotFoundError",
                )
                raise typer.Exit(EXIT_NOT_FOUND) from e
        elif parsed_folder_ids:
            # Non-recursive mode: just validate folders exist
            try:
                from lookervault.folder.hierarchy import FolderHierarchyResolver

                resolver = FolderHierarchyResolver(repository)
                resolver.validate_folders_exist(parsed_folder_ids)

            except NotFoundError as e:
                output_error_message(
                    f"Folder validation failed: {e}",
                    json_output,
                    error_type="NotFoundError",
                )
                raise typer.Exit(EXIT_NOT_FOUND) from e

        # Validate folder filtering only applies to supported content types
        if parsed_folder_ids:
            folder_filterable_types = {
                ContentType.DASHBOARD,
                ContentType.LOOK,
                ContentType.BOARD,
                ContentType.FOLDER,
            }

            # Check if only_types is specified - warn if any type doesn't support folders
            if only_types:
                only_type_ints = [parse_content_type(ct) for ct in only_types]
                only_type_enums = [ContentType(ct) for ct in only_type_ints]
                unsupported_types = [
                    ct for ct in only_type_enums if ct not in folder_filterable_types
                ]

                if unsupported_types and should_use_console_output(json_output, quiet):
                    console.print(
                        f"[yellow]⚠ Warning: Folder filtering will be ignored for: "
                        f"{', '.join(t.name.lower() for t in unsupported_types)}[/yellow]"
                    )
                    console.print(
                        f"[dim]Folder filtering only works with: "
                        f"{', '.join(t.name.lower() for t in folder_filterable_types)}[/dim]"
                    )

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
            if should_use_console_output(json_output, quiet):
                console.print("[yellow]⚠ No content types to restore[/yellow]")
            raise typer.Exit(EXIT_SUCCESS)

        total_types = len(ordered_types)

        # Confirmation prompt for destructive operation (unless dry_run or force or JSON output)
        if should_show_confirmation_prompt(dry_run, force, json_output, quiet):
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
        if should_show_progress(json_output, quiet):
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
            folder_ids=parsed_folder_ids,
            destination_instance=str(cfg.looker.api_url),
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
                    display_restoration_summary(
                        total_items=summary.total_items,
                        success_count=summary.success_count,
                        created_count=summary.created_count,
                        updated_count=summary.updated_count,
                        error_count=summary.error_count,
                        duration_seconds=total_duration,
                        json_output=json_output,
                    )

                # Clean exit
                repository.close()

                # Cleanup temporary snapshot if used
                cleanup_snapshot_if_needed(temp_snapshot_path)

                # Exit with appropriate code
                if summary.error_count > 0:
                    raise typer.Exit(EXIT_GENERAL_ERROR)
                else:
                    raise typer.Exit(EXIT_SUCCESS)

            except Exception as e:
                if not json_output:
                    print_error(f"Parallel restoration error: {e}")
                logger.exception("Error during parallel restoration")
                # Cleanup temporary snapshot on error
                cleanup_snapshot_if_needed(temp_snapshot_path)
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

            if should_show_progress(json_output, quiet):
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
                if should_show_progress(json_output, quiet):
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
                if should_show_progress(json_output, quiet):
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
            display_restoration_summary(
                total_items=aggregated_results["total_items"],
                success_count=aggregated_results["success_count"],
                created_count=aggregated_results["created_count"],
                updated_count=aggregated_results["updated_count"],
                error_count=aggregated_results["error_count"],
                duration_seconds=total_duration,
                json_output=json_output,
            )

        # Clean exit
        repository.close()

        # Cleanup temporary snapshot if used
        cleanup_snapshot_if_needed(temp_snapshot_path)

        # Exit with appropriate code
        if aggregated_results["error_count"] > 0:
            raise typer.Exit(EXIT_GENERAL_ERROR)
        else:
            raise typer.Exit(EXIT_SUCCESS)

    except typer.Exit:
        # Cleanup temporary snapshot on early exit
        cleanup_snapshot_if_needed(temp_snapshot_path)
        raise
    except ConfigError as e:
        if not json_output:
            print_error(f"Configuration error: {e}")
        logger.error(f"Configuration error: {e}")
        # Cleanup temporary snapshot on error
        cleanup_snapshot_if_needed(temp_snapshot_path)
        raise typer.Exit(EXIT_VALIDATION_ERROR) from None
    except ValidationError as e:
        if not json_output:
            print_error(f"Validation error: {e}")
        logger.error(f"Validation error: {e}")
        # Cleanup temporary snapshot on error
        cleanup_snapshot_if_needed(temp_snapshot_path)
        raise typer.Exit(EXIT_VALIDATION_ERROR) from None
    except DeserializationError as e:
        if not json_output:
            print_error(f"Deserialization error: {e}")
        logger.error(f"Deserialization error: {e}")
        # Cleanup temporary snapshot on error
        cleanup_snapshot_if_needed(temp_snapshot_path)
        raise typer.Exit(EXIT_VALIDATION_ERROR) from None
    except RestorationError as e:
        if not json_output:
            print_error(f"Restoration error: {e}")
        logger.error(f"Restoration error: {e}")
        # Cleanup temporary snapshot on error
        cleanup_snapshot_if_needed(temp_snapshot_path)
        raise typer.Exit(EXIT_GENERAL_ERROR) from None
    except KeyboardInterrupt:
        # Graceful Ctrl+C handling - checkpoint already saved by orchestrator/restorer
        if should_show_progress(json_output, quiet):
            console.print("\n[yellow]⚠ Interrupted by user (Ctrl+C)[/yellow]")
            console.print(
                "[dim]Progress has been saved. Use 'restore all' with the same options to resume.[/dim]"
            )
        logger.info("Restoration interrupted by user (KeyboardInterrupt)")
        # Cleanup temporary snapshot on interrupt
        cleanup_snapshot_if_needed(temp_snapshot_path)
        raise typer.Exit(130) from None
    except Exception as e:
        if not json_output:
            print_error(f"Unexpected error: {e}")
        logger.exception("Unexpected error during restoration")
        # Cleanup temporary snapshot on unexpected error
        cleanup_snapshot_if_needed(temp_snapshot_path)
        raise typer.Exit(EXIT_GENERAL_ERROR) from None
