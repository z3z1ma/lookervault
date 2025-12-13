"""Verify command implementation for content integrity validation."""

import logging
from pathlib import Path

import typer
from rich.console import Console

from lookervault.exceptions import StorageError
from lookervault.storage.models import ContentType
from lookervault.storage.repository import SQLiteContentRepository
from lookervault.storage.serializer import MsgpackSerializer

logger = logging.getLogger(__name__)


def run(
    db: str = "looker.db",
    content_type: str | None = None,
    compare_live: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> None:
    """Verify integrity of extracted content.

    Args:
        db: Database path to verify
        content_type: Specific content type to verify (default: all)
        compare_live: Compare with current Looker state
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
        # Check if database exists
        db_path = Path(db)
        if not db_path.exists():
            console.print(f"[red]✗ Database not found: {db}[/red]")
            console.print("Run 'lookervault extract' first to create a backup")
            raise typer.Exit(1)

        # Create repository and serializer
        repository = SQLiteContentRepository(db_path=db)
        serializer = MsgpackSerializer()

        # Parse content types to verify
        types_to_verify = _parse_content_types(content_type)

        console.print(f"[cyan]Verifying content in {db}...[/cyan]\n")

        # Verification results
        total_items = 0
        valid_items = 0
        invalid_items = 0
        errors_by_type: dict[str, list[str]] = {}

        for ct in types_to_verify:
            type_name = ContentType(ct).name.lower()
            console.print(f"Checking {type_name}...", end=" ")

            # Get all items of this type
            items = repository.list_content(content_type=ct, include_deleted=False)
            type_valid = 0
            type_invalid = 0

            for item in items:
                total_items += 1

                # Verify deserialization
                try:
                    serializer.deserialize(item.content_data)
                    type_valid += 1
                    valid_items += 1
                except Exception as e:
                    type_invalid += 1
                    invalid_items += 1
                    error_msg = f"{item.id}: {str(e)}"
                    errors_by_type.setdefault(type_name, []).append(error_msg)

                # Verify content size matches
                if item.content_size != len(item.content_data):
                    type_invalid += 1
                    invalid_items += 1
                    error_msg = f"{item.id}: size mismatch ({item.content_size} vs {len(item.content_data)})"
                    errors_by_type.setdefault(type_name, []).append(error_msg)

            if type_invalid == 0:
                console.print(f"[green]✓ {type_valid} valid[/green]")
            else:
                console.print(f"[yellow]⚠ {type_valid} valid, {type_invalid} errors[/yellow]")

        # Display summary
        console.print()
        if invalid_items == 0:
            console.print("[green]✓ All content verified successfully![/green]")
            console.print(f"  Total items: {total_items}")
            console.print("  No corruption detected")
        else:
            console.print("[yellow]⚠ Verification completed with errors[/yellow]")
            console.print(f"  Total items: {total_items}")
            console.print(f"  Valid: {valid_items}")
            console.print(f"  Invalid: {invalid_items}")

            # Show errors
            if errors_by_type:
                console.print("\n[yellow]Errors found:[/yellow]")
                for type_name, errors in errors_by_type.items():
                    console.print(f"\n{type_name}:")
                    for error in errors[:5]:  # Show first 5 errors per type
                        console.print(f"  - {error}")
                    if len(errors) > 5:
                        console.print(f"  ... and {len(errors) - 5} more errors")

        # Live comparison if requested
        if compare_live:
            console.print("\n[cyan]Comparing with live Looker instance...[/cyan]")
            # This would require loading config and comparing
            console.print("[yellow]Live comparison not yet implemented[/yellow]")

        # Clean exit
        repository.close()
        exit_code = 0 if invalid_items == 0 else 1
        raise typer.Exit(exit_code)

    except typer.Exit:
        raise
    except StorageError as e:
        console.print(f"[red]Storage error: {e}[/red]")
        raise typer.Exit(1) from None
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
        logger.exception("Unexpected error during verification")
        raise typer.Exit(1) from None


def _parse_content_types(types_str: str | None) -> list[int]:
    """Parse content type string.

    Args:
        types_str: Content type name or None for all

    Returns:
        List of ContentType enum values
    """
    if not types_str:
        # Default to all content types
        return [ct.value for ct in ContentType]

    # Parse single type
    type_name = types_str.strip().upper()

    # Remove plural 's' if present
    if type_name.endswith("S") and type_name != "SCHEDULES":
        type_name = type_name[:-1]

    # Special case mappings
    if type_name == "SCHEDULE":
        type_name = "SCHEDULED_PLAN"

    try:
        content_type = ContentType[type_name]
        return [content_type.value]
    except KeyError:
        available = ", ".join(ct.name.lower() for ct in ContentType)
        raise typer.BadParameter(
            f"Invalid content type: {types_str}. Available types: {available}"
        ) from None
