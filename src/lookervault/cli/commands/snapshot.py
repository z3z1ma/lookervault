"""CLI commands for snapshot operations."""

import logging
import re
from pathlib import Path

import typer

from lookervault.cli.rich_logging import configure_rich_logging, console, print_error
from lookervault.config.loader import load_config
from lookervault.exceptions import ConfigError
from lookervault.snapshot.uploader import upload_snapshot

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="snapshot",
    help="Cloud snapshot management commands",
    no_args_is_help=True,
)

# Exit codes
EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_VALIDATION_ERROR = 2


@app.command()
def upload(
    source: str = typer.Option("./looker.db", help="Path to local database file"),
    name: str | None = typer.Option(
        None, help="Custom snapshot name prefix (e.g., 'pre-migration', 'test-run')"
    ),
    compress: bool = typer.Option(True, help="Enable gzip compression"),
    compression_level: int = typer.Option(6, help="Gzip compression level (1-9)"),
    dry_run: bool = typer.Option(False, help="Preview upload without executing"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
    config: Path | None = typer.Option(None, help="Path to config file"),
    verbose: bool = typer.Option(False, help="Enable verbose logging"),
    quiet: bool = typer.Option(False, help="Suppress all non-error output"),
) -> None:
    """Upload local database snapshot to Google Cloud Storage.

    This command uploads your local Looker database snapshot to Google Cloud Storage
    with optional gzip compression and automatic integrity verification using CRC32C
    checksums.

    Examples:
        # Upload with default settings
        lookervault snapshot upload

        # Upload with custom name for context
        lookervault snapshot upload --name pre-migration
        # Creates: pre-migration-2025-12-14T12-00-00.db.gz

        # Upload specific file with maximum compression
        lookervault snapshot upload --source /path/to/backup.db --compression-level 9

        # Preview upload (dry run)
        lookervault snapshot upload --dry-run

        # Upload with JSON output (for scripting)
        lookervault snapshot upload --json

    Exit Codes:
        0: Upload successful
        1: Upload failed (network error, authentication error, etc.)
        2: Validation error (invalid source path, configuration error)
    """
    # Configure logging
    if quiet:
        log_level = logging.ERROR
    elif verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    configure_rich_logging(log_level)

    try:
        # Load configuration
        try:
            cfg = load_config(config)
        except ConfigError as e:
            print_error(f"Configuration error: {e}")
            raise typer.Exit(EXIT_VALIDATION_ERROR)

        # Validate snapshot configuration exists
        if not cfg.snapshot:
            print_error(
                "Snapshot configuration not found in lookervault.toml\n\n"
                "Add snapshot configuration:\n"
                "[snapshot]\n"
                'bucket_name = "lookervault-backups"\n'
                'region = "us-central1"\n'
            )
            raise typer.Exit(EXIT_VALIDATION_ERROR)

        # Validate source path
        source_path = Path(source).expanduser()
        if not source_path.exists():
            print_error(f"Source file not found: {source_path}")
            raise typer.Exit(EXIT_VALIDATION_ERROR)

        # Validate custom snapshot name if provided
        if name:
            # Name must match pattern: lowercase letters, digits, underscores, hyphens
            if not re.match(r"^[a-z0-9_-]+$", name):
                print_error(
                    f"Invalid snapshot name: '{name}'\n"
                    "Name must contain only lowercase letters, digits, underscores, and hyphens"
                )
                raise typer.Exit(EXIT_VALIDATION_ERROR)

        # Override compression settings and snapshot name if provided
        provider_config = cfg.snapshot.provider.model_copy()
        provider_config.compression_enabled = compress
        provider_config.compression_level = compression_level
        if name:
            provider_config.filename_prefix = name

        # Perform upload
        try:
            if dry_run and not json_output:
                console.print("[yellow][DRY RUN] Preview mode - no actual upload[/yellow]")
                console.print(f"Source: {source_path}")
                console.print(
                    f"Bucket: gs://{provider_config.bucket_name}/{provider_config.prefix}"
                )
                console.print(
                    f"Compression: {'Enabled' if compress else 'Disabled'} (level {compression_level})"
                )
                console.print()

            metadata = upload_snapshot(
                provider_config,
                source_path,
                dry_run=dry_run,
                show_progress=not json_output and not quiet,
            )

            # Output results
            if json_output:
                output = {
                    "success": True,
                    "snapshot": {
                        "filename": metadata.filename,
                        "timestamp": metadata.timestamp.isoformat(),
                        "size_bytes": metadata.size_bytes,
                        "size_mb": metadata.size_mb,
                        "crc32c": metadata.crc32c,
                        "gcs_path": metadata.gcs_path,
                        "compression_ratio": (
                            1 - (metadata.size_bytes / source_path.stat().st_size)
                            if metadata.content_encoding == "gzip"
                            else None
                        ),
                    },
                    "dry_run": dry_run,
                }
                console.print_json(data=output)
            elif not quiet:
                console.print()
                console.print("[bold green]✓[/bold green] Upload complete!")
                console.print(f"  Snapshot: {metadata.filename}")
                console.print(f"  Size: {metadata.size_bytes:,} bytes ({metadata.size_mb} MB)")

                if metadata.content_encoding == "gzip":
                    original_size = source_path.stat().st_size
                    reduction = (1 - metadata.size_bytes / original_size) * 100
                    console.print(f"  Compressed: {reduction:.1f}% reduction")

                console.print(f"  CRC32C: {metadata.crc32c}")
                console.print(f"  Location: {metadata.gcs_path}")

                if dry_run:
                    console.print()
                    console.print("[yellow]This was a dry run. No files were uploaded.[/yellow]")

            raise typer.Exit(EXIT_SUCCESS)

        except typer.Exit:
            # Re-raise exit exceptions (don't catch our own exits!)
            raise

        except FileNotFoundError as e:
            print_error(f"File not found: {e}")
            raise typer.Exit(EXIT_VALIDATION_ERROR)

        except RuntimeError as e:
            # Authentication or bucket access errors
            print_error(str(e))
            raise typer.Exit(EXIT_GENERAL_ERROR)

        except (OSError, ValueError) as e:
            # Compression, upload, or verification errors
            print_error(f"Upload failed: {e}")
            raise typer.Exit(EXIT_GENERAL_ERROR)

        except Exception as e:
            logger.exception("Unexpected error during upload")
            print_error(f"Unexpected error: {e}")
            raise typer.Exit(EXIT_GENERAL_ERROR)

    except typer.Exit:
        raise
    except Exception as e:
        logger.exception("Fatal error")
        print_error(f"Fatal error: {e}")
        raise typer.Exit(EXIT_GENERAL_ERROR)


@app.command()
def list(
    limit: int | None = typer.Option(None, help="Maximum number of snapshots to display"),
    filter: str | None = typer.Option(None, help="Filter snapshots by date range"),
    verbose_mode: bool = typer.Option(
        False, "--verbose-output", "-V", help="Show detailed metadata for each snapshot"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
    no_cache: bool = typer.Option(False, help="Skip local cache, fetch fresh data"),
    config: Path | None = typer.Option(None, help="Path to config file"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Enable verbose logging"),
    quiet: bool = typer.Option(False, help="Suppress all non-error output"),
) -> None:
    """List available snapshots in Google Cloud Storage.

    This command lists all snapshots in the configured GCS bucket, sorted by
    creation time (newest first) with sequential indices for easy reference.

    Examples:
        # List all snapshots (uses cache if available)
        lookervault snapshot list

        # List 10 most recent snapshots
        lookervault snapshot list --limit 10

        # List snapshots from December 2025
        lookervault snapshot list --filter "2025-12"

        # List with detailed metadata
        lookervault snapshot list --verbose

        # List with JSON output (for scripting)
        lookervault snapshot list --json

    Exit Codes:
        0: List successful
        1: List failed (network error, authentication error, etc.)
        2: No snapshots found or validation error
    """
    # Configure logging
    if quiet:
        log_level = logging.ERROR
    elif verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    configure_rich_logging(log_level)

    try:
        # Load configuration
        try:
            cfg = load_config(config)
        except ConfigError as e:
            print_error(f"Configuration error: {e}")
            raise typer.Exit(EXIT_VALIDATION_ERROR)

        # Validate snapshot configuration exists
        if not cfg.snapshot:
            print_error(
                "Snapshot configuration not found in lookervault.toml\n\n"
                "Add snapshot configuration:\n"
                "[snapshot]\n"
                'bucket_name = "lookervault-backups"\n'
                'region = "us-central1"\n'
            )
            raise typer.Exit(EXIT_VALIDATION_ERROR)

        snapshot_config = cfg.snapshot
        provider = snapshot_config.provider

        # Import list functions (lazy import to avoid circular dependencies)
        from lookervault.snapshot.client import create_storage_client, validate_bucket_access
        from lookervault.snapshot.lister import filter_by_date_range, list_snapshots

        try:
            # Create GCS client
            client = create_storage_client(project_id=provider.project_id)

            # Validate bucket access
            validate_bucket_access(client, provider.bucket_name)

            # List snapshots
            use_cache = not no_cache
            cache_ttl = snapshot_config.cache_ttl_minutes if use_cache else 0

            snapshots = list_snapshots(
                client=client,
                bucket_name=provider.bucket_name,
                prefix=provider.prefix,
                use_cache=use_cache,
                cache_ttl_minutes=cache_ttl,
            )

            # Apply date filter if specified
            if filter:
                try:
                    snapshots = filter_by_date_range(snapshots, filter)
                except ValueError as e:
                    print_error(str(e))
                    raise typer.Exit(EXIT_VALIDATION_ERROR)

            # Apply limit if specified
            if limit is not None and limit > 0:
                snapshots = snapshots[:limit]

            # No snapshots found
            if not snapshots:
                if json_output:
                    output = {"total_count": 0, "snapshots": []}
                    console.print_json(data=output)
                elif not quiet:
                    console.print("[yellow]No snapshots found.[/yellow]")
                    console.print(
                        "\nRun [cyan]lookervault snapshot upload[/cyan] to create a snapshot."
                    )
                raise typer.Exit(EXIT_SUCCESS)

            # JSON output
            if json_output:
                output = {
                    "total_count": len(snapshots),
                    "snapshots": [s.model_dump(mode="json") for s in snapshots],
                }
                console.print_json(data=output)
                raise typer.Exit(EXIT_SUCCESS)

            # Human-readable output
            if not quiet:
                _display_snapshots_table(snapshots, verbose_mode)
            raise typer.Exit(EXIT_SUCCESS)

        except typer.Exit:
            # Re-raise exit exceptions (don't catch our own exits!)
            raise

        except RuntimeError as e:
            # Authentication or bucket access errors
            print_error(str(e))
            raise typer.Exit(EXIT_GENERAL_ERROR)

        except Exception as e:
            logger.exception("Unexpected error during list operation")
            print_error(f"Unexpected error: {e}")
            raise typer.Exit(EXIT_GENERAL_ERROR)

    except typer.Exit:
        raise
    except Exception as e:
        logger.exception("Fatal error")
        print_error(f"Fatal error: {e}")
        raise typer.Exit(EXIT_GENERAL_ERROR)


@app.command()
def download(
    snapshot_ref: str | None = typer.Argument(
        "1", help="Snapshot reference (index or timestamp). Optional if --interactive is used."
    ),
    output: str = typer.Option("./looker.db", help="Output path for downloaded file"),
    overwrite: bool = typer.Option(False, help="Overwrite existing file without confirmation"),
    verify_checksum: bool = typer.Option(True, help="Verify CRC32C checksum after download"),
    interactive: bool = typer.Option(False, help="Interactive snapshot selection with arrow keys"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
    config: Path | None = typer.Option(None, help="Path to config file"),
    verbose: bool = typer.Option(False, help="Enable verbose logging"),
    quiet: bool = typer.Option(False, help="Suppress all non-error output"),
) -> None:
    """Download snapshot from Google Cloud Storage to local file.

    This command downloads a specific snapshot from Google Cloud Storage to your local
    machine with automatic decompression and integrity verification using CRC32C checksums.

    SNAPSHOT_REF can be either:
        - Sequential index (e.g., "1" for most recent, "2" for second-most recent)
        - Timestamp in ISO format (e.g., "2025-12-14T10:30:00")
        - Omitted if using --interactive flag for menu-based selection

    Examples:
        # Download most recent snapshot
        lookervault snapshot download 1

        # Download to specific location
        lookervault snapshot download 1 --output /path/to/restored.db

        # Download by timestamp
        lookervault snapshot download 2025-12-14T10:30:00

        # Interactive menu selection (arrow keys)
        lookervault snapshot download --interactive

        # Download without checksum verification (faster but risky)
        lookervault snapshot download 1 --verify-checksum=false

        # Download with JSON output (for scripting)
        lookervault snapshot download 1 --json

    Exit Codes:
        0: Download successful
        1: Download failed (network error, authentication error, etc.)
        2: Validation error (invalid snapshot reference, file exists, etc.)
    """
    # Configure logging
    if quiet:
        log_level = logging.ERROR
    elif verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    configure_rich_logging(log_level)

    try:
        # Load configuration
        try:
            cfg = load_config(config)
        except ConfigError as e:
            print_error(f"Configuration error: {e}")
            raise typer.Exit(EXIT_VALIDATION_ERROR)

        # Validate snapshot configuration exists
        if not cfg.snapshot:
            print_error(
                "Snapshot configuration not found in lookervault.toml\n\n"
                "Add snapshot configuration:\n"
                "[snapshot]\n"
                'bucket_name = "lookervault-backups"\n'
                'region = "us-central1"\n'
            )
            raise typer.Exit(EXIT_VALIDATION_ERROR)

        snapshot_config = cfg.snapshot
        provider = snapshot_config.provider

        # Import download functions (lazy import to avoid circular dependencies)
        from datetime import datetime

        from lookervault.snapshot.client import create_storage_client, validate_bucket_access
        from lookervault.snapshot.downloader import download_snapshot
        from lookervault.snapshot.lister import (
            get_snapshot_by_index,
            get_snapshot_by_timestamp,
            list_snapshots,
        )

        try:
            # Create GCS client
            client = create_storage_client(project_id=provider.project_id)

            # Validate bucket access
            validate_bucket_access(client, provider.bucket_name)

            # Handle interactive mode
            if interactive:
                if json_output:
                    print_error("Interactive mode cannot be used with --json output")
                    raise typer.Exit(EXIT_VALIDATION_ERROR)

                if snapshot_ref:
                    print_error(
                        "Cannot specify snapshot reference when using --interactive mode.\n"
                        "Use either SNAPSHOT_REF or --interactive, not both."
                    )
                    raise typer.Exit(EXIT_VALIDATION_ERROR)

                # Import interactive UI function
                from lookervault.snapshot.ui import interactive_snapshot_picker

                # List all snapshots
                snapshots = list_snapshots(
                    client=client,
                    bucket_name=provider.bucket_name,
                    prefix=provider.prefix,
                    use_cache=True,
                    cache_ttl_minutes=snapshot_config.cache_ttl_minutes,
                )

                if not snapshots:
                    console.print("[yellow]No snapshots available to select.[/yellow]")
                    console.print(
                        "\nRun [cyan]lookervault snapshot upload[/cyan] to create a snapshot."
                    )
                    raise typer.Exit(EXIT_SUCCESS)

                # Launch interactive picker
                try:
                    snapshot = interactive_snapshot_picker(
                        snapshots, title="Download Snapshot", allow_cancel=True
                    )
                except RuntimeError as e:
                    # Terminal doesn't support interactive mode
                    print_error(str(e))
                    raise typer.Exit(EXIT_VALIDATION_ERROR)

                # User cancelled selection
                if snapshot is None:
                    raise typer.Exit(EXIT_SUCCESS)

            # Parse snapshot reference (index or timestamp)
            elif snapshot_ref:
                snapshot = None
                try:
                    # Try parsing as integer index first
                    index = int(snapshot_ref)
                    snapshot = get_snapshot_by_index(
                        client=client,
                        bucket_name=provider.bucket_name,
                        index=index,
                        prefix=provider.prefix,
                    )
                except ValueError:
                    # Not an integer, try parsing as timestamp
                    try:
                        # Try parsing as ISO timestamp
                        timestamp = datetime.fromisoformat(snapshot_ref.replace("Z", "+00:00"))
                        snapshot = get_snapshot_by_timestamp(
                            client=client,
                            bucket_name=provider.bucket_name,
                            timestamp=timestamp,
                            filename_prefix=provider.filename_prefix,
                            prefix=provider.prefix,
                        )
                    except ValueError:
                        # Invalid snapshot reference
                        print_error(
                            f"Invalid snapshot reference: '{snapshot_ref}'\n\n"
                            f"SNAPSHOT_REF must be either:\n"
                            f"  - Sequential index (e.g., '1', '2', '3')\n"
                            f"  - ISO timestamp (e.g., '2025-12-14T10:30:00')\n\n"
                            f"Run 'lookervault snapshot list' to see available snapshots."
                        )
                        raise typer.Exit(EXIT_VALIDATION_ERROR)

            # Neither interactive nor snapshot_ref provided
            else:
                print_error(
                    "Missing snapshot reference.\n\n"
                    "Usage:\n"
                    "  lookervault snapshot download SNAPSHOT_REF\n"
                    "  lookervault snapshot download --interactive\n\n"
                    "Run 'lookervault snapshot list' to see available snapshots."
                )
                raise typer.Exit(EXIT_VALIDATION_ERROR)

            # Validate output path
            output_path = Path(output).expanduser().resolve()

            # Check if output file exists
            if output_path.exists() and not overwrite:
                if json_output:
                    # JSON mode: fail immediately without prompt
                    print_error(
                        f"Output file exists: {output_path}\n\nUse --overwrite to replace it."
                    )
                    raise typer.Exit(EXIT_VALIDATION_ERROR)
                else:
                    # Interactive mode: ask for confirmation
                    confirmed = typer.confirm(
                        f"\nOutput file exists: {output_path}\n\nOverwrite it?",
                        default=False,
                    )
                    if not confirmed:
                        console.print("\n[yellow]Download cancelled.[/yellow]")
                        raise typer.Exit(EXIT_SUCCESS)

            # Create output directory if needed
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Download snapshot
            try:
                if not json_output and not quiet:
                    console.print(
                        f"\n[bold]Downloading snapshot {snapshot.sequential_index}[/bold]"
                    )
                    console.print(f"  Filename:  {snapshot.filename.split('/')[-1]}")
                    console.print(
                        f"  Size:      {snapshot.size_mb} MB ({snapshot.size_bytes:,} bytes)"
                    )
                    console.print(
                        f"  Created:   {snapshot.created.strftime('%Y-%m-%d %H:%M:%S')} UTC"
                    )
                    console.print()

                metadata = download_snapshot(
                    client=client,
                    snapshot=snapshot,
                    output_path=output_path,
                    verify_checksum=verify_checksum,
                    show_progress=not json_output and not quiet,
                )

                # Output results
                if json_output:
                    result = {
                        "success": True,
                        "snapshot": {
                            "index": snapshot.sequential_index,
                            "filename": snapshot.filename.split("/")[-1],
                            "timestamp": snapshot.timestamp.isoformat(),
                            "size_bytes": snapshot.size_bytes,
                        },
                        "download": metadata,
                    }
                    console.print_json(data=result)
                elif not quiet:
                    console.print()
                    console.print("[bold green]✓[/bold green] Download complete!")
                    console.print(f"  Saved to:  {metadata['filename']}")
                    console.print(f"  Size:      {metadata['size_bytes']:,} bytes")
                    console.print(f"  Time:      {metadata['download_time']:.1f} seconds")

                    if metadata["checksum_verified"]:
                        console.print("  [green]Checksum: Verified ✓[/green]")
                    else:
                        console.print("  [yellow]Checksum: Skipped[/yellow]")

                raise typer.Exit(EXIT_SUCCESS)

            except FileExistsError as e:
                print_error(str(e))
                raise typer.Exit(EXIT_VALIDATION_ERROR)

            except ValueError as e:
                # Checksum verification failure or invalid snapshot
                print_error(str(e))
                raise typer.Exit(EXIT_GENERAL_ERROR)

            except OSError as e:
                # Download or decompression errors
                print_error(f"Download failed: {e}")
                raise typer.Exit(EXIT_GENERAL_ERROR)

        except typer.Exit:
            # Re-raise exit exceptions (don't catch our own exits!)
            raise

        except RuntimeError as e:
            # Authentication or bucket access errors
            print_error(str(e))
            raise typer.Exit(EXIT_GENERAL_ERROR)

        except Exception as e:
            logger.exception("Unexpected error during download operation")
            print_error(f"Unexpected error: {e}")
            raise typer.Exit(EXIT_GENERAL_ERROR)

    except typer.Exit:
        raise
    except Exception as e:
        logger.exception("Fatal error")
        print_error(f"Fatal error: {e}")
        raise typer.Exit(EXIT_GENERAL_ERROR)


@app.command()
def delete(
    snapshot_ref: str = typer.Argument(..., help="Snapshot reference (index or timestamp)"),
    force: bool = typer.Option(False, help="Skip confirmation prompt"),
    dry_run: bool = typer.Option(False, help="Preview deletion without executing"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
    config: Path | None = typer.Option(None, help="Path to config file"),
    verbose: bool = typer.Option(False, help="Enable verbose logging"),
    quiet: bool = typer.Option(False, help="Suppress all non-error output"),
) -> None:
    """Delete snapshot from Google Cloud Storage.

    This command deletes a specific snapshot from Google Cloud Storage. The snapshot
    is moved to GCS's soft delete retention (7 days) before permanent deletion.

    SNAPSHOT_REF can be either:
        - Sequential index (e.g., "1" for most recent, "2" for second-most recent)
        - Timestamp in ISO format (e.g., "2025-12-14T10:30:00")

    Examples:
        # Preview deletion (dry run)
        lookervault snapshot delete 1 --dry-run

        # Delete most recent snapshot with confirmation
        lookervault snapshot delete 1

        # Delete by timestamp without confirmation
        lookervault snapshot delete 2025-12-14T10:30:00 --force

        # Delete with JSON output (for scripting)
        lookervault snapshot delete 1 --json --force

    Exit Codes:
        0: Deletion successful
        1: Deletion failed (network error, authentication error, etc.)
        2: Validation error (invalid snapshot reference, etc.)
    """
    # Configure logging
    if quiet:
        log_level = logging.ERROR
    elif verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    configure_rich_logging(log_level)

    try:
        # Load configuration
        try:
            cfg = load_config(config)
        except ConfigError as e:
            print_error(f"Configuration error: {e}")
            raise typer.Exit(EXIT_VALIDATION_ERROR)

        # Validate snapshot configuration exists
        if not cfg.snapshot:
            print_error(
                "Snapshot configuration not found in lookervault.toml\n\n"
                "Add snapshot configuration:\n"
                "[snapshot]\n"
                'bucket_name = "lookervault-backups"\n'
                'region = "us-central1"\n'
            )
            raise typer.Exit(EXIT_VALIDATION_ERROR)

        snapshot_config = cfg.snapshot
        provider = snapshot_config.provider

        # Import delete functions (lazy import to avoid circular dependencies)
        from datetime import datetime

        from lookervault.snapshot.client import create_storage_client, validate_bucket_access
        from lookervault.snapshot.lister import (
            get_snapshot_by_index,
            get_snapshot_by_timestamp,
        )
        from lookervault.snapshot.retention import AuditLogger, delete_snapshot

        try:
            # Create GCS client
            client = create_storage_client(project_id=provider.project_id)

            # Validate bucket access
            validate_bucket_access(client, provider.bucket_name)

            # Parse snapshot reference (index or timestamp)
            snapshot = None
            try:
                # Try parsing as integer index first
                index = int(snapshot_ref)
                snapshot = get_snapshot_by_index(
                    client=client,
                    bucket_name=provider.bucket_name,
                    index=index,
                    prefix=provider.prefix,
                )
            except ValueError:
                # Not an integer, try parsing as timestamp
                try:
                    # Try parsing as ISO timestamp
                    timestamp = datetime.fromisoformat(snapshot_ref.replace("Z", "+00:00"))
                    snapshot = get_snapshot_by_timestamp(
                        client=client,
                        bucket_name=provider.bucket_name,
                        timestamp=timestamp,
                        filename_prefix=provider.filename_prefix,
                        prefix=provider.prefix,
                    )
                except ValueError:
                    # Invalid snapshot reference
                    print_error(
                        f"Invalid snapshot reference: '{snapshot_ref}'\n\n"
                        f"SNAPSHOT_REF must be either:\n"
                        f"  - Sequential index (e.g., '1', '2', '3')\n"
                        f"  - ISO timestamp (e.g., '2025-12-14T10:30:00')\n\n"
                        f"Run 'lookervault snapshot list' to see available snapshots."
                    )
                    raise typer.Exit(EXIT_VALIDATION_ERROR)

            # Display snapshot metadata
            if not json_output and not quiet:
                console.print(f"\n[bold]Snapshot {snapshot.sequential_index}[/bold]")
                console.print("─" * 60)
                console.print(f"  Filename:   {snapshot.filename.split('/')[-1]}")
                console.print(
                    f"  Timestamp:  {snapshot.timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC"
                )
                console.print(
                    f"  Size:       {snapshot.size_mb} MB ({snapshot.size_bytes:,} bytes)"
                )
                console.print(f"  Age:        {_format_age(snapshot.age_days)}")
                console.print(f"  Location:   {snapshot.gcs_path}")
                console.print()

            # Dry run preview
            if dry_run:
                if json_output:
                    output = {
                        "success": True,
                        "snapshot": {
                            "index": snapshot.sequential_index,
                            "filename": snapshot.filename.split("/")[-1],
                            "timestamp": snapshot.timestamp.isoformat(),
                            "size_bytes": snapshot.size_bytes,
                        },
                        "dry_run": True,
                        "deleted": False,
                    }
                    console.print_json(data=output)
                elif not quiet:
                    console.print("[yellow][DRY RUN] Preview mode - no actual deletion[/yellow]")
                    console.print(
                        f"\nThis would delete snapshot {snapshot.sequential_index} "
                        f"({snapshot.size_mb} MB)"
                    )
                    console.print(
                        "\nTo execute deletion, run: "
                        f"[cyan]lookervault snapshot delete {snapshot_ref} [/cyan]"
                    )
                raise typer.Exit(EXIT_SUCCESS)

            # Confirmation prompt (unless --force or --json)
            if not force and not json_output:
                console.print()
                confirmed = typer.confirm(
                    f"Delete snapshot {snapshot.sequential_index} ({snapshot.size_mb} MB)?",
                    default=False,
                )
                if not confirmed:
                    console.print("\n[yellow]Deletion cancelled.[/yellow]")
                    raise typer.Exit(EXIT_SUCCESS)

            # Initialize audit logger
            audit_logger = AuditLogger(
                log_path=snapshot_config.audit_log_path,
                gcs_bucket=snapshot_config.audit_gcs_bucket,
            )

            # Execute deletion
            if not json_output and not quiet:
                console.print("\n[bold]Deleting snapshot...[/bold]")

            success = delete_snapshot(
                client=client,
                bucket_name=provider.bucket_name,
                snapshot=snapshot,
                audit_logger=audit_logger,
                reason="manual_deletion",
                dry_run=False,
            )

            # Output results
            if json_output:
                output = {
                    "success": success,
                    "snapshot": {
                        "index": snapshot.sequential_index,
                        "filename": snapshot.filename.split("/")[-1],
                        "timestamp": snapshot.timestamp.isoformat(),
                        "size_bytes": snapshot.size_bytes,
                    },
                    "dry_run": False,
                    "deleted": success,
                }
                console.print_json(data=output)
            elif not quiet:
                console.print()
                console.print("[bold green]✓[/bold green] Snapshot deleted successfully!")
                console.print(f"  Snapshot:    {snapshot.filename.split('/')[-1]}")
                console.print(f"  Size freed:  {snapshot.size_mb} MB")
                console.print()
                console.print(
                    "[dim]Note: GCS soft delete enabled. Snapshot can be recovered within 7 days.[/dim]"
                )
                console.print(
                    f"[dim]Run 'gcloud storage objects list --soft-deleted gs://{provider.bucket_name}/{provider.prefix}' to view.[/dim]"
                )
                console.print(f"\n[dim]Audit log: {snapshot_config.audit_log_path}[/dim]")

            raise typer.Exit(EXIT_SUCCESS)

        except typer.Exit:
            # Re-raise exit exceptions (don't catch our own exits!)
            raise

        except RuntimeError as e:
            # Deletion errors, authentication, or bucket access errors
            print_error(str(e))
            raise typer.Exit(EXIT_GENERAL_ERROR)

        except Exception as e:
            logger.exception("Unexpected error during delete operation")
            print_error(f"Unexpected error: {e}")
            raise typer.Exit(EXIT_GENERAL_ERROR)

    except typer.Exit:
        raise
    except Exception as e:
        logger.exception("Fatal error")
        print_error(f"Fatal error: {e}")
        raise typer.Exit(EXIT_GENERAL_ERROR)


@app.command()
def cleanup(
    dry_run: bool = typer.Option(True, help="Preview cleanup without executing"),
    force: bool = typer.Option(False, help="Execute cleanup without confirmation"),
    older_than: int | None = typer.Option(
        None, help="Override retention policy: delete snapshots older than N days"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
    config: Path | None = typer.Option(None, help="Path to config file"),
    verbose: bool = typer.Option(False, help="Enable verbose logging"),
    quiet: bool = typer.Option(False, help="Suppress all non-error output"),
) -> None:
    """Clean up old snapshots based on retention policy.

    This command automatically deletes old snapshots according to the configured retention
    policy (min_days, max_days, min_count). It provides preview mode by default and requires
    explicit confirmation before deleting snapshots.

    Retention Policy Logic:
        - Always protect snapshots newer than min_days
        - Always delete snapshots older than max_days (unless protected by min_count)
        - Always protect at least min_count most recent snapshots

    Examples:
        # Preview cleanup (dry run - default)
        lookervault snapshot cleanup

        # Preview with explicit dry-run flag
        lookervault snapshot cleanup --dry-run

        # Execute cleanup (requires confirmation)
        lookervault snapshot cleanup --dry-run=false

        # Execute cleanup without confirmation
        lookervault snapshot cleanup --dry-run=false --force

        # Override retention policy (delete snapshots older than 60 days)
        lookervault snapshot cleanup --older-than 60 --dry-run=false

        # JSON output for scripting
        lookervault snapshot cleanup --json

    Exit Codes:
        0: Cleanup successful or preview complete
        1: Cleanup failed (network error, authentication error, etc.)
        2: Validation error (safety check failed, configuration error)
    """
    # Configure logging
    if quiet:
        log_level = logging.ERROR
    elif verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    configure_rich_logging(log_level)

    try:
        # Load configuration
        try:
            cfg = load_config(config)
        except ConfigError as e:
            print_error(f"Configuration error: {e}")
            raise typer.Exit(EXIT_VALIDATION_ERROR)

        # Validate snapshot configuration exists
        if not cfg.snapshot:
            print_error(
                "Snapshot configuration not found in lookervault.toml\n\n"
                "Add snapshot configuration:\n"
                "[snapshot]\n"
                'bucket_name = "lookervault-backups"\n'
                'region = "us-central1"\n'
            )
            raise typer.Exit(EXIT_VALIDATION_ERROR)

        snapshot_config = cfg.snapshot
        provider = snapshot_config.provider
        retention_policy = snapshot_config.retention

        # Override max_days if --older-than specified
        if older_than is not None:
            if older_than < retention_policy.min_days:
                print_error(
                    f"--older-than ({older_than} days) cannot be less than "
                    f"min_days ({retention_policy.min_days} days)"
                )
                raise typer.Exit(EXIT_VALIDATION_ERROR)

            # Create modified retention policy
            retention_policy = retention_policy.model_copy()
            retention_policy.max_days = older_than

            if not json_output and not quiet:
                console.print(
                    f"[yellow]⚠ Overriding retention policy: max_days = {older_than} days[/yellow]"
                )

        # Import cleanup functions (lazy import to avoid circular dependencies)
        from lookervault.snapshot.client import create_storage_client, validate_bucket_access
        from lookervault.snapshot.lister import list_snapshots
        from lookervault.snapshot.retention import (
            AuditLogger,
            delete_old_snapshots,
            evaluate_retention_policy,
            preview_cleanup,
            validate_safety_threshold,
        )

        try:
            # Create GCS client
            client = create_storage_client(project_id=provider.project_id)

            # Validate bucket access
            validate_bucket_access(client, provider.bucket_name)

            # List all snapshots (use cache for preview, skip cache for actual cleanup)
            use_cache = dry_run  # Only use cache in dry-run mode
            cache_ttl = snapshot_config.cache_ttl_minutes if use_cache else 0

            snapshots = list_snapshots(
                client=client,
                bucket_name=provider.bucket_name,
                prefix=provider.prefix,
                use_cache=use_cache,
                cache_ttl_minutes=cache_ttl,
            )

            # No snapshots found
            if not snapshots:
                if json_output:
                    output = {
                        "total_snapshots": 0,
                        "protected_count": 0,
                        "deleted_count": 0,
                        "failed_count": 0,
                        "skipped_count": 0,
                        "size_freed_bytes": 0,
                        "dry_run": dry_run,
                    }
                    console.print_json(data=output)
                elif not quiet:
                    console.print("[yellow]No snapshots found. Nothing to clean up.[/yellow]")
                raise typer.Exit(EXIT_SUCCESS)

            # Evaluate retention policy
            evaluation = evaluate_retention_policy(snapshots, retention_policy)

            # Validate safety threshold
            try:
                validate_safety_threshold(
                    evaluation.snapshots_to_protect,
                    retention_policy.min_count,
                    force=force,
                )
            except ValueError as e:
                print_error(str(e))
                raise typer.Exit(EXIT_VALIDATION_ERROR)

            # Generate preview
            preview = preview_cleanup(evaluation, retention_policy)

            # Display preview (if not JSON output)
            if not json_output and not quiet:
                _display_cleanup_preview(
                    evaluation,
                    preview,
                    retention_policy,
                    dry_run,
                )

            # No snapshots to delete
            if preview["delete_count"] == 0:
                if json_output:
                    output = {
                        "total_snapshots": preview["total_snapshots"],
                        "protected_count": preview["protected_count"],
                        "deleted_count": 0,
                        "failed_count": 0,
                        "skipped_count": 0,
                        "size_freed_bytes": 0,
                        "dry_run": dry_run,
                    }
                    console.print_json(data=output)
                elif not quiet:
                    console.print(
                        "\n[green]✓[/green] No snapshots to delete. All snapshots are within retention policy."
                    )
                raise typer.Exit(EXIT_SUCCESS)

            # Dry run mode - exit after preview
            if dry_run:
                if json_output:
                    output = {
                        "total_snapshots": preview["total_snapshots"],
                        "protected_count": preview["protected_count"],
                        "deleted_count": preview["delete_count"],
                        "failed_count": 0,
                        "skipped_count": 0,
                        "size_freed_bytes": preview["size_to_free_bytes"],
                        "dry_run": True,
                    }
                    console.print_json(data=output)
                elif not quiet:
                    console.print()
                    console.print("[yellow]This was a dry run. No snapshots were deleted.[/yellow]")
                    console.print(
                        "\nTo execute cleanup, run: "
                        "[cyan]lookervault snapshot cleanup --dry-run=false[/cyan]"
                    )
                raise typer.Exit(EXIT_SUCCESS)

            # Confirmation prompt (unless --force or --json)
            if not force and not json_output:
                console.print()
                confirmed = typer.confirm(
                    f"Delete {preview['delete_count']} snapshots "
                    f"({preview['size_to_free_mb']} MB)?",
                    default=False,
                )
                if not confirmed:
                    console.print("\n[yellow]Cleanup cancelled.[/yellow]")
                    raise typer.Exit(EXIT_SUCCESS)

            # Execute cleanup
            if not json_output and not quiet:
                console.print("\n[bold]Executing cleanup...[/bold]")

            # Initialize audit logger
            audit_logger = AuditLogger(
                log_path=snapshot_config.audit_log_path,
                gcs_bucket=snapshot_config.audit_gcs_bucket,
            )

            # Delete old snapshots
            result = delete_old_snapshots(
                client=client,
                bucket_name=provider.bucket_name,
                snapshots_to_delete=evaluation.snapshots_to_delete,
                audit_logger=audit_logger,
                dry_run=False,  # Actually execute deletion
            )

            # Output results
            if json_output:
                output = {
                    "total_snapshots": preview["total_snapshots"],
                    "protected_count": preview["protected_count"],
                    "deleted_count": result.deleted,
                    "failed_count": result.failed,
                    "skipped_count": result.skipped,
                    "size_freed_bytes": result.size_freed_bytes,
                    "dry_run": False,
                }
                console.print_json(data=output)
            elif not quiet:
                console.print()
                console.print("[bold green]✓[/bold green] Cleanup complete!")
                console.print(f"  Deleted:     {result.deleted} snapshots")
                console.print(f"  Protected:   {preview['protected_count']} snapshots")

                if result.failed > 0:
                    console.print(f"  [red]Failed:      {result.failed} snapshots[/red]")

                if result.skipped > 0:
                    console.print(
                        f"  [yellow]Skipped:     {result.skipped} snapshots (protected)[/yellow]"
                    )

                size_freed_mb = round(result.size_freed_bytes / (1024 * 1024), 1)
                console.print(f"  Size freed:  {size_freed_mb} MB")

                console.print(f"\n[dim]Audit log: {snapshot_config.audit_log_path}[/dim]")

            raise typer.Exit(EXIT_SUCCESS)

        except typer.Exit:
            # Re-raise exit exceptions (don't catch our own exits!)
            raise

        except RuntimeError as e:
            # Authentication or bucket access errors
            print_error(str(e))
            raise typer.Exit(EXIT_GENERAL_ERROR)

        except Exception as e:
            logger.exception("Unexpected error during cleanup operation")
            print_error(f"Unexpected error: {e}")
            raise typer.Exit(EXIT_GENERAL_ERROR)

    except typer.Exit:
        raise
    except Exception as e:
        logger.exception("Fatal error")
        print_error(f"Fatal error: {e}")
        raise typer.Exit(EXIT_GENERAL_ERROR)


# Helper functions


def _display_snapshots_table(snapshots: list, verbose: bool) -> None:
    """
    Display snapshots in a Rich table.

    Args:
        snapshots: List of SnapshotMetadata
        verbose: Whether to show detailed metadata
    """
    from rich.table import Table

    if verbose:
        # Verbose mode: detailed output for each snapshot
        for snapshot in snapshots:
            console.print(
                f"\n[bold]Snapshot {snapshot.sequential_index} of {len(snapshots)}[/bold]"
            )
            console.print("─" * 60)
            console.print(f"  [cyan]Filename:[/cyan]   {snapshot.filename.split('/')[-1]}")
            console.print(
                f"  [cyan]Timestamp:[/cyan]  {snapshot.timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC"
            )
            console.print(
                f"  [cyan]Size:[/cyan]       {snapshot.size_mb} MB ({snapshot.size_bytes:,} bytes)"
            )
            console.print(f"  [cyan]CRC32C:[/cyan]     {snapshot.crc32c}")

            if snapshot.content_encoding:
                console.print(f"  [cyan]Encoding:[/cyan]   {snapshot.content_encoding}")

            if snapshot.tags:
                console.print(f"  [cyan]Tags:[/cyan]       {', '.join(snapshot.tags)}")

            console.print(f"  [cyan]Location:[/cyan]   {snapshot.gcs_path}")
            console.print(
                f"  [cyan]Created:[/cyan]    {snapshot.created.strftime('%Y-%m-%d %H:%M:%S')} UTC"
            )
            console.print(
                f"  [cyan]Updated:[/cyan]    {snapshot.updated.strftime('%Y-%m-%d %H:%M:%S')} UTC"
            )
            console.print(f"  [cyan]Age:[/cyan]        {_format_age(snapshot.age_days)}")

    else:
        # Compact table mode
        console.print(f"\n[bold]Available Snapshots ({len(snapshots)})[/bold]\n")

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Index", justify="right", style="cyan")
        table.add_column("Filename", style="white")
        table.add_column("Timestamp", style="dim")
        table.add_column("Size (MB)", justify="right", style="yellow")
        table.add_column("Age", style="magenta")

        for snapshot in snapshots:
            # Extract filename without directory prefix
            filename = snapshot.filename.split("/")[-1]

            # Format timestamp
            timestamp_str = snapshot.timestamp.strftime("%Y-%m-%d %H:%M:%S")

            # Format age
            age_str = _format_age(snapshot.age_days)

            table.add_row(
                str(snapshot.sequential_index),
                filename,
                timestamp_str,
                f"{snapshot.size_mb}",
                age_str,
            )

        console.print(table)
        console.print(
            "\n[dim]Use index number to download or restore "
            "(e.g., lookervault snapshot download 1)[/dim]"
        )


def _format_age(age_days: int) -> str:
    """
    Format age in human-readable format.

    Args:
        age_days: Age in days

    Returns:
        Formatted age string (e.g., "2 hours", "3 days", "2 months")
    """
    if age_days == 0:
        return "< 1 day"
    elif age_days == 1:
        return "1 day"
    elif age_days < 30:
        return f"{age_days} days"
    elif age_days < 365:
        months = age_days // 30
        return f"{months} month{'s' if months > 1 else ''}"
    else:
        years = age_days // 365
        return f"{years} year{'s' if years > 1 else ''}"


def _display_cleanup_preview(
    evaluation,
    preview: dict,
    retention_policy,
    dry_run: bool,
) -> None:
    """
    Display cleanup preview with retention policy details.

    Args:
        evaluation: RetentionEvaluation result
        preview: Preview statistics dictionary
        retention_policy: RetentionPolicy configuration
        dry_run: Whether this is a dry run
    """
    from rich.table import Table

    console.print()
    console.print("[bold]Retention Policy Cleanup Preview[/bold]")
    console.print("─" * 60)
    console.print(f"  Min retention:     {retention_policy.min_days} days")
    console.print(f"  Max retention:     {retention_policy.max_days} days")
    console.print(f"  Min backup count:  {retention_policy.min_count}")
    console.print()

    # Summary counts
    console.print(f"[bold]Total snapshots:[/bold]    {preview['total_snapshots']}")
    console.print(f"[green]Snapshots to protect:[/green] {preview['protected_count']}")
    console.print(f"[red]Snapshots to delete:[/red]  {preview['delete_count']}")
    console.print(f"[yellow]Size to free:[/yellow]        {preview['size_to_free_mb']} MB")
    console.print()

    # Show snapshots to delete in a table
    if preview["delete_count"] > 0:
        console.print("[bold red]Snapshots to Delete:[/bold red]")
        table = Table(show_header=True, header_style="bold red")
        table.add_column("Index", justify="right", style="red")
        table.add_column("Filename", style="white")
        table.add_column("Age", style="yellow")
        table.add_column("Size (MB)", justify="right", style="dim")

        for snapshot in evaluation.snapshots_to_delete[:10]:  # Show first 10
            filename = snapshot.filename.split("/")[-1]
            age_str = _format_age(snapshot.age_days)

            table.add_row(
                str(snapshot.sequential_index),
                filename,
                age_str,
                f"{snapshot.size_mb}",
            )

        console.print(table)

        if len(evaluation.snapshots_to_delete) > 10:
            remaining = len(evaluation.snapshots_to_delete) - 10
            console.print(f"[dim]... and {remaining} more snapshots[/dim]")

        console.print()

    # Show snapshots to protect (sample)
    if preview["protected_count"] > 0:
        console.print("[bold green]Protected Snapshots (sample):[/bold green]")
        table = Table(show_header=True, header_style="bold green")
        table.add_column("Index", justify="right", style="green")
        table.add_column("Filename", style="white")
        table.add_column("Age", style="yellow")
        table.add_column("Reason", style="dim")

        for snapshot in evaluation.snapshots_to_protect[:5]:  # Show first 5
            filename = snapshot.filename.split("/")[-1]
            age_str = _format_age(snapshot.age_days)
            reason = evaluation.protection_reasons.get(snapshot.filename, "unknown")

            # Shorten reason for display
            if len(reason) > 40:
                reason = reason[:37] + "..."

            table.add_row(
                str(snapshot.sequential_index),
                filename,
                age_str,
                reason,
            )

        console.print(table)

        if preview["protected_count"] > 5:
            remaining = preview["protected_count"] - 5
            console.print(f"[dim]... and {remaining} more protected snapshots[/dim]")

        console.print()
