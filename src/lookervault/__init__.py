"""LookerVault - Backup and restore tool for Looker instances."""

__version__ = "0.1.0"


def main() -> None:
    """Main entry point for the CLI."""
    from lookervault.cli.main import app

    app()
