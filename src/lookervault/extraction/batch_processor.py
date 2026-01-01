"""Memory-efficient batch processing."""

import logging
import tracemalloc
from collections.abc import Callable, Iterator
from typing import Protocol, TypeVar

from lookervault.exceptions import ProcessingError

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


class BatchProcessor(Protocol[T, R]):
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

    # Memory thresholds in bytes
    WARNING_THRESHOLD_MB = 500  # Warn when memory exceeds 500MB
    CRITICAL_THRESHOLD_MB = 1000  # Critical warning at 1GB

    def __init__(self, enable_monitoring: bool = True):
        """Initialize batch processor.

        Args:
            enable_monitoring: If True, enable memory monitoring
        """
        self.enable_monitoring = enable_monitoring
        self._warned_at_level: set[str] = set()  # Track which warnings we've already issued
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
        # Check memory usage before processing batch
        if self.enable_monitoring:
            self._check_memory_usage()

        for item in batch:
            yield processor(item)

    def _check_memory_usage(self) -> None:
        """Check current memory usage and emit warnings if thresholds exceeded."""
        current, peak = self.get_memory_usage()
        current_mb = current / (1024 * 1024)
        peak_mb = peak / (1024 * 1024)

        if current_mb > self.CRITICAL_THRESHOLD_MB and "critical" not in self._warned_at_level:
            logger.warning(
                f"CRITICAL: Memory usage is very high: {current_mb:.1f} MB "
                f"(peak: {peak_mb:.1f} MB). Consider reducing batch size."
            )
            self._warned_at_level.add("critical")

        elif current_mb > self.WARNING_THRESHOLD_MB and "warning" not in self._warned_at_level:
            logger.warning(
                f"Memory usage is elevated: {current_mb:.1f} MB "
                f"(peak: {peak_mb:.1f} MB). Monitoring for further increases."
            )
            self._warned_at_level.add("warning")

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
