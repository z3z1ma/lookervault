"""Extract command implementation for content extraction."""

import logging
from pathlib import Path

import typer
from rich.console import Console

from lookervault.config.loader import load_config
from lookervault.exceptions import ConfigError, OrchestrationError
from lookervault.extraction.orchestrator import ExtractionConfig, ExtractionOrchestrator
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


def run(
    config: Path | None = None,
    output: str = "table",
    db: str = "looker.db",
    types: str | None = None,
    batch_size: int = 100,
    resume: bool = True,
    incremental: bool = False,
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
        verbose: Enable verbose logging
        debug: Enable debug logging
    """
    # Configure logging
    log_level = logging.DEBUG if debug else (logging.INFO if verbose else logging.WARNING)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    console = Console()

    try:
        # Load configuration
        cfg = load_config(config)

        # Parse content types
        content_types = _parse_content_types(types)

        # Create components
        looker_client = LookerClient(
            api_url=cfg.looker.api_url,
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

        # Create extraction config
        extraction_config = ExtractionConfig(
            content_types=content_types,
            batch_size=batch_size,
            resume=resume,
            incremental=incremental,
            output_mode=output,
        )

        # Create orchestrator
        orchestrator = ExtractionOrchestrator(
            extractor=extractor,
            repository=repository,
            serializer=serializer,
            progress=progress_tracker,
            config=extraction_config,
        )

        # Run extraction
        with progress_tracker:
            result = orchestrator.extract()

        # Display summary (if not in JSON mode)
        if output != "json":
            console.print("\n[green]✓ Extraction complete![/green]")
            console.print(
                f"\nExtracted {result.total_items} items in {result.duration_seconds:.1f}s:"
            )
            for content_type, count in result.items_by_type.items():
                type_name = ContentType(content_type).name.lower()
                console.print(f"  {type_name}: {count} items")

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
            typer.echo(f"Configuration error: {e}", err=True)
        logger.error(f"Configuration error: {e}")
        raise typer.Exit(2) from None
    except OrchestrationError as e:
        if output != "json":
            typer.echo(f"Extraction error: {e}", err=True)
        logger.error(f"Extraction error: {e}")
        raise typer.Exit(1) from None
    except KeyboardInterrupt:
        if output != "json":
            typer.echo("\nExtraction interrupted by user", err=True)
            typer.echo("Run 'lookervault extract --resume' to continue")
        logger.info("Extraction interrupted by user")
        raise typer.Exit(130) from None
    except Exception as e:
        if output != "json":
            typer.echo(f"Unexpected error: {e}", err=True)
        logger.exception("Unexpected error during extraction")
        raise typer.Exit(1) from None


def _parse_content_types(types_str: str | None) -> list[int]:
    """Parse comma-separated content types string.

    Args:
        types_str: Comma-separated content type names (e.g., "dashboards,looks")

    Returns:
        List of ContentType enum values

    Raises:
        typer.BadParameter: If invalid content type specified
    """
    if not types_str:
        # Default to all content types
        return [ct.value for ct in ContentType]

    type_names = [t.strip().upper() for t in types_str.split(",")]
    content_types = []

    for type_name in type_names:
        try:
            # Remove plural 's' if present for matching
            if type_name.endswith("S") and type_name != "SCHEDULES":
                type_name = type_name[:-1]

            # Special case mappings
            if type_name == "SCHEDULE":
                type_name = "SCHEDULED_PLAN"

            content_type = ContentType[type_name]
            content_types.append(content_type.value)
        except KeyError:
            available = ", ".join(ct.name.lower() for ct in ContentType)
            raise typer.BadParameter(
                f"Invalid content type: {type_name.lower()}. Available types: {available}"
            ) from None

    return content_types
