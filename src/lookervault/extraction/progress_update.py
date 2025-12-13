"""Progress update models for real-time extraction monitoring."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class ProgressUpdate:
    """Real-time progress update from parallel extraction workers.

    Used to notify progress trackers about extraction progress in real-time.
    Workers emit these updates after completing batches, allowing UI components
    to display live progress bars and statistics.

    Attributes:
        content_type: ContentType enum value being processed
        items_processed: Number of items processed in this update
        total_items: Expected total items for this content type (if known)
        batches_completed: Number of batches completed so far
        timestamp: When this update was generated
        worker_id: ID of worker thread that generated this update
        metadata: Optional additional context (e.g., current batch number)
    """

    content_type: int
    items_processed: int
    total_items: int | None = None
    batches_completed: int = 0
    timestamp: datetime = None  # type: ignore[assignment]
    worker_id: str | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Set timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now()

    @property
    def progress_percentage(self) -> float | None:
        """Calculate progress percentage if total is known.

        Returns:
            Progress percentage (0-100), or None if total unknown
        """
        if self.total_items is None or self.total_items == 0:
            return None
        return min((self.items_processed / self.total_items) * 100.0, 100.0)

    def __str__(self) -> str:
        """Return human-readable progress summary."""
        if self.progress_percentage is not None:
            return (
                f"ProgressUpdate(content_type={self.content_type}, "
                f"{self.items_processed}/{self.total_items} items, "
                f"{self.progress_percentage:.1f}%, "
                f"batches={self.batches_completed})"
            )
        else:
            return (
                f"ProgressUpdate(content_type={self.content_type}, "
                f"{self.items_processed} items, "
                f"batches={self.batches_completed})"
            )
