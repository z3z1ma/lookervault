"""Pack CLI command implementation for importing YAML content into SQLite database."""

import json
import logging
import sys
import time
from pathlib import Path
from typing import Annotated

import typer

from lookervault.cli.rich_logging import configure_rich_logging, console, print_error
from lookervault.export.metadata import MetadataManager
from lookervault.export.packer import ContentPacker
from lookervault.export.validator import YamlValidator
from lookervault.export.yaml_serializer import YamlSerializer
from lookervault.storage.repository import SQLiteContentRepository

# Exit codes matching cli-contracts.yaml
EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_SCHEMA_MISMATCH = 3
EXIT_TRANSACTION_FAILED = 5


def run(
    input_dir: Annotated[
        Path,
        typer.Option("--input-dir", help="Directory containing exported YAML files"),
    ],
    db_path: Annotated[
        str,
        typer.Option("--db-path", help="Path to SQLite database to write/update"),
    ] = "looker.db",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Validate without making database changes"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Delete database items for missing YAML files. Use with caution - deleted items cannot be recovered without a backup.",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output results in JSON format"),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable verbose logging"),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable debug logging"),
    ] = False,
) -> None:
    """Pack exported YAML files back into a Looker database.

    This command imports YAML files (previously exported with `lookervault unpack`)
    back into the SQLite database, performing validation, query remapping, and
    content updates.

    Usage Examples:

        # Normal mode: Validate and import with full validation
        lookervault pack --input-dir export/

        # Preview changes without modifying the database
        lookervault pack --input-dir export/ --dry-run

        # Force mode: Delete database items for missing YAML files
        # Use this when you've deleted YAML files and want the database to match
        lookervault pack --input-dir export/ --force

    Normal Mode (default):
        - Validates all YAML files for syntax and schema correctness
        - Performs Looker SDK validation to ensure content is valid
        - Creates new database entries for new items
        - Updates existing entries for modified items
        - Leaves unmodified items unchanged
        - Tracks query modifications and creates new query objects as needed
        - Does NOT delete database items for missing YAML files

    Force Mode (--force):
        - Performs all normal mode validations
        - Additionally DELETES database items when corresponding YAML files are missing
        - Use this to synchronize the database with a manually pruned YAML export
        - WARNING: Deleted items cannot be recovered unless you have a database backup

    When to use --force:
        - After manually deleting YAML files from the export directory
        - When you want to remove content from the database by deleting its YAML file
        - To keep the database synchronized with a curated subset of exported content
        - During selective import workflows where you only want specific items

    When NOT to use --force:
        - For normal import operations where you want to preserve all database content
        - When the YAML export directory is incomplete or partially corrupted
        - If you're unsure whether missing YAML files represent intentional deletions

    Workflow Recommendation:
        1. Always run with --dry-run first to preview changes
        2. Review the output, especially "Missing files" count
        3. If missing files are expected, run again with --force
        4. If missing files are unexpected, investigate before proceeding

    Exit Codes:
        0: Successful packing
        1: General error
        3: Schema version mismatch
        5: Database transaction failed
    """
    # Configure logging
    log_level = logging.DEBUG if debug else (logging.INFO if verbose else logging.WARNING)
    configure_rich_logging(level=log_level)

    start_time = time.time()
    logger = logging.getLogger(__name__)

    try:
        input_path = Path(input_dir).resolve()

        # Validate input directory exists
        if not input_path.is_dir():
            if not json_output:
                console.print(f"[red]✗ Input directory not found: {input_dir}[/red]")
            else:
                error_output = {
                    "status": "error",
                    "error_type": "NotFoundError",
                    "error_message": f"Input directory not found: {input_dir}",
                }
                console.print(json.dumps(error_output, indent=2))
            sys.exit(EXIT_GENERAL_ERROR)

        # Create repository
        repository = SQLiteContentRepository(db_path=db_path)

        # Create YAML serializer and validator
        yaml_serializer = YamlSerializer()
        validator = YamlValidator()
        metadata_manager = MetadataManager()

        # Create content packer
        packer = ContentPacker(
            repository=repository,
            yaml_serializer=yaml_serializer,
            validator=validator,
        )

        # Check if metadata.json exists
        metadata_path = input_path / "metadata.json"
        if not metadata_path.exists():
            if not json_output:
                console.print("[red]✗ metadata.json not found in export directory[/red]")
            else:
                error_output = {
                    "status": "error",
                    "error_type": "MetadataMissing",
                    "error_message": "metadata.json not found in export directory",
                }
                console.print(json.dumps(error_output, indent=2))
            sys.exit(EXIT_GENERAL_ERROR)

        # Load metadata for display purposes
        metadata = metadata_manager.load_metadata(input_path)

        # Run packing operation (progress bar is handled internally)
        summary = packer.pack(
            input_dir=input_path,
            dry_run=dry_run,
            force=force,  # T073 - pass force flag to handle missing files
        )

        # Compute duration
        duration = time.time() - start_time

        # Output based on format
        if not json_output:
            console.print("\n[bold green]✓ Pack Completed Successfully[/bold green]")
            console.print(f"  Input Directory: [cyan]{input_dir}[/cyan]")
            console.print(f"  Output Database: [cyan]{db_path}[/cyan]")
            console.print(f"  Strategy: [cyan]{metadata.strategy}[/cyan]")
            console.print("\nModification Summary:")
            console.print(f"  Created items   : {summary.created}")
            console.print(f"  Updated items   : {summary.updated}")
            console.print(f"  Unchanged items : {summary.unchanged}")
            console.print(f"  Deleted items   : {summary.deleted}")  # T073
            console.print(f"  Missing files   : {len(summary.missing_files)}")  # T073
            console.print(f"  New queries     : {summary.new_queries_created}")
            console.print(f"  Errors          : {len(summary.errors)}")
            console.print(f"\nPack completed in {duration:.1f}s")
        else:
            output = {
                "status": "success",
                "input_dir": input_dir,
                "db_path": db_path,
                "strategy": metadata.strategy,
                "total_items": metadata.total_items,
                "modifications": {
                    "created_items": summary.created,
                    "updated_items": summary.updated,
                    "unchanged_items": summary.unchanged,
                    "deleted_items": summary.deleted,  # T073
                    "missing_files": len(summary.missing_files),  # T073
                    "new_queries": summary.new_queries_created,
                },
                "errors": len(summary.errors),
                "duration_seconds": duration,
            }
            console.print(json.dumps(output, indent=2))

        # Handle errors
        if len(summary.errors) > 0:
            sys.exit(EXIT_GENERAL_ERROR)

        sys.exit(EXIT_SUCCESS)

    except Exception as e:
        if not json_output:
            print_error(f"Unexpected error during pack: {e}")
        else:
            error_output = {
                "status": "error",
                "error_type": "UnexpectedError",
                "error_message": str(e),
            }
            console.print(json.dumps(error_output, indent=2))
        logger.exception("Unexpected error during pack operation")
        sys.exit(EXIT_GENERAL_ERROR)
