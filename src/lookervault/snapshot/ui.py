"""Interactive terminal UI for snapshot selection."""

import sys

import click
from rich.align import Align, AlignMethod
from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from lookervault.cli.rich_logging import console
from lookervault.snapshot.models import SnapshotMetadata


class Menu:
    """Interactive menu for terminal selection using arrow keys."""

    def __init__(
        self,
        *options: str,
        start_index: int = 0,
        title: str = "MENU",
        rule: bool = True,
        panel: bool = True,
        panel_title: str = "",
        color: str = "bold green",
        align: AlignMethod = "center",
        selection_char: str = ">",
        selected_char: str = "*",
        selected_color: str = "bold blue",
        highlight_color: str = "",
    ):
        self.options = options
        self.index = start_index
        self.title = title
        self.rule = rule
        self.panel = panel
        self.panel_title = panel_title
        self.color = color
        self.align = align
        self.selection_char = selection_char
        self.highlight_color = highlight_color
        self.selected_char = selected_char
        self.selected_color = selected_color
        self.selected_options = []

    def _get_click(self) -> str | None:
        match click.getchar():
            case "\r":
                return "enter"
            case "\x1b[B" | "s" | "S" | "àP" | "j":
                return "down"
            case "\x1b[A" | "w" | "W" | "àH" | "k":
                return "up"
            case "\x1b[D" | "a" | "A" | "àK" | "h":
                return "left"
            case "\x1b[C" | "d" | "D" | "àM" | "l":
                return "right"
            case " " | "\x0d":
                return "space"
            case "\x1b":
                return "exit"
            case _:
                return None

    def _update_index(self, key: str | None) -> None:
        if key == "down":
            self.index += 1
        elif key == "up":
            self.index -= 1

        if self.index > len(self.options) - 1:
            self.index = 0
        elif self.index < 0:
            self.index = len(self.options) - 1

    @property
    def _group(self) -> Group:
        menu = Text(justify="left")

        current = Text(self.selection_char + " ", self.color)
        not_selected = Text(" " * (len(self.selection_char) + 1))
        selected = Text(self.selected_char + " ", self.selected_color)

        for idx, option in enumerate(self.options):
            if (
                idx == self.index and option in self.selected_options
            ):  # is current selected in multiple selection mode
                menu.append(Text.assemble(current, Text(option + "\n", self.selected_color)))
            elif idx == self.index:  # is selected in single mode
                menu.append(Text.assemble(current, Text(option + "\n", self.highlight_color)))
            elif option in self.selected_options:  # is selected in multiple selection mode
                menu.append(Text.assemble(selected, Text(option + "\n", self.selected_color)))
            else:
                menu.append(Text.assemble(not_selected, option + "\n"))
        menu.rstrip()

        if self.panel:
            menu = Panel.fit(menu)
            menu.title = Text(self.panel_title, self.color)
        if self.title:
            group = Group(
                Rule(self.title, style=self.color) if self.rule else self.title,
                Align(menu, self.align),
            )
        else:
            group = Group(
                Align(menu, self.align),
            )

        return group

    def _clean_menu(self):
        rule = 1 if self.title else 0
        panel = 2 if self.panel else 0
        for _ in range(len(self.options) + rule + panel):
            print("\x1b[A\x1b[K", end="")

    def ask(self, screen: bool = True, esc: bool = True) -> str:
        """Ask user to select a single option from the menu.

        Args:
            screen: Whether to use alternate screen buffer
            esc: Whether ESC key exits the program

        Returns:
            Selected option string
        """
        with Live(self._group, auto_refresh=False, screen=screen) as live:
            live.update(self._group, refresh=True)
            while True:
                try:
                    key = self._get_click()
                    if key == "enter":
                        break
                    elif key == "exit" and esc:
                        raise KeyboardInterrupt

                    self._update_index(key)
                    live.update(self._group, refresh=True)
                except (KeyboardInterrupt, EOFError):
                    raise KeyboardInterrupt from None

        if not screen:
            self._clean_menu()

        return self.options[self.index]

    def ask_multiple(
        self,
        screen: bool = True,
        esc: bool = True,
    ) -> list[str]:
        """Ask user to select multiple options from the menu.

        Args:
            screen: Whether to use alternate screen buffer
            esc: Whether ESC key exits the program

        Returns:
            List of selected option strings
        """
        self.selected_options = []
        with Live(self._group, auto_refresh=False, screen=screen) as live:
            live.update(self._group, refresh=True)
            while True:
                try:
                    key = self._get_click()
                    if key == "enter":
                        break
                    elif key == "exit" and esc:
                        raise KeyboardInterrupt
                    elif key == "down" or key == "up":
                        self._update_index(key)
                    elif key == "space":
                        if self.options[self.index] in self.selected_options:
                            self.selected_options.remove(self.options[self.index])
                        else:
                            self.selected_options.append(self.options[self.index])

                    live.update(self._group, refresh=True)
                except (KeyboardInterrupt, EOFError):
                    raise KeyboardInterrupt from None

        if not screen:
            self._clean_menu()

        return self.selected_options


