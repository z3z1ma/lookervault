"""Thread-safe coordinator for parallel offset-based pagination."""

import threading


class OffsetCoordinator:
    """Thread-safe coordinator for parallel offset-based pagination.

    Coordinates multiple workers fetching data using offset-based pagination.
    Each worker atomically claims the next offset range to fetch, ensuring
    no duplicate or missing data.

    Example:
        Basic usage pattern for parallel data fetching:

        >>> from concurrent.futures import ThreadPoolExecutor
        >>> coordinator = OffsetCoordinator(stride=100)
        >>> coordinator.set_total_workers(4)
        >>>
        >>> def fetch_items():
        ...     while True:
        ...         offset, limit = coordinator.claim_range()
        ...         items = api.fetch(offset=offset, limit=limit)
        ...         if not items:
        ...             coordinator.mark_worker_complete()
        ...             break
        ...         process(items)
        >>>
        >>> with ThreadPoolExecutor(max_workers=4) as executor:
        ...     executor.map(fetch_items, range(4))

    Thread Safety:
        All methods are thread-safe and use a mutex lock for synchronization.
    """

    def __init__(self, stride: int):
        """Initialize offset coordinator.

        Args:
            stride: Number of items per offset range (batch size)

        Example:
            Create a coordinator that fetches 100 items at a time:

            >>> coordinator = OffsetCoordinator(stride=100)
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
            Sequential calls return increasing offset ranges:

            >>> coordinator = OffsetCoordinator(stride=100)
            >>> coordinator.claim_range()
            (0, 100)
            >>> coordinator.claim_range()
            (100, 100)
            >>> coordinator.claim_range()
            (200, 100)

            Use in a worker function:

            >>> def worker():
            ...     while True:
            ...         offset, limit = coordinator.claim_range()
            ...         items = fetch(offset=offset, limit=limit)
            ...         if not items:
            ...             break
            ...         process(items)
        """
        with self._lock:
            start = self._current_offset
            self._current_offset += self._stride
            return (start, self._stride)

    def mark_worker_complete(self) -> None:
        """Mark a worker as complete (hit end-of-data).

        Thread-safe method to track how many workers have finished
        fetching all available data.

        Example:
            >>> coordinator = OffsetCoordinator(stride=100)
            >>> coordinator.set_total_workers(3)
            >>> coordinator.mark_worker_complete()
            >>> coordinator.get_workers_done()
            1
        """
        with self._lock:
            self._workers_done += 1

    def all_workers_done(self) -> bool:
        """Check if all workers have completed.

        Returns:
            True if all workers have called mark_worker_complete()

        Example:
            >>> coordinator = OffsetCoordinator(stride=100)
            >>> coordinator.set_total_workers(2)
            >>> coordinator.all_workers_done()
            False
            >>> coordinator.mark_worker_complete()
            >>> coordinator.mark_worker_complete()
            >>> coordinator.all_workers_done()
            True
        """
        with self._lock:
            return self._workers_done >= self._total_workers

    def set_total_workers(self, count: int) -> None:
        """Set expected number of workers.

        Args:
            count: Total number of workers that will be claiming ranges

        Example:
            >>> coordinator = OffsetCoordinator(stride=100)
            >>> coordinator.set_total_workers(4)
            >>> coordinator.get_workers_done()
            0
            >>> coordinator.all_workers_done()
            False
        """
        with self._lock:
            self._total_workers = count

    def get_current_offset(self) -> int:
        """Get current offset value (for debugging/monitoring).

        Returns:
            Current offset value

        Example:
            >>> coordinator = OffsetCoordinator(stride=100)
            >>> coordinator.get_current_offset()
            0
            >>> coordinator.claim_range()
            (0, 100)
            >>> coordinator.get_current_offset()
            100
        """
        with self._lock:
            return self._current_offset

    def get_workers_done(self) -> int:
        """Get number of workers that have completed (for debugging/monitoring).

        Returns:
            Number of workers marked as done

        Example:
            >>> coordinator = OffsetCoordinator(stride=100)
            >>> coordinator.set_total_workers(3)
            >>> coordinator.get_workers_done()
            0
            >>> coordinator.mark_worker_complete()
            >>> coordinator.get_workers_done()
            1
        """
        with self._lock:
            return self._workers_done
