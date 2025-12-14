"""Extract command implementation for content extraction."""

import logging
import os
from pathlib import Path

import typer

from lookervault.cli.rich_logging import configure_rich_logging, console, print_error
from lookervault.cli.types import parse_content_types
from lookervault.config.loader import load_config
from lookervault.config.models import ParallelConfig
from lookervault.exceptions import ConfigError, OrchestrationError
from lookervault.extraction.orchestrator import ExtractionConfig, ExtractionOrchestrator
from lookervault.extraction.parallel_orchestrator import ParallelOrchestrator
from lookervault.extraction.performance import PerformanceTuner
from lookervault.extraction.progress import (
    JsonProgressTracker,
    RichProgressTracker,
)
from lookervault.looker.client import LookerClient
from lookervault.looker.extractor import LookerContentExtractor
from lookervault.storage.models import ContentType
from lookervault.storage.repository import SQLiteContentRepository
from lookervault.storage.serializer import MsgpackSerializer

logger = logging.getLogger(__name__)

# Default worker count: conservative default based on CPU cores
DEFAULT_WORKERS = min(os.cpu_count() or 1, 8)


def run(
    config: Path | None = None,
    output: str = "table",
    db: str = "looker.db",
    types: str | None = None,
    batch_size: int = 100,
    resume: bool = True,
    incremental: bool = False,
    workers: int = DEFAULT_WORKERS,
    rate_limit_per_minute: int | None = None,
    rate_limit_per_second: int | None = None,
    verbose: bool = False,
    debug: bool = False,
) -> None:
    """Run content extraction from Looker instance.

    Args:
        config: Optional path to config file
        output: Output format ("table" or "json")
        db: Database path for storage
        types: Comma-separated content types to extract (default: all)
        batch_size: Items per batch for memory management
        resume: Resume incomplete extraction
        incremental: Extract only new/changed content since last extraction
        workers: Number of worker threads for parallel extraction (1-50, default: min(cpu_count, 8))
        rate_limit_per_minute: Max API requests per minute (default: 100)
        rate_limit_per_second: Max API requests per second burst (default: 10)
        verbose: Enable verbose logging
        debug: Enable debug logging
    """
    # Configure rich logging - default to INFO for extraction to show progress
    log_level = logging.DEBUG if debug else logging.INFO
    configure_rich_logging(
        level=log_level,
        show_time=debug,  # Only show timestamps in debug mode
        show_path=debug,  # Only show file paths in debug mode
        enable_link_path=debug,  # Only enable clickable paths in debug mode
    )

    try:
        # Auto-detect workers if not specified (workers=0)
        if workers == 0:
            workers = DEFAULT_WORKERS
            logger.info(f"Auto-detected {workers} workers based on CPU cores")

        # Load configuration
        cfg = load_config(config)

        # Validate credentials
        if not cfg.looker.client_id or not cfg.looker.client_secret:
            console.print("[red]✗ Missing credentials[/red]")
            console.print(
                "Set LOOKERVAULT_CLIENT_ID and LOOKERVAULT_CLIENT_SECRET environment variables"
            )
            raise typer.Exit(2)

        # Parse content types
        content_types = parse_content_types(types)

        # Create components
        looker_client = LookerClient(
            api_url=str(cfg.looker.api_url),
            client_id=cfg.looker.client_id,
            client_secret=cfg.looker.client_secret,
            timeout=cfg.looker.timeout,
            verify_ssl=cfg.looker.verify_ssl,
        )

        repository = SQLiteContentRepository(db_path=db)
        serializer = MsgpackSerializer()
        extractor = LookerContentExtractor(client=looker_client)

        # Test connection first
        if not extractor.test_connection():
            console.print("[red]✗ Failed to connect to Looker instance[/red]")
            console.print("Run 'lookervault check' to diagnose connection issues")
            raise typer.Exit(3)

        # Create progress tracker
        if output == "json":
            progress_tracker = JsonProgressTracker()
        else:
            progress_tracker = RichProgressTracker()

        # Validate worker count
        if workers < 1 or workers > 50:
            console.print(f"[red]✗ Invalid worker count: {workers} (must be 1-50)[/red]")
            raise typer.Exit(2)

        # Warn if worker count is very high
        if workers > 16:
            console.print(
                f"[yellow]⚠ Warning: {workers} workers may cause SQLite write contention. "
                "Recommended: 8-16 workers for optimal throughput.[/yellow]"
            )

        # Validate configuration and provide performance recommendations
        if workers > 1:
            tuner = PerformanceTuner()
            config_warnings = tuner.validate_configuration(
                workers=workers,
                queue_size=workers * 100,  # Default queue size
                batch_size=batch_size,
            )

            for warning in config_warnings:
                if verbose or "WARNING" in warning.upper():
                    console.print(f"[yellow]⚠ {warning}[/yellow]")

            # Suggest optimal configuration in verbose mode
            if verbose:
                profile = tuner.recommend_for_dataset(total_items=None, avg_item_size_kb=5.0)
                if profile.workers != workers:
                    console.print(
                        f"[dim]💡 Recommended: {profile.workers} workers "
                        f"(expected throughput: {profile.expected_throughput:.0f} items/sec)[/dim]"
                    )

        # Create extraction config
        extraction_config = ExtractionConfig(
            content_types=content_types,
            batch_size=batch_size,
            resume=resume,
            incremental=incremental,
            output_mode=output,
        )

        # Choose orchestrator based on worker count
        if workers == 1:
            # Sequential extraction (existing behavior)
            orchestrator = ExtractionOrchestrator(
                extractor=extractor,
                repository=repository,
                serializer=serializer,
                progress=progress_tracker,
                config=extraction_config,
            )
            if output != "json":
                console.print("[cyan]Running sequential extraction (1 worker)[/cyan]")
        else:
            # Parallel extraction (new!)
            # Build parallel config with optional rate limit overrides
            parallel_config_kwargs = {
                "workers": workers,
                "queue_size": workers * 100,  # Auto-calculated
                "batch_size": batch_size,
                "adaptive_rate_limiting": True,
            }

            # Apply rate limit overrides if provided
            if rate_limit_per_minute is not None:
                parallel_config_kwargs["rate_limit_per_minute"] = rate_limit_per_minute
            if rate_limit_per_second is not None:
                parallel_config_kwargs["rate_limit_per_second"] = rate_limit_per_second

            parallel_config = ParallelConfig(**parallel_config_kwargs)
            orchestrator = ParallelOrchestrator(
                extractor=extractor,
                repository=repository,
                serializer=serializer,
                progress=progress_tracker,
                config=extraction_config,
                parallel_config=parallel_config,
            )
            if output != "json":
                console.print(
                    f"[cyan]Running parallel extraction with {workers} workers "
                    f"(queue_size={parallel_config.queue_size}, batch_size={batch_size})[/cyan]"
                )
                console.print(
                    f"[dim]Extracting: {', '.join([ContentType(ct).name.lower() for ct in content_types])}[/dim]"
                )

        # Run extraction
        if output != "json":
            console.print("[cyan]Starting extraction...[/cyan]")

        with progress_tracker:
            result = orchestrator.extract()

        # Display summary (if not in JSON mode)
        if output != "json":
            console.print("\n[green]✓ Extraction complete![/green]")

            # Calculate throughput
            throughput = (
                result.total_items / result.duration_seconds if result.duration_seconds > 0 else 0
            )

            console.print(
                f"\nExtracted {result.total_items} items in {result.duration_seconds:.1f}s "
                f"({throughput:.1f} items/sec):"
            )
            for content_type, count in result.items_by_type.items():
                type_name = ContentType(content_type).name.lower()
                console.print(f"  {type_name}: {count} items")

            # Show parallel execution stats
            if workers > 1:
                console.print("\n[cyan]Parallel execution:[/cyan]")
                console.print(f"  Workers: {workers}")
                console.print(f"  Throughput: {throughput:.1f} items/sec")
                if result.errors > 0:
                    console.print(f"  [yellow]Errors: {result.errors}[/yellow]")

            # Show incremental stats if available
            if incremental and (result.new_items or result.updated_items or result.deleted_items):
                console.print("\n[cyan]Incremental summary:[/cyan]")
                if result.new_items:
                    console.print(f"  New items: {result.new_items}")
                if result.updated_items:
                    console.print(f"  Updated items: {result.updated_items}")
                if result.deleted_items:
                    console.print(f"  Deleted items: {result.deleted_items}")

            console.print(f"\nStorage: {db}")

        # Clean exit
        repository.close()
        raise typer.Exit(0)

    except typer.Exit:
        raise
    except ConfigError as e:
        if output != "json":
            print_error(f"Configuration error: {e}")
        logger.error(f"Configuration error: {e}")
        raise typer.Exit(2) from None
    except OrchestrationError as e:
        if output != "json":
            print_error(f"Extraction error: {e}")
        logger.error(f"Extraction error: {e}")
        raise typer.Exit(1) from None
    except KeyboardInterrupt:
        if output != "json":
            print_error("Extraction interrupted by user")
            console.print("[dim]Run 'lookervault extract --resume' to continue[/dim]")
        logger.info("Extraction interrupted by user")
        raise typer.Exit(130) from None
    except Exception as e:
        if output != "json":
            print_error(f"Unexpected error: {e}")
        logger.exception("Unexpected error during extraction")
        raise typer.Exit(1) from None
