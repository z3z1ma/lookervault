"""Memory-efficient batch processing."""

import tracemalloc
from collections.abc import Callable, Iterator
from typing import Protocol, TypeVar

from lookervault.exceptions import ProcessingError

T = TypeVar("T")
R = TypeVar("R")


class BatchProcessor[T, R](Protocol):
    """Protocol for processing items in memory-safe batches."""

    def process_batches(
        self,
        items: Iterator[T],
        processor: Callable[[T], R],
        batch_size: int = 100,
    ) -> Iterator[R]:
        """Process items in batches to manage memory.

        Args:
            items: Iterator of input items
            processor: Function to process each item
            batch_size: Items per batch

        Yields:
            Processed results

        Raises:
            ProcessingError: If batch processing fails
        """
        ...

    def get_memory_usage(self) -> tuple[int, int]:
        """Get current memory usage.

        Returns:
            Tuple of (current_bytes, peak_bytes)
        """
        ...


class MemoryAwareBatchProcessor:
    """Batch processor with memory monitoring."""

    def __init__(self, enable_monitoring: bool = True):
        """Initialize batch processor.

        Args:
            enable_monitoring: If True, enable memory monitoring
        """
        self.enable_monitoring = enable_monitoring
        if enable_monitoring:
            tracemalloc.start()

    def process_batches(
        self,
        items: Iterator[T],
        processor: Callable[[T], R],
        batch_size: int = 100,
    ) -> Iterator[R]:
        """Process items in batches to manage memory.

        Args:
            items: Iterator of input items
            processor: Function to process each item
            batch_size: Items per batch

        Yields:
            Processed results

        Raises:
            ProcessingError: If batch processing fails
        """
        try:
            batch = []
            for item in items:
                batch.append(item)

                if len(batch) >= batch_size:
                    # Process full batch
                    yield from self._process_batch(batch, processor)
                    batch = []

            # Process remaining items
            if batch:
                yield from self._process_batch(batch, processor)

        except Exception as e:
            raise ProcessingError(f"Batch processing failed: {e}") from e

    def _process_batch(self, batch: list[T], processor: Callable[[T], R]) -> Iterator[R]:
        """Process a single batch of items.

        Args:
            batch: List of items to process
            processor: Processing function

        Yields:
            Processed results
        """
        for item in batch:
            yield processor(item)

    def get_memory_usage(self) -> tuple[int, int]:
        """Get current memory usage.

        Returns:
            Tuple of (current_bytes, peak_bytes)
        """
        if self.enable_monitoring:
            current, peak = tracemalloc.get_traced_memory()
            return (current, peak)
        return (0, 0)

    def stop_monitoring(self) -> None:
        """Stop memory monitoring."""
        if self.enable_monitoring:
            tracemalloc.stop()
