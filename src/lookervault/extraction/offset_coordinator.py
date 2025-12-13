"""Thread-safe coordinator for parallel offset-based pagination."""

import threading


class OffsetCoordinator:
    """Thread-safe coordinator for parallel offset-based pagination.

    Coordinates multiple workers fetching data using offset-based pagination.
    Each worker atomically claims the next offset range to fetch, ensuring
    no duplicate or missing data.

    Example:
        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(8)

        # Worker 1 claims: (0, 100)
        # Worker 2 claims: (100, 100)
        # Worker 3 claims: (200, 100)
        # ...

    Thread Safety:
        All methods are thread-safe and use a mutex lock for synchronization.
    """

    def __init__(self, stride: int):
        """Initialize offset coordinator.

        Args:
            stride: Number of items per offset range (batch size)
        """
        self._current_offset = 0
        self._stride = stride
        self._lock = threading.Lock()
        self._workers_done = 0
        self._total_workers = 0

    def claim_range(self) -> tuple[int, int]:
        """Atomically claim next offset range.

        Thread-safe method that returns the next available offset range
        and advances the internal counter.

        Returns:
            Tuple of (start_offset, limit) where:
            - start_offset: Starting offset for this range (0-based)
            - limit: Number of items to fetch

        Example:
            First call:  (0, 100)
            Second call: (100, 100)
            Third call:  (200, 100)
        """
        with self._lock:
            start = self._current_offset
            self._current_offset += self._stride
            return (start, self._stride)

    def mark_worker_complete(self) -> None:
        """Mark a worker as complete (hit end-of-data).

        Thread-safe method to track how many workers have finished
        fetching all available data.
        """
        with self._lock:
            self._workers_done += 1

    def all_workers_done(self) -> bool:
        """Check if all workers have completed.

        Returns:
            True if all workers have called mark_worker_complete()
        """
        with self._lock:
            return self._workers_done >= self._total_workers

    def set_total_workers(self, count: int) -> None:
        """Set expected number of workers.

        Args:
            count: Total number of workers that will be claiming ranges
        """
        with self._lock:
            self._total_workers = count

    def get_current_offset(self) -> int:
        """Get current offset value (for debugging/monitoring).

        Returns:
            Current offset value
        """
        with self._lock:
            return self._current_offset

    def get_workers_done(self) -> int:
        """Get number of workers that have completed (for debugging/monitoring).

        Returns:
            Number of workers marked as done
        """
        with self._lock:
            return self._workers_done
