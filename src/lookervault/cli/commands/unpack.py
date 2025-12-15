"""Unpack command implementation for extracting Looker content from SQLite to YAML."""

import json
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from lookervault.export.metadata import MetadataManager
from lookervault.export.unpacker import ContentUnpacker
from lookervault.export.yaml_serializer import YamlSerializer
from lookervault.storage.models import ContentType
from lookervault.storage.repository import SQLiteContentRepository


def validate_content_types(value: str | None) -> list[str]:
    """
    Validate and parse content types input.

    Args:
        value (Optional[str]): Comma-separated content types.

    Returns:
        List[str]: Validated list of uppercase content types.

    Raises:
        typer.BadParameter: If invalid content types are provided.
    """
    if value is None:
        return []

    valid_content_types = {
        "DASHBOARD",
        "LOOK",
        "USER",
        "GROUP",
        "FOLDER",
        "BOARD",
        "ROLE",
        "LOOKML_MODEL",
        "EXPLORE",
        "PERMISSION_SET",
        "MODEL_SET",
        "SCHEDULED_PLAN",
    }

    try:
        content_types = [ct.upper().strip() for ct in value.split(",")]
    except Exception:
        raise typer.BadParameter("Invalid content types format. Use comma-separated values.")

    # Validate each content type
    invalid_types = set(content_types) - valid_content_types
    if invalid_types:
        raise typer.BadParameter(
            f"Invalid content types: {', '.join(invalid_types)}. "
            f"Valid types are: {', '.join(valid_content_types)}"
        )

    return content_types


def run(
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory to write exported YAML files"),
    ],
    db_path: Annotated[
        str,
        typer.Option("--db-path", help="Path to SQLite database to export from"),
    ] = "looker.db",
    strategy: Annotated[
        str,
        typer.Option("--strategy", help="Export strategy: 'full' or 'folder'"),
    ] = "full",
    content_types: Annotated[
        str | None,
        typer.Option("--content-types", help="Comma-separated list of content types to export"),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="Overwrite existing files in output directory"),
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
    """Unpack Looker content from database to YAML files."""
    console = Console()

    try:
        # Validate output directory
        if output_dir.exists() and not overwrite:
            console.print(f"[red]Error: Output directory '{output_dir}' already exists[/red]")
            raise typer.Exit(code=2)

        # Validate content types
        parsed_content_types = validate_content_types(content_types)

        # Initialize repository and serializer
        db_path_obj = Path(db_path)
        if not db_path_obj.exists():
            console.print(f"[red]Error: Database file not found: {db_path}[/red]")
            raise typer.Exit(code=1)

        repository = SQLiteContentRepository(db_path=str(db_path_obj))
        yaml_serializer = YamlSerializer()
        metadata_manager = MetadataManager()

        # Create unpacker
        unpacker = ContentUnpacker(
            repository=repository,
            yaml_serializer=yaml_serializer,
            metadata_manager=metadata_manager,
        )

        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)

        # Perform unpacking based on strategy
        if strategy == "folder":
            # Validate folders presence for folder strategy
            folder_count = len(repository.list_content(content_type=ContentType.FOLDER))
            if folder_count == 0:
                console.print(
                    "[red]Error: No folders found in database. 'folder' strategy requires folders.[/red]"
                )
                raise typer.Exit(code=4)

            result = unpacker.unpack_folder(
                db_path=db_path_obj,
                output_dir=output_dir,
                content_types=parsed_content_types,
            )
        else:
            result = unpacker.unpack_full(
                db_path=db_path_obj,
                output_dir=output_dir,
                content_types=parsed_content_types,
            )

        # Output results
        if json_output:
            # JSON output format from cli-contracts.yaml with folder strategy support
            export_summary = {
                "status": "success",
                "strategy": strategy,
                "output_dir": str(output_dir),
                "total_items": result["total_items"],
                "content_type_counts": result["content_type_counts"],
                "metadata_file": str(output_dir / "metadata.json"),
            }

            # For folder strategy, add folder map summary
            if strategy == "folder":
                metadata_file = output_dir / "metadata.json"
                with metadata_file.open() as f:
                    metadata = json.load(f)
                    export_summary["folder_map_summary"] = {
                        "total_folders": len(metadata.get("folder_map", {})),
                        "folders_with_content": sum(
                            1
                            for folder in metadata.get("folder_map", {}).values()
                            if folder.get("dashboard_count", 0) > 0
                            or folder.get("look_count", 0) > 0
                        ),
                    }

            console.print(export_summary)
        else:
            # Human-readable output
            console.print(f"Unpacking Looker content from {db_path}...")
            console.print(f"Strategy: {strategy}")
            console.print(f"Output directory: {output_dir}\n")

            for content_type, count in result["content_type_counts"].items():
                console.print(f"{content_type:<15}: {count} items")

            console.print(f"\nTotal: {result['total_items']} items")
            console.print(f"Metadata written to {output_dir}/metadata.json")

        sys.exit(0)

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        sys.exit(1)
