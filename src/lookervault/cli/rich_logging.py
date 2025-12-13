"""Rich logging utilities for beautiful CLI output."""

import logging

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

# Define custom theme for consistent colors
LOOKERVAULT_THEME = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "error": "bold red",
        "success": "bold green",
        "dim": "dim",
        "highlight": "bold magenta",
    }
)

# Global console instance with custom theme
console = Console(theme=LOOKERVAULT_THEME, stderr=True)


def configure_rich_logging(
    level: int = logging.INFO,
    show_time: bool = True,
    show_path: bool = False,
    enable_link_path: bool = False,
) -> None:
    """Configure rich logging handler for beautiful log output.

    Args:
        level: Logging level (logging.DEBUG, logging.INFO, etc.)
        show_time: Show timestamp in log output
        show_path: Show file path in log output
        enable_link_path: Enable clickable file paths in log output
    """
    # Remove existing handlers
    logging.root.handlers.clear()

    # Configure rich handler
    rich_handler = RichHandler(
        console=console,
        show_time=show_time,
        show_path=show_path,
        enable_link_path=enable_link_path,
        rich_tracebacks=True,
        tracebacks_show_locals=True,
        markup=True,
    )

    # Set format (Rich handles the pretty formatting)
    rich_handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))

    # Configure root logger
    logging.basicConfig(
        level=level,
        handlers=[rich_handler],
        force=True,
    )


def get_console(stderr: bool = False) -> Console:
    """Get a Rich Console instance.

    Args:
        stderr: Output to stderr instead of stdout

    Returns:
        Rich Console instance
    """
    if stderr:
        return console
    return Console(theme=LOOKERVAULT_THEME)


def print_error(message: str, console_obj: Console | None = None) -> None:
    """Print error message in red.

    Args:
        message: Error message to print
        console_obj: Optional console instance (uses global if None)
    """
    c = console_obj or console
    c.print(f"[error]✗ {message}[/error]")


def print_success(message: str, console_obj: Console | None = None) -> None:
    """Print success message in green.

    Args:
        message: Success message to print
        console_obj: Optional console instance (uses global if None)
    """
    c = console_obj or console
    c.print(f"[success]✓ {message}[/success]")


def print_warning(message: str, console_obj: Console | None = None) -> None:
    """Print warning message in yellow.

    Args:
        message: Warning message to print
        console_obj: Optional console instance (uses global if None)
    """
    c = console_obj or console
    c.print(f"[warning]⚠ {message}[/warning]")


def print_info(message: str, console_obj: Console | None = None) -> None:
    """Print info message in cyan.

    Args:
        message: Info message to print
        console_obj: Optional console instance (uses global if None)
    """
    c = console_obj or console
    c.print(f"[info]{message}[/info]")
