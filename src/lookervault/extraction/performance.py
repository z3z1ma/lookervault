"""Performance tuning utilities for parallel extraction.

Provides recommendations for optimal worker counts, queue sizes, and batch sizes
based on system resources and extraction characteristics.
"""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PerformanceProfile:
    """Performance characteristics and recommendations for extraction.

    Attributes:
        workers: Recommended number of worker threads
        queue_size: Recommended work queue depth
        batch_size: Recommended items per batch
        expected_throughput: Estimated items/second (rough estimate)
        notes: Performance notes and warnings
    """

    workers: int
    queue_size: int
    batch_size: int
    expected_throughput: float
    notes: list[str]


class PerformanceTuner:
    """Performance tuning recommendations for parallel extraction.

    Provides optimal configuration based on:
    - CPU core count
    - Expected dataset size
    - Item complexity (small vs large content)
    - Available memory

    Examples:
        >>> tuner = PerformanceTuner()
        >>> profile = tuner.recommend_for_dataset(total_items=50000, avg_item_size_kb=5)
        >>> print(f"Use {profile.workers} workers with batch_size={profile.batch_size}")
    """

    # Performance constants based on empirical testing
    SQLITE_WRITE_LIMIT = 16  # SQLite write throughput plateaus beyond this
    DEFAULT_WORKERS = 8  # Conservative default for most systems
    MIN_WORKERS = 1
    MAX_WORKERS = 50

    # Batch size recommendations
    SMALL_ITEM_BATCH = 200  # For items < 1KB (dashboards, looks without large payloads)
    MEDIUM_ITEM_BATCH = 100  # For items 1-10KB (typical dashboards)
    LARGE_ITEM_BATCH = 50  # For items > 10KB (dashboards with many elements)

    # Queue sizing
    QUEUE_MULTIPLIER = 100  # queue_size = workers * multiplier

    # Throughput estimates (items/second per worker, approximate)
    BASE_THROUGHPUT_PER_WORKER = 50  # Sequential baseline
    PARALLEL_EFFICIENCY = 0.85  # 85% scaling efficiency due to contention

    def __init__(self):
        """Initialize performance tuner with system information."""
        self.cpu_count = os.cpu_count() or 1

    def recommend_for_dataset(
        self,
        total_items: int | None = None,
        avg_item_size_kb: float = 5.0,
        memory_limit_mb: int = 2000,
    ) -> PerformanceProfile:
        """Recommend optimal configuration for a dataset.

        Args:
            total_items: Expected total items to extract (if known)
            avg_item_size_kb: Average item size in KB (default: 5KB)
            memory_limit_mb: Memory limit in MB (default: 2GB)

        Returns:
            PerformanceProfile with recommendations
        """
        notes: list[str] = []

        # Determine optimal worker count
        workers = self._recommend_workers(total_items, notes)

        # Determine optimal batch size based on item size
        batch_size = self._recommend_batch_size(avg_item_size_kb, notes)

        # Calculate queue size
        queue_size = workers * self.QUEUE_MULTIPLIER

        # Estimate memory usage
        estimated_mem_mb = self._estimate_memory_usage(
            workers, queue_size, batch_size, avg_item_size_kb
        )

        if estimated_mem_mb > memory_limit_mb:
            notes.append(
                f"WARNING: Estimated memory usage ({estimated_mem_mb:.0f} MB) "
                f"exceeds limit ({memory_limit_mb} MB). "
                f"Consider reducing workers or batch_size."
            )

        # Estimate throughput
        expected_throughput = self._estimate_throughput(workers)

        return PerformanceProfile(
            workers=workers,
            queue_size=queue_size,
            batch_size=batch_size,
            expected_throughput=expected_throughput,
            notes=notes,
        )

    def _recommend_workers(self, total_items: int | None, notes: list[str]) -> int:
        """Recommend optimal worker count.

        Args:
            total_items: Expected total items (if known)
            notes: List to append notes to

        Returns:
            Recommended worker count
        """
        # Start with CPU-based recommendation
        cpu_based = min(self.cpu_count, self.DEFAULT_WORKERS)

        # For very small datasets, use fewer workers
        if total_items and total_items < 1000:
            workers = min(cpu_based, 4)
            notes.append(f"Small dataset ({total_items} items): using {workers} workers")
            return workers

        # For large datasets, can use more workers (up to SQLite limit)
        if total_items and total_items > 10000:
            workers = min(self.SQLITE_WRITE_LIMIT, self.cpu_count)
            if workers > self.SQLITE_WRITE_LIMIT:
                notes.append(
                    f"WARNING: {workers} workers exceeds SQLite write limit "
                    f"({self.SQLITE_WRITE_LIMIT}). Capping at {self.SQLITE_WRITE_LIMIT}."
                )
                workers = self.SQLITE_WRITE_LIMIT
            notes.append(
                f"Large dataset ({total_items} items): using {workers} workers for throughput"
            )
            return workers

        # Default: CPU-based with conservative cap
        notes.append(f"Using {cpu_based} workers based on {self.cpu_count} CPU cores")
        return cpu_based

    def _recommend_batch_size(self, avg_item_size_kb: float, notes: list[str]) -> int:
        """Recommend optimal batch size based on item size.

        Args:
            avg_item_size_kb: Average item size in KB
            notes: List to append notes to

        Returns:
            Recommended batch size
        """
        if avg_item_size_kb < 1.0:
            notes.append("Small items (<1KB): using large batch size (200)")
            return self.SMALL_ITEM_BATCH
        elif avg_item_size_kb > 10.0:
            notes.append("Large items (>10KB): using small batch size (50)")
            return self.LARGE_ITEM_BATCH
        else:
            notes.append("Medium items (1-10KB): using standard batch size (100)")
            return self.MEDIUM_ITEM_BATCH

    def _estimate_memory_usage(
        self,
        workers: int,
        queue_size: int,
        batch_size: int,
        avg_item_size_kb: float,
    ) -> float:
        """Estimate memory usage in MB.

        Rough estimation:
        - Queue holds batches of items
        - Each worker may have a batch in processing
        - Overhead for Python objects, SQLite connections, etc.

        Args:
            workers: Number of workers
            queue_size: Work queue depth
            batch_size: Items per batch
            avg_item_size_kb: Average item size in KB

        Returns:
            Estimated memory usage in MB
        """
        # Items in queue (worst case: queue full)
        max_batches_in_queue = queue_size
        max_items_in_queue = max_batches_in_queue * batch_size
        queue_memory_mb = (max_items_in_queue * avg_item_size_kb) / 1024

        # Items being processed by workers
        worker_memory_mb = (workers * batch_size * avg_item_size_kb) / 1024

        # Python overhead + SQLite connections (~50MB base + 10MB per worker)
        overhead_mb = 50 + (workers * 10)

        total_mb = queue_memory_mb + worker_memory_mb + overhead_mb

        return total_mb

    def _estimate_throughput(self, workers: int) -> float:
        """Estimate throughput in items/second.

        Based on:
        - Sequential baseline: ~50 items/sec
        - Parallel efficiency: ~85% due to SQLite write contention
        - Diminishing returns beyond 8-16 workers

        Args:
            workers: Number of worker threads

        Returns:
            Estimated items/second
        """
        if workers == 1:
            return self.BASE_THROUGHPUT_PER_WORKER

        # Apply parallel efficiency factor with diminishing returns
        if workers <= 8:
            # Linear scaling up to 8 workers with 85% efficiency
            return self.BASE_THROUGHPUT_PER_WORKER * workers * self.PARALLEL_EFFICIENCY
        else:
            # Diminishing returns beyond 8 workers
            base_8_workers = self.BASE_THROUGHPUT_PER_WORKER * 8 * self.PARALLEL_EFFICIENCY
            # Each additional worker adds 50% less than the previous
            additional = sum(
                self.BASE_THROUGHPUT_PER_WORKER * self.PARALLEL_EFFICIENCY * (0.5**i)
                for i in range(1, workers - 7)
            )
            return base_8_workers + additional

    def validate_configuration(
        self,
        workers: int,
        queue_size: int,
        batch_size: int,
    ) -> list[str]:
        """Validate configuration and return warnings.

        Args:
            workers: Number of worker threads
            queue_size: Work queue depth
            batch_size: Items per batch

        Returns:
            List of warning messages (empty if configuration is good)
        """
        warnings: list[str] = []

        # Worker count validation
        if workers < self.MIN_WORKERS or workers > self.MAX_WORKERS:
            warnings.append(
                f"Worker count {workers} outside valid range "
                f"({self.MIN_WORKERS}-{self.MAX_WORKERS})"
            )

        if workers > self.SQLITE_WRITE_LIMIT:
            warnings.append(
                f"Worker count {workers} exceeds SQLite write limit "
                f"({self.SQLITE_WRITE_LIMIT}). Expect diminishing returns."
            )

        if workers > self.cpu_count:
            warnings.append(
                f"Worker count {workers} exceeds CPU cores ({self.cpu_count}). "
                f"May cause contention."
            )

        # Queue size validation
        min_queue_size = workers * 10
        if queue_size < min_queue_size:
            warnings.append(
                f"Queue size {queue_size} too small for {workers} workers. "
                f"Minimum: {min_queue_size} (workers * 10)"
            )

        # Batch size validation
        if batch_size < 10:
            warnings.append("Batch size < 10 may cause excessive overhead")
        elif batch_size > 1000:
            warnings.append("Batch size > 1000 may cause memory issues")

        return warnings


def log_performance_recommendations(
    total_items: int | None = None,
    avg_item_size_kb: float = 5.0,
) -> PerformanceProfile:
    """Log performance recommendations and return profile.

    Convenience function for logging recommendations during extraction.

    Args:
        total_items: Expected total items to extract
        avg_item_size_kb: Average item size in KB

    Returns:
        PerformanceProfile with recommendations
    """
    tuner = PerformanceTuner()
    profile = tuner.recommend_for_dataset(total_items, avg_item_size_kb)

    logger.info("Performance recommendations:")
    logger.info(f"  Workers: {profile.workers}")
    logger.info(f"  Queue size: {profile.queue_size}")
    logger.info(f"  Batch size: {profile.batch_size}")
    logger.info(f"  Expected throughput: {profile.expected_throughput:.1f} items/sec")

    for note in profile.notes:
        if "WARNING" in note:
            logger.warning(f"  {note}")
        else:
            logger.info(f"  {note}")

    return profile
