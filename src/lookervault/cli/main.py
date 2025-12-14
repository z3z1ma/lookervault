"""Main Typer application for LookerVault CLI."""

from pathlib import Path
from typing import Annotated

import typer

from lookervault import __version__

app = typer.Typer(
    help="LookerVault - Backup and restore tool for Looker instances",
    add_completion=False,
    no_args_is_help=True,
)


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        typer.echo(f"LookerVault version {__version__}")
        raise typer.Exit(0)


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=version_callback,
            is_eager=True,
            help="Show version and exit",
        ),
    ] = False,
) -> None:
    """LookerVault CLI main callback."""
    pass


@app.command()
def check(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to configuration file"),
    ] = None,
    output: Annotated[
        str,
        typer.Option("--output", "-o", help='Output format: "table" or "json"'),
    ] = "table",
) -> None:
    """Perform readiness checks to validate installation and configuration."""
    from .commands import check as check_module

    check_module.run(config, output)


@app.command()
def info(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to configuration file"),
    ] = None,
    output: Annotated[
        str,
        typer.Option("--output", "-o", help='Output format: "table" or "json"'),
    ] = "table",
) -> None:
    """Display Looker instance information."""
    from .commands import info as info_module

    info_module.run(config, output)


@app.command()
def extract(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to configuration file"),
    ] = None,
    output: Annotated[
        str,
        typer.Option("--output", "-o", help='Output format: "table" or "json"'),
    ] = "table",
    db: Annotated[
        str,
        typer.Option("--db", help="Database path for storage"),
    ] = "looker.db",
    types: Annotated[
        str | None,
        typer.Option(
            "--types",
            "-t",
            help="Comma-separated content types to extract (e.g., 'dashboards,looks') or 'all' for everything. "
            "Valid types: dashboard, look, lookml_model, explore, folder, board, user, group, role, "
            "permission_set, model_set, scheduled_plan",
        ),
    ] = None,
    batch_size: Annotated[
        int,
        typer.Option("--batch-size", "-b", help="Items per batch for memory management"),
    ] = 100,
    resume: Annotated[
        bool,
        typer.Option("--resume", help="Resume incomplete extraction"),
    ] = True,
    incremental: Annotated[
        bool,
        typer.Option("--incremental", "-i", help="Extract only new/changed content"),
    ] = False,
    workers: Annotated[
        int,
        typer.Option(
            "--workers",
            "-w",
            min=1,
            max=50,
            help="Number of parallel worker threads (1-50, default: auto-detect based on CPU cores)",
        ),
    ] = 0,  # 0 = auto-detect in extract_module.run()
    rate_limit_per_minute: Annotated[
        int | None,
        typer.Option(
            "--rate-limit-per-minute",
            help="Max API requests per minute across all workers (default: 100)",
        ),
    ] = None,
    rate_limit_per_second: Annotated[
        int | None,
        typer.Option(
            "--rate-limit-per-second",
            help="Max API requests per second for burst handling (default: 10)",
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable verbose logging"),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable debug logging"),
    ] = False,
) -> None:
    """Extract all content from Looker instance to local database."""
    from .commands import extract as extract_module

    extract_module.run(
        config,
        output,
        db,
        types,
        batch_size,
        resume,
        incremental,
        workers,
        rate_limit_per_minute,
        rate_limit_per_second,
        verbose,
        debug,
    )


@app.command()
def verify(
    db: Annotated[
        str,
        typer.Option("--db", help="Database path to verify"),
    ] = "looker.db",
    content_type: Annotated[
        str | None,
        typer.Option("--type", "-t", help="Specific content type to verify"),
    ] = None,
    compare_live: Annotated[
        bool,
        typer.Option("--compare-live", help="Compare with current Looker state"),
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
    """Verify integrity of extracted content."""
    from .commands import verify as verify_module

    verify_module.run(db, content_type, compare_live, verbose, debug)


@app.command(name="list")
def list_content(
    content_type: Annotated[
        str,
        typer.Argument(help="Content type to list (e.g., 'dashboards', 'looks')"),
    ],
    db: Annotated[
        str,
        typer.Option("--db", help="Database path to query"),
    ] = "looker.db",
    owner: Annotated[
        str | None,
        typer.Option("--owner", help="Filter by owner email"),
    ] = None,
    folder: Annotated[
        str | None,
        typer.Option("--folder", help="Filter by folder name"),
    ] = None,
    created_after: Annotated[
        str | None,
        typer.Option("--created-after", help="Filter by creation date (ISO format)"),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Maximum items to return (default: 50 for table, 0 for all)"),
    ] = None,
    offset: Annotated[
        int,
        typer.Option("--offset", help="Pagination offset"),
    ] = 0,
    output: Annotated[
        str,
        typer.Option("--output", "-o", help='Output format: "table" or "json"'),
    ] = "table",
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable verbose logging"),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable debug logging"),
    ] = False,
) -> None:
    """List extracted content items with optional filters."""
    from .commands import list as list_module

    list_module.run(
        content_type, db, owner, folder, created_after, limit, offset, output, verbose, debug
    )


@app.command()
def cleanup(
    retention_days: Annotated[
        int,
        typer.Option("--retention-days", help="Days to keep soft-deleted items"),
    ] = 30,
    db: Annotated[
        str,
        typer.Option("--db", help="Database path to clean up"),
    ] = "looker.db",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview changes without applying them"),
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
    """Clean up soft-deleted items past retention period."""
    from .commands import cleanup as cleanup_module

    cleanup_module.run(retention_days, db, dry_run, verbose, debug)


# Restore command group
restore_app = typer.Typer(
    help="Restore content from backup to Looker instance",
    no_args_is_help=True,
)
app.add_typer(restore_app, name="restore")


@restore_app.command("single")
def restore_single_cmd(
    content_type: Annotated[
        str,
        typer.Argument(help="Content type to restore (dashboard, look, folder, etc.)"),
    ],
    content_id: Annotated[
        str,
        typer.Argument(help="ID of the content item to restore"),
    ],
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to configuration file"),
    ] = None,
    db_path: Annotated[
        str,
        typer.Option("--db-path", help="Path to SQLite backup database"),
    ] = "looker.db",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Validate without making changes"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Skip confirmation prompts"),
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
    """Restore a single content item by type and ID."""
    from .commands import restore as restore_module

    restore_module.restore_single(
        content_type,
        content_id,
        config,
        db_path,
        dry_run,
        force,
        json_output,
        verbose,
        debug,
    )


if __name__ == "__main__":
    app()
