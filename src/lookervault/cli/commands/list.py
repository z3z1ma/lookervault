"""List command implementation for querying extracted content metadata."""

import logging
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.table import Table

from lookervault.cli.rich_logging import configure_rich_logging, console, print_error
from lookervault.cli.types import parse_content_type
from lookervault.exceptions import StorageError
from lookervault.storage.models import ContentType
from lookervault.storage.repository import SQLiteContentRepository

logger = logging.getLogger(__name__)


def run(
    content_type: str,
    db: str = "looker.db",
    created_after: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    output: str = "table",
    verbose: bool = False,
    debug: bool = False,
) -> None:
    """List extracted content items with optional filters.

    Args:
        content_type: Content type to list (e.g., "dashboards", "looks")
        db: Database path to query
        created_after: Filter by creation date (ISO format)
        limit: Maximum items to return (default: 50 for table, unlimited for JSON)
        offset: Pagination offset
        output: Output format ("table" or "json")
        verbose: Enable verbose logging
        debug: Enable debug logging
    """
    # Configure rich logging
    log_level = logging.DEBUG if debug else (logging.INFO if verbose else logging.WARNING)
    configure_rich_logging(level=log_level, show_time=debug, show_path=debug)

    # Default limits for table output to prevent overwhelming display
    default_table_limit = 50

    try:
        # Check if database exists
        db_path = Path(db)
        if not db_path.exists():
            console.print(f"[red]✗ Database not found: {db}[/red]")
            console.print("Run 'lookervault extract' first to create a backup")
            raise typer.Exit(1)

        # Create repository
        repository = SQLiteContentRepository(db_path=db)

        # Parse content type
        ct = parse_content_type(content_type)

        # Get total count before applying limit (for display purposes)
        total_count = repository.count_content(content_type=ct, include_deleted=False)

        # Apply default limit for table output if not specified
        # limit=None means use default, limit=0 means show all
        effective_limit = limit
        if output == "table" and limit is None:
            effective_limit = default_table_limit
        elif limit == 0:
            # --limit 0 means show all items
            effective_limit = None

        # Get items
        items = repository.list_content(
            content_type=ct,
            include_deleted=False,
            limit=effective_limit,
            offset=offset,
        )

        # Apply additional filters
        if created_after:
            cutoff = datetime.fromisoformat(created_after)
            items = [item for item in items if item.created_at >= cutoff]

        # Apply additional filters (affects displayed count but not total count)
        filtered_count = len(items)

        # Display results
        if output == "json":
            import json

            items_data = [
                {
                    "id": item.id,
                    "name": item.name,
                    "owner_email": item.owner_email,
                    "folder_id": item.folder_id,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                    "synced_at": item.synced_at.isoformat() if item.synced_at else None,
                    "content_size": item.content_size,
                }
                for item in items
            ]
            console.print_json(json.dumps(items_data, indent=2))
        else:
            # Table format
            content_type_name = ContentType(ct).name.lower().capitalize()
            table = Table(title=f"{content_type_name}")

            # Content types that support folder organization
            folder_supported_types = {ContentType.DASHBOARD, ContentType.LOOK, ContentType.BOARD}
            show_folder = ct in folder_supported_types

            table.add_column("ID", style="cyan")
            table.add_column("Name", style="white")
            if show_folder:
                table.add_column("Folder ID", style="magenta")
            table.add_column("Owner", style="yellow")
            table.add_column("Updated", style="green")
            table.add_column("Size", style="blue")

            for item in items:
                # Format updated_at as relative time if recent
                if item.updated_at:
                    # Use timezone-aware datetime for comparison
                    now = datetime.now(UTC)
                    updated = item.updated_at

                    # Add UTC timezone if naive
                    if updated.tzinfo is None:
                        updated = updated.replace(tzinfo=UTC)

                    delta = now - updated
                    if delta.days == 0:
                        updated_str = "Today"
                    elif delta.days == 1:
                        updated_str = "Yesterday"
                    elif delta.days < 7:
                        updated_str = f"{delta.days}d ago"
                    else:
                        updated_str = item.updated_at.strftime("%Y-%m-%d")
                else:
                    updated_str = "N/A"

                # Format size
                size_kb = item.content_size / 1024 if item.content_size else 0
                if size_kb < 1024:
                    size_str = f"{size_kb:.1f} KB"
                else:
                    size_str = f"{size_kb / 1024:.1f} MB"

                # Truncate ID and name for display
                item_id = item.id.split("::")[-1][:20]
                name = item.name[:40] + "..." if len(item.name) > 40 else item.name
                owner = item.owner_email or "N/A"
                folder = item.folder_id or "N/A"

                if show_folder:
                    table.add_row(item_id, name, folder, owner, updated_str, size_str)
                else:
                    table.add_row(item_id, name, owner, updated_str, size_str)

            console.print(table)

            # Show count summary
            if filtered_count < total_count:
                # Truncated or paginated
                console.print(
                    f"\n[bold]Showing {filtered_count} of {total_count:,} total items[/bold]"
                )
                if output == "table" and limit is None:
                    # Default truncation applied
                    console.print(
                        "[dim]Use --limit to show more (e.g., --limit 100) or --limit 0 to show all[/dim]"
                    )
                elif effective_limit:
                    # User-specified limit
                    console.print(
                        f"[dim]Use --offset {offset + filtered_count} to see next page[/dim]"
                    )
            else:
                # All items shown
                console.print(f"\n[bold]Total: {total_count:,} items[/bold]")

        # Clean exit
        repository.close()
        raise typer.Exit(0)

    except typer.Exit:
        raise
    except StorageError as e:
        print_error(f"Storage error: {e}")
        raise typer.Exit(1) from None
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        logger.exception("Unexpected error during list operation")
        raise typer.Exit(1) from None