def detect_interactive_mode() -> bool:
    """Detect if the terminal supports interactive mode.

    Returns:
        True if both stdin and stdout are TTYs (interactive terminal)
        False if running in CI/CD, redirected output, or non-TTY environment
    """
    return sys.stdin.isatty() and sys.stdout.isatty()


def interactive_snapshot_picker(
    snapshots: list[SnapshotMetadata],
    title: str = "Select Snapshot",
    allow_cancel: bool = True,
) -> SnapshotMetadata | None:
    """Interactive terminal UI for selecting a snapshot with arrow key navigation.

    Args:
        snapshots: List of available snapshots (must be non-empty)
        title: Menu title text
        allow_cancel: Whether to allow ESC key cancellation

    Returns:
        Selected SnapshotMetadata or None if cancelled

    Raises:
        RuntimeError: If terminal doesn't support interactive mode
        ValueError: If snapshots list is empty
    """
    if not snapshots:
        raise ValueError("No snapshots available for selection")

    if not detect_interactive_mode():
        raise RuntimeError(
            "Interactive mode not supported in this terminal.\n\n"
            "Solutions:\n"
            "  1. Use snapshot index: lookervault snapshot download 1\n"
            "  2. Use snapshot timestamp: lookervault snapshot download 2025-12-14T10:30:00\n"
            "  3. Run in an interactive terminal (not CI/CD or redirected output)"
        )

    # Display preview panel with snapshot details
    console.print()
    _display_preview_panel(snapshots[0])

    # Display help text
    console.print()
    console.print("[dim]Navigation: ↑/↓ or j/k | Select: Enter | Cancel: ESC[/dim]")
    console.print()

    # Build menu options with formatted snapshot info
    options = []
    for snapshot in snapshots:
        # Format: "1. looker-2025-12-14T10-30-00.db.gz (45.2 MB, 2 days ago)"
        age_str = _format_age(snapshot.age_days)
        option = (
            f"{snapshot.sequential_index}. {snapshot.filename.split('/')[-1]} "
            f"({snapshot.size_mb} MB, {age_str})"
        )
        options.append(option)

    try:
        # Launch interactive menu
        menu = Menu(
            *options,
            title=title,
            panel_title="Available Snapshots",
            color="bold cyan",
            highlight_color="bold yellow",
            selection_char="→",
        )

        selected_option = menu.ask(screen=False, esc=allow_cancel)

        # Extract index from selected option (format: "1. filename...")
        selected_index = int(selected_option.split(".")[0])

        # Find matching snapshot
        selected_snapshot = next(
            (s for s in snapshots if s.sequential_index == selected_index), None
        )

        if selected_snapshot:
            console.print()
            console.print(f"[green]✓[/green] Selected: {selected_snapshot.filename.split('/')[-1]}")
            console.print()

        return selected_snapshot

    except KeyboardInterrupt:
        console.print()
        console.print("[yellow]Selection cancelled[/yellow]")
        console.print()
        return None


def _display_preview_panel(snapshot: SnapshotMetadata) -> None:
    """Display a Rich panel with snapshot metadata preview.

    Args:
        snapshot: Snapshot to display preview for
    """
    table = Table.grid(padding=(0, 2))
    table.add_column(style="cyan", justify="right")
    table.add_column(style="white")

    table.add_row("Filename:", snapshot.filename.split("/")[-1])
    table.add_row("Created:", snapshot.created.strftime("%Y-%m-%d %H:%M:%S UTC"))
    table.add_row("Size:", f"{snapshot.size_mb} MB ({snapshot.size_bytes:,} bytes)")
    table.add_row("Age:", _format_age(snapshot.age_days))
    table.add_row("CRC32C:", snapshot.crc32c)

    if snapshot.content_encoding:
        table.add_row("Encoding:", snapshot.content_encoding)

    if snapshot.tags:
        table.add_row("Tags:", ", ".join(snapshot.tags))

    panel = Panel(
        table,
        title="[bold cyan]Snapshot Details[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    )

    console.print(panel)


def _format_age(age_days: int) -> str:
    """Format age in human-readable format.

    Args:
        age_days: Age in days

    Returns:
        Formatted age string (e.g., "2 hours", "3 days", "2 months")
    """
    if age_days == 0:
        return "< 1 day"
    elif age_days == 1:
        return "1 day ago"
    elif age_days < 30:
        return f"{age_days} days ago"
    elif age_days < 365:
        months = age_days // 30
        return f"{months} month{'s' if months > 1 else ''} ago"
    else:
        years = age_days // 365
        return f"{years} year{'s' if years > 1 else ''} ago"
