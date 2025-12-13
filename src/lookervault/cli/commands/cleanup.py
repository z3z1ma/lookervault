"""Cleanup command implementation for retention policy management."""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer
from rich.console import Console

from lookervault.exceptions import StorageError
from lookervault.storage.repository import SQLiteContentRepository

logger = logging.getLogger(__name__)


def run(
    retention_days: int = 30,
    db: str = "looker.db",
    dry_run: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> None:
    """Clean up soft-deleted items past retention period.

    Args:
        retention_days: Days to keep soft-deleted items before hard delete
        db: Database path to clean up
        dry_run: Preview changes without applying them
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
        # Validate retention days
        if retention_days < 0:
            console.print("[red]✗ Retention days must be non-negative[/red]")
            raise typer.Exit(1)

        # Check if database exists
        db_path = Path(db)
        if not db_path.exists():
            console.print(f"[red]✗ Database not found: {db}[/red]")
            console.print("Nothing to clean up")
            raise typer.Exit(0)

        # Create repository
        repository = SQLiteContentRepository(db_path=db)

        # Calculate cutoff date
        cutoff_date = datetime.now(UTC) - timedelta(days=retention_days)

        console.print("[cyan]Cleanup Policy:[/cyan]")
        console.print(f"  Retention period: {retention_days} days")
        console.print(f"  Cutoff date: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')}")
        console.print(f"  Mode: {'Dry run (preview only)' if dry_run else 'Live (will delete)'}")
        console.print()

        # Get items to delete
        deleted_items = repository.get_deleted_items_before(cutoff_date)

        if not deleted_items:
            console.print("[green]✓ No items found past retention period[/green]")
            console.print("Database is clean")
            repository.close()
            raise typer.Exit(0)

        # Group by content type for display
        items_by_type: dict[str, list] = {}
        for item in deleted_items:
            type_name = item.id.split("::")[0]
            items_by_type.setdefault(type_name, []).append(item)

        # Display summary
        console.print(f"[yellow]Found {len(deleted_items)} items past retention period:[/yellow]\n")
        for type_name, items in sorted(items_by_type.items()):
            console.print(f"  {type_name}: {len(items)} items")

        console.print()

        # If dry run, just show what would be deleted
        if dry_run:
            console.print("[cyan]Dry run mode - no changes will be made[/cyan]")
            console.print("\nSample items that would be deleted:")
            for type_name, items in sorted(items_by_type.items()):
                console.print(f"\n{type_name}:")
                for item in items[:3]:  # Show first 3 items
                    if item.deleted_at:
                        now = datetime.now(UTC)
                        deleted = item.deleted_at
                        # Add UTC timezone if naive
                        if deleted.tzinfo is None:
                            deleted = deleted.replace(tzinfo=UTC)
                        deleted_age = (now - deleted).days
                    else:
                        deleted_age = 0
                    console.print(f"  - {item.id} (deleted {deleted_age} days ago)")
                if len(items) > 3:
                    console.print(f"  ... and {len(items) - 3} more items")

            console.print("\n[dim]Run without --dry-run to actually delete these items[/dim]")
            repository.close()
            raise typer.Exit(0)

        # Confirm deletion
        if not typer.confirm(f"\nPermanently delete {len(deleted_items)} items?"):
            console.print("Cleanup cancelled")
            repository.close()
            raise typer.Exit(0)

        # Perform cleanup
        console.print("\n[cyan]Cleaning up...[/cyan]")
        deleted_count = repository.hard_delete_before(cutoff_date)

        console.print("[green]✓ Cleanup complete![/green]")
        console.print(f"  Permanently deleted: {deleted_count} items")

        # Show database size change
        db_size_mb = db_path.stat().st_size / (1024 * 1024)
        console.print(f"  Database size: {db_size_mb:.1f} MB")
        console.print("\n[dim]Note: Run 'VACUUM' to reclaim disk space[/dim]")

        # Clean exit
        repository.close()
        raise typer.Exit(0)

    except typer.Exit:
        raise
    except StorageError as e:
        console.print(f"[red]Storage error: {e}[/red]")
        logger.error(f"Storage error during cleanup: {e}")
        raise typer.Exit(1) from None
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
        logger.exception("Unexpected error during cleanup")
        raise typer.Exit(1) from None
