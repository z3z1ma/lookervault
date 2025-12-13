"""Output formatting utilities for CLI commands."""

import json
from typing import Any

from rich.console import Console
from rich.table import Table

from lookervault.config.models import ConnectionStatus, ReadinessCheckResult


def format_json(data: Any) -> str:
    """
    Format data as JSON string.

    Args:
        data: Data to format (must be JSON-serializable)

    Returns:
        Pretty-printed JSON string
    """
    # Convert Pydantic models to dict if needed
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    return json.dumps(data, indent=2, default=str)


def format_table(headers: list[str], rows: list[list[str]], title: str = "") -> None:
    """
    Format and print data as a table using Rich.

    Args:
        headers: Column headers
        rows: Table rows
        title: Optional table title
    """
    console = Console()
    table = Table(title=title, show_header=True, header_style="bold")

    for header in headers:
        table.add_column(header)

    for row in rows:
        table.add_row(*row)

    console.print(table)


def format_readiness_check_table(result: ReadinessCheckResult) -> None:
    """
    Format readiness check result as a table.

    Args:
        result: ReadinessCheckResult to format
    """
    console = Console()

    # Print title
    console.print("\n[bold]LookerVault Readiness Check[/bold]")
    console.print("━" * 50)

    # Print check results
    for check in result.checks:
        if check.status == "pass":
            icon = "✓"
            style = "green"
        elif check.status == "fail":
            icon = "✗"
            style = "red"
        else:  # warning
            icon = "⚠"
            style = "yellow"

        console.print(f"[{style}]{icon} {check.name}[/{style}]")

        # Print message if it's not just a simple pass
        if check.message and check.status != "pass":
            console.print(f"  {check.message}", style="dim")
        elif check.message and check.message != check.name:
            console.print(f"  ({check.message})", style="dim")

    # Print overall status
    console.print()
    status_text = "READY" if result.ready else "NOT READY"
    status_style = "bold green" if result.ready else "bold red"
    console.print(f"Status: [{status_style}]{status_text}[/{status_style}]")
    console.print(f"Checked: {result.timestamp.isoformat()}\n")


def format_readiness_check_json(result: ReadinessCheckResult) -> str:
    """
    Format readiness check result as JSON.

    Args:
        result: ReadinessCheckResult to format

    Returns:
        JSON string
    """
    return format_json(result)


def format_instance_info_table(status: ConnectionStatus) -> None:
    """
    Format Looker instance information as a table.

    Args:
        status: ConnectionStatus with instance info
    """
    console = Console()

    if not status.connected:
        # Print error
        console.print("\n[bold red]Error: Failed to connect to Looker instance[/bold red]\n")
        console.print(f"Reason: {status.error_message}\n")
        console.print("[bold]Troubleshooting:[/bold]")
        console.print("  - Verify LOOKERVAULT_CLIENT_ID and LOOKERVAULT_CLIENT_SECRET are set")
        console.print("  - Check that credentials have not expired")
        console.print("  - Ensure api_url is correct\n")
        return

    # Create table for instance info
    console.print("\n[bold]Looker Instance Information[/bold]")
    console.print("━" * 50)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Property", style="bold")
    table.add_column("Value")

    table.add_row("Instance URL", status.instance_url or "")
    table.add_row("Looker Version", status.looker_version or "")
    table.add_row("API Version", status.api_version or "")
    table.add_row(
        "User",
        f"{status.user_email} (ID: {status.user_id})" if status.user_email else "",
    )
    table.add_row("Status", "[green]Connected[/green]")

    console.print(table)
    console.print()


def format_instance_info_json(status: ConnectionStatus) -> str:
    """
    Format Looker instance information as JSON.

    Args:
        status: ConnectionStatus with instance info

    Returns:
        JSON string
    """
    return format_json(status)
