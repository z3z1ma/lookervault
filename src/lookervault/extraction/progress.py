"""Progress tracking for extraction operations."""

import json
import sys
from enum import Enum
from typing import Any, Protocol

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)


class OutputMode(str, Enum):
    """Output mode for progress tracking."""

    HUMAN = "table"
    MACHINE = "json"


class ProgressTracker(Protocol):
    """Protocol for tracking extraction progress."""

    def start_task(self, task_id: str, description: str, total: int | None = None) -> None:
        """Start tracking a new task.

        Args:
            task_id: Unique task identifier
            description: Human-readable description
            total: Total items (None if unknown)
        """
        ...

    def update_task(self, task_id: str, advance: int = 1) -> None:
        """Update task progress.

        Args:
            task_id: Task identifier
            advance: Items to advance by
        """
        ...

    def complete_task(self, task_id: str) -> None:
        """Mark task as complete."""
        ...

    def fail_task(self, task_id: str, error: str) -> None:
        """Mark task as failed."""
        ...

    def emit_event(self, event: str, **data: Any) -> None:
        """Emit structured event (for JSON mode).

        Args:
            event: Event type
            **data: Event payload
        """
        ...


class RichProgressTracker:
    """Terminal-based progress tracker using Rich library."""

    def __init__(self, disable: bool = False):
        """Initialize progress tracker.

        Args:
            disable: If True, disable progress display
        """
        self.console = Console()
        self.disable = disable
        self._progress: Progress | None = None
        self._tasks: dict[str, TaskID] = {}

    def __enter__(self):
        """Enter context manager."""
        if not self.disable:
            self._progress = Progress(
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TextColumn("({task.percentage:>3.0f}%)"),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=self.console,
            )
            self._progress.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager."""
        if self._progress:
            self._progress.__exit__(exc_type, exc_val, exc_tb)
            self._progress = None
        return False

    def start_task(self, task_id: str, description: str, total: int | None = None) -> None:
        """Start tracking a new task.

        Args:
            task_id: Unique task identifier
            description: Human-readable description
            total: Total items (None if unknown)
        """
        if self._progress and not self.disable:
            rich_task_id = self._progress.add_task(description, total=total)
            self._tasks[task_id] = rich_task_id

    def update_task(self, task_id: str, advance: int = 1) -> None:
        """Update task progress.

        Args:
            task_id: Task identifier
            advance: Items to advance by
        """
        if self._progress and not self.disable and task_id in self._tasks:
            self._progress.update(self._tasks[task_id], advance=advance)

    def complete_task(self, task_id: str) -> None:
        """Mark task as complete.

        Args:
            task_id: Task identifier
        """
        if self._progress and not self.disable and task_id in self._tasks:
            self._progress.update(self._tasks[task_id], completed=True)

    def fail_task(self, task_id: str, error: str) -> None:
        """Mark task as failed.

        Args:
            task_id: Task identifier
            error: Error message
        """
        if not self.disable:
            self.console.print(f"[red]✗ Task {task_id} failed: {error}[/red]")

    def emit_event(self, event: str, **data: Any) -> None:
        """Emit structured event (no-op for Rich tracker).

        Args:
            event: Event type
            **data: Event payload
        """
        pass  # Rich tracker uses visual progress, not events


class JsonProgressTracker:
    """JSON-based progress tracker for machine-readable output."""

    def __init__(self):
        """Initialize JSON progress tracker."""
        self._tasks: dict[str, dict[str, Any]] = {}

    def __enter__(self):
        """Enter context manager."""
        self.emit_event("extraction_started")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager."""
        if exc_type:
            self.emit_event("extraction_failed", error=str(exc_val))
        else:
            self.emit_event("extraction_complete")
        return False

    def start_task(self, task_id: str, description: str, total: int | None = None) -> None:
        """Start tracking a new task.

        Args:
            task_id: Unique task identifier
            description: Human-readable description
            total: Total items (None if unknown)
        """
        self._tasks[task_id] = {
            "description": description,
            "total": total,
            "completed": 0,
        }
        self.emit_event(
            "task_started",
            task_id=task_id,
            description=description,
            total=total,
        )

    def update_task(self, task_id: str, advance: int = 1) -> None:
        """Update task progress.

        Args:
            task_id: Task identifier
            advance: Items to advance by
        """
        if task_id in self._tasks:
            self._tasks[task_id]["completed"] += advance

            task = self._tasks[task_id]
            percentage = (task["completed"] / task["total"]) * 100 if task["total"] else 0

            self.emit_event(
                "task_progress",
                task_id=task_id,
                completed=task["completed"],
                total=task["total"],
                percentage=round(percentage, 2),
            )

    def complete_task(self, task_id: str) -> None:
        """Mark task as complete.

        Args:
            task_id: Task identifier
        """
        self.emit_event("task_complete", task_id=task_id)

    def fail_task(self, task_id: str, error: str) -> None:
        """Mark task as failed.

        Args:
            task_id: Task identifier
            error: Error message
        """
        self.emit_event("task_failed", task_id=task_id, error=error)

    def emit_event(self, event: str, **data: Any) -> None:
        """Emit structured JSON event.

        Args:
            event: Event type
            **data: Event payload
        """
        event_data = {"event": event, **data}
        print(json.dumps(event_data), file=sys.stdout, flush=True)
