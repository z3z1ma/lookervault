"""Work queue for distributing extraction tasks across parallel workers."""

import queue
from dataclasses import dataclass
from typing import Any


@dataclass
class WorkItem:
    """Batch of items to be processed by worker threads.

    Used in producer-consumer pattern where:
    - Producer (main thread) fetches from API and creates WorkItems
    - Consumers (worker threads) process WorkItems and save to database

    Attributes:
        content_type: ContentType enum value (e.g., 1=dashboard, 2=look)
        items: Batch of raw API response dictionaries to process
        batch_number: Sequential batch identifier for tracking progress
        is_final_batch: True if this is the last batch for this content type
                       (signals checkpoint completion)
    """

    content_type: int
    items: list[dict[str, Any]]
    batch_number: int
    is_final_batch: bool = False

    def __post_init__(self) -> None:
        """Validate WorkItem fields after initialization.

        Raises:
            ValueError: If validation fails
        """
        if not isinstance(self.content_type, int) or self.content_type < 0:
            raise ValueError(f"content_type must be non-negative integer, got {self.content_type}")

        if not isinstance(self.items, list):
            raise ValueError(f"items must be a list, got {type(self.items)}")

        if not self.items:
            raise ValueError("items list cannot be empty")

        if not isinstance(self.batch_number, int) or self.batch_number < 0:
            raise ValueError(f"batch_number must be non-negative integer, got {self.batch_number}")

        if not isinstance(self.is_final_batch, bool):
            raise ValueError(f"is_final_batch must be boolean, got {type(self.is_final_batch)}")

    def __repr__(self) -> str:
        """Return detailed string representation for debugging."""
        return (
            f"WorkItem(content_type={self.content_type}, "
            f"batch_number={self.batch_number}, "
            f"items={len(self.items)}, "
            f"is_final={self.is_final_batch})"
        )


class WorkQueue:
    """Thread-safe bounded queue for distributing work to parallel workers.

    Wraps Python's queue.Queue with WorkItem-specific semantics including:
    - Bounded queue size for backpressure (prevents memory exhaustion)
    - Support for stop signals (None) to gracefully shutdown workers
    - Exception handling for queue.Empty and queue.Full conditions

    Attributes:
        _queue: Underlying thread-safe queue.Queue instance
        maxsize: Maximum queue depth (0 = unlimited, but don't use that)

    Example:
        >>> work_queue = WorkQueue(maxsize=1000)
        >>> # Producer thread:
        >>> work_queue.put_work(WorkItem(...))
        >>> work_queue.send_stop_signals(num_workers=8)
        >>> # Consumer thread:
        >>> while True:
        >>>     work = work_queue.get_work()
        >>>     if work is None: break  # Stop signal
        >>>     process(work)
    """

    def __init__(self, maxsize: int = 0):
        """Initialize bounded work queue.

        Args:
            maxsize: Maximum queue depth. 0 = unlimited (not recommended).
                    Recommended: workers * 100 for good throughput.
        """
        self._queue: queue.Queue[WorkItem | None] = queue.Queue(maxsize=maxsize)
        self.maxsize = maxsize

    def put_work(self, item: WorkItem, block: bool = True, timeout: float | None = None) -> None:
        """Add work item to queue (blocks if queue is full).

        Args:
            item: WorkItem to queue for processing
            block: If True, block until queue has space. If False, raise queue.Full.
            timeout: Optional timeout in seconds for blocking put

        Raises:
            queue.Full: If queue is full and block=False
            queue.Full: If timeout expires while waiting
        """
        self._queue.put(item, block=block, timeout=timeout)

    def get_work(self, block: bool = True, timeout: float | None = None) -> WorkItem | None:
        """Get next work item from queue (blocks if queue is empty).

        Returns None when stop signal received (indicates shutdown).

        Args:
            block: If True, block until work available. If False, raise queue.Empty.
            timeout: Optional timeout in seconds for blocking get

        Returns:
            WorkItem to process, or None if stop signal received

        Raises:
            queue.Empty: If queue is empty and block=False
            queue.Empty: If timeout expires while waiting
        """
        return self._queue.get(block=block, timeout=timeout)

    def send_stop_signals(self, num_workers: int) -> None:
        """Send stop signals (None) to all workers for graceful shutdown.

        Args:
            num_workers: Number of worker threads to signal
        """
        for _ in range(num_workers):
            self._queue.put(None)

    def qsize(self) -> int:
        """Return approximate queue size.

        Note: This is approximate and may be inaccurate in multi-threaded contexts.
        Use only for monitoring/debugging, not for synchronization.

        Returns:
            Approximate number of items in queue
        """
        return self._queue.qsize()

    def empty(self) -> bool:
        """Return True if queue is empty (approximate).

        Note: This is approximate. Don't use for synchronization.

        Returns:
            True if queue appears empty
        """
        return self._queue.empty()

    def full(self) -> bool:
        """Return True if queue is full (approximate).

        Note: This is approximate. Don't use for synchronization.

        Returns:
            True if queue appears full
        """
        return self._queue.full()

    def __repr__(self) -> str:
        """Return string representation with queue state."""
        return f"WorkQueue(maxsize={self.maxsize}, current_size≈{self.qsize()})"
