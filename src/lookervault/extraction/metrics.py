"""Thread-safe metrics tracking for parallel extraction."""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ThreadSafeMetrics:
    """Thread-safe metrics aggregation for parallel worker threads.

    All methods use threading.Lock to ensure safe concurrent access from
    multiple worker threads. Use this class to aggregate statistics across
    all workers without data races.

    Attributes:
        items_processed: Total items processed across all workers
        items_by_type: Breakdown of items processed per content type
        errors: Total error count across all workers
        worker_errors: Error messages grouped by worker thread ID
        start_time: Extraction start timestamp for throughput calculation
        _lock: Thread synchronization lock (private)

    Example:
        >>> metrics = ThreadSafeMetrics()
        >>> # From worker thread:
        >>> metrics.increment_processed(content_type=1, count=10)
        >>> # From main thread:
        >>> snapshot = metrics.snapshot()
        >>> print(f"Processed {snapshot['total']} items")
    """

    items_processed: int = 0
    items_by_type: dict[int, int] = field(default_factory=dict)
    errors: int = 0
    worker_errors: dict[str, list[str]] = field(default_factory=dict)
    start_time: datetime = field(default_factory=datetime.now)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def increment_processed(self, content_type: int, count: int = 1) -> None:
        """Thread-safe increment of processed item counters.

        Args:
            content_type: ContentType enum value (e.g., 1=dashboard, 2=look)
            count: Number of items to increment (default: 1)
        """
        with self._lock:
            self.items_processed += count
            self.items_by_type[content_type] = self.items_by_type.get(content_type, 0) + count

    def record_error(self, worker_id: str, error_msg: str) -> None:
        """Thread-safe error recording with worker attribution.

        Args:
            worker_id: Worker thread identifier (e.g., thread name)
            error_msg: Error message to record
        """
        with self._lock:
            self.errors += 1
            if worker_id not in self.worker_errors:
                self.worker_errors[worker_id] = []
            self.worker_errors[worker_id].append(error_msg)

    def snapshot(self) -> dict[str, Any]:
        """Thread-safe atomic read of all metrics.

        Returns a consistent snapshot of all metrics at a single point in time.
        Safe to call from any thread without risking partial reads.

        Returns:
            Dictionary with keys:
                - total: Total items processed
                - by_type: Dict of items per content type
                - errors: Total error count
                - duration_seconds: Elapsed time since start
                - items_per_second: Throughput rate
        """
        with self._lock:
            duration = (datetime.now() - self.start_time).total_seconds()
            items_per_second = self.items_processed / duration if duration > 0 else 0.0

            return {
                "total": self.items_processed,
                "by_type": dict(self.items_by_type),  # Copy to avoid external mutation
                "errors": self.errors,
                "duration_seconds": duration,
                "items_per_second": items_per_second,
                "worker_errors": dict(self.worker_errors),  # Copy
            }

    def __str__(self) -> str:
        """Return human-readable metrics summary."""
        snapshot = self.snapshot()
        return (
            f"ThreadSafeMetrics(processed={snapshot['total']}, "
            f"errors={snapshot['errors']}, "
            f"rate={snapshot['items_per_second']:.1f} items/sec)"
        )
