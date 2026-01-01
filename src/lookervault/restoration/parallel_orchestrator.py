"""Parallel restoration orchestrator for bulk content restoration with multi-threading.

This module provides the ParallelRestorationOrchestrator class that handles:
- Multi-threaded parallel restoration using ThreadPoolExecutor
- Work distribution via thread-safe queue.Queue
- Rate limiting coordination across all worker threads
- Error handling with Dead Letter Queue (DLQ) for failed items
- Checkpoint-based resume capability for interrupted restorations
- Dependency-aware restoration ordering for multi-type operations
- Metrics aggregation across all workers
"""

import logging
import queue
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Protocol

from lookervault.config.models import RestorationConfig
from lookervault.extraction.metrics import ThreadSafeMetrics
from lookervault.extraction.rate_limiter import AdaptiveRateLimiter
from lookervault.restoration.dependency_graph import DependencyGraph
from lookervault.restoration.restorer import IDMapper, LookerContentRestorer
from lookervault.storage.models import (
    ContentType,
    RestorationCheckpoint,
    RestorationResult,
    RestorationSummary,
)
from lookervault.storage.repository import ContentRepository

logger = logging.getLogger(__name__)


class SupportsDeadLetterQueue(Protocol):
    """Protocol for Dead Letter Queue operations."""

    def add(
        self,
        content_id: str,
        content_type: ContentType,
        error_message: str,
        session_id: str,
        stack_trace: str | None = None,
        retry_count: int = 0,
    ) -> int:
        """Add failed item to DLQ after exhausting retries."""
        ...


class ParallelRestorationOrchestrator:
    """Orchestrates parallel restoration of Looker content using multiple worker threads.

    This class provides high-throughput parallel restoration by distributing work
    across a thread pool of workers. Each worker processes content items independently,
    with coordinated rate limiting, error handling, and checkpointing.

    Key Features:
    - **Parallel Execution**: ThreadPoolExecutor with configurable worker count
    - **Work Distribution**: Thread-safe queue.Queue for work item distribution
    - **Rate Limiting**: Shared AdaptiveRateLimiter coordinates API throttling
    - **Error Handling**: Failed items added to DLQ after max retries exhausted
    - **Checkpointing**: Periodic checkpoints enable resume capability
    - **Dependency Ordering**: Multi-type restoration respects content dependencies
    - **Metrics Aggregation**: Thread-safe metrics track progress across workers

    Thread Safety:
    - All worker threads share the same rate limiter for coordinated throttling
    - Metrics are aggregated thread-safely using ThreadSafeMetrics
    - Repository uses thread-local connections for SQLite access
    - Work queue (queue.Queue) provides thread-safe work distribution

    Examples:
        >>> # Basic parallel restoration (8 workers)
        >>> orchestrator = ParallelRestorationOrchestrator(
        ...     restorer=restorer,
        ...     repository=repo,
        ...     config=RestorationConfig(workers=8),
        ...     rate_limiter=rate_limiter,
        ...     metrics=ThreadSafeMetrics(),
        ...     dlq=repo,  # Repository implements DeadLetterQueue protocol
        ... )
        >>> summary = orchestrator.restore(ContentType.DASHBOARD, session_id="abc-123")
        >>> print(f"Restored {summary.success_count} of {summary.total_items} items")

        >>> # High-throughput restoration (16 workers)
        >>> config = RestorationConfig(workers=16, rate_limit_per_minute=200)
        >>> orchestrator = ParallelRestorationOrchestrator(
        ...     restorer=restorer,
        ...     repository=repo,
        ...     config=config,
        ...     rate_limiter=AdaptiveRateLimiter(requests_per_minute=200),
        ...     metrics=ThreadSafeMetrics(),
        ...     dlq=repo,
        ... )
        >>> summary = orchestrator.restore_all()

        >>> # Resume from checkpoint
        >>> summary = orchestrator.resume(content_type=ContentType.DASHBOARD, session_id="abc-123")
        >>> print(f"Resumed: {summary.success_count} additional items restored")

        >>> # Cross-instance migration with ID mapping
        >>> id_mapper = IDMapper(repo, "source.looker.com", "dest.looker.com")
        >>> orchestrator = ParallelRestorationOrchestrator(
        ...     restorer=restorer,
        ...     repository=repo,
        ...     config=config,
        ...     rate_limiter=rate_limiter,
        ...     metrics=ThreadSafeMetrics(),
        ...     dlq=repo,
        ...     id_mapper=id_mapper,
        ... )
    """

    repository: ContentRepository

    def __init__(
        self,
        restorer: LookerContentRestorer,
        repository: ContentRepository,
        config: RestorationConfig,
        rate_limiter: AdaptiveRateLimiter,
        metrics: ThreadSafeMetrics,
        dlq: SupportsDeadLetterQueue,
        id_mapper: IDMapper | None = None,
    ):
        """Initialize ParallelRestorationOrchestrator.

        Args:
            restorer: LookerContentRestorer instance for single-item restoration
            repository: SQLite repository for reading content and saving checkpoints
            config: RestorationConfig with worker count, rate limits, checkpoint interval
            rate_limiter: Shared AdaptiveRateLimiter for coordinated API throttling
            metrics: ThreadSafeMetrics for aggregating statistics across workers
            dlq: DeadLetterQueue implementation for failed items (typically repository)
            id_mapper: Optional ID mapper for cross-instance migration

        Examples:
            >>> # Standard configuration
            >>> config = RestorationConfig(workers=8, checkpoint_interval=100)
            >>> orchestrator = ParallelRestorationOrchestrator(
            ...     restorer=restorer,
            ...     repository=repo,
            ...     config=config,
            ...     rate_limiter=AdaptiveRateLimiter(requests_per_minute=120),
            ...     metrics=ThreadSafeMetrics(),
            ...     dlq=repo,
            ... )

            >>> # High-throughput with ID mapping
            >>> config = RestorationConfig(workers=16, rate_limit_per_minute=200)
            >>> orchestrator = ParallelRestorationOrchestrator(
            ...     restorer=restorer,
            ...     repository=repo,
            ...     config=config,
            ...     rate_limiter=AdaptiveRateLimiter(requests_per_minute=200),
            ...     metrics=ThreadSafeMetrics(),
            ...     dlq=repo,
            ...     id_mapper=IDMapper(repo, "source.looker.com", "dest.looker.com"),
            ... )
        """
        self.restorer = restorer
        self.repository = repository
        self.config = config
        self.rate_limiter = rate_limiter
        self.metrics = metrics
        self.dlq = dlq
        self.id_mapper = id_mapper

        # Initialize dependency graph for restore_all ordering
        self.dependency_graph = DependencyGraph()

        logger.info(
            f"Initialized ParallelRestorationOrchestrator: "
            f"workers={config.workers}, "
            f"checkpoint_interval={config.checkpoint_interval}, "
            f"max_retries={config.max_retries}, "
            f"id_mapper={'enabled' if id_mapper else 'disabled'}"
        )

    def restore(
        self, content_type: ContentType, session_id: str, content_ids: Sequence[str] | None = None
    ) -> RestorationSummary:
        """Restore all content of a given type using parallel worker threads.

        This method orchestrates parallel restoration by:
        1. Querying SQLite for all content IDs of the specified content type
        2. Creating a ThreadPoolExecutor with config.workers threads
        3. Distributing content IDs via thread-safe queue.Queue
        4. Workers call restorer.restore_single() with rate limiting
        5. Aggregating results into RestorationSummary
        6. Saving checkpoints every config.checkpoint_interval items
        7. Handling worker errors: catch exceptions, add to DLQ after max retries

        Args:
            content_type: ContentType enum value to restore
            session_id: Unique session identifier for tracking
            content_ids: Optional sequence of content IDs to restore. If None, queries
                        the repository for all IDs of this content type.

        Returns:
            RestorationSummary with aggregated results:
            - total_items: Number of items attempted
            - success_count: Successfully restored (created + updated)
            - created_count: Items created in destination
            - updated_count: Items updated in destination
            - error_count: Items failed after max retries (added to DLQ)
            - skipped_count: Items skipped (e.g., dry_run, skip_if_modified)
            - duration_seconds: Total restoration time
            - average_throughput: Items per second
            - content_type_breakdown: Items per content type
            - error_breakdown: Errors by type

        Examples:
            >>> # Restore all dashboards
            >>> summary = orchestrator.restore(ContentType.DASHBOARD, "session-123")
            >>> print(f"Success: {summary.success_count}/{summary.total_items}")
            >>> print(f"Throughput: {summary.average_throughput:.1f} items/sec")

            >>> # Check for errors
            >>> if summary.error_count > 0:
            ...     print(f"Errors: {summary.error_breakdown}")

            >>> # Restore with dry_run
            >>> config.dry_run = True
            >>> summary = orchestrator.restore(ContentType.LOOK, "dry-run-456")
            >>> print(f"Validation: {summary.success_count} items valid")

            >>> # Restore specific content IDs (e.g., for resume)
            >>> summary = orchestrator.restore(
            ...     ContentType.DASHBOARD, "session-123", content_ids=["1", "2", "3"]
            ... )
        """
        start_time = time.time()

        logger.info(
            f"Starting parallel restoration: "
            f"content_type={content_type.name}, "
            f"session_id={session_id}, "
            f"workers={self.config.workers}, "
            f"dry_run={self.config.dry_run}"
        )

        # Step 1: Query SQLite for all content IDs of this content_type
        # Apply folder filtering if configured
        # If content_ids is provided, use it directly (e.g., for resume)
        content_ids_to_restore: set[str] | None
        if content_ids is not None:
            content_ids_to_restore = set(content_ids)
            logger.info(f"Using provided content IDs: {len(content_ids_to_restore)} items")
        elif self.config.folder_ids and content_type in [
            ContentType.DASHBOARD,
            ContentType.LOOK,
            ContentType.BOARD,
        ]:
            # Folder-filtered query for folder-aware content types
            content_ids_to_restore = self.repository.get_content_ids_in_folders(
                content_type.value, set(self.config.folder_ids), include_deleted=False
            )
            logger.info(
                f"Found {len(content_ids_to_restore)} {content_type.name} items "
                f"in {len(self.config.folder_ids)} folder(s)"
            )
        elif content_type == ContentType.FOLDER:
            # Restoring folders: use folder_ids directly if specified
            if self.config.folder_ids:
                content_ids_to_restore = set(self.config.folder_ids)
                logger.info(f"Restoring {len(content_ids_to_restore)} folder(s) by ID")
            else:
                content_ids_to_restore = self.repository.get_content_ids(content_type.value)
        else:
            # No folder filter for this type (or no folder_ids configured)
            content_ids_to_restore = self.repository.get_content_ids(content_type.value)

        if not content_ids_to_restore:
            logger.info(f"No {content_type.name} content found in repository")
            return self._create_empty_summary(session_id, content_type)

        total_items = len(content_ids_to_restore)
        logger.info(f"Found {total_items} {content_type.name} items to restore")

        # Set expected total in metrics for progress tracking
        self.metrics.set_total(content_type.value, total_items)

        # Initialize result aggregation
        results_lock = threading.Lock()
        success_count = 0
        created_count = 0
        updated_count = 0
        error_count = 0
        skipped_count = 0
        error_breakdown: dict[str, int] = {}
        completed_ids: list[str] = []

        # Step 2: Create ThreadPoolExecutor with config.workers threads
        # Step 3: Distribute work via queue
        work_queue: queue.Queue[str] = queue.Queue()
        for content_id in content_ids_to_restore:
            work_queue.put(content_id)

        def worker() -> None:
            """Worker function that processes items from the queue."""
            nonlocal success_count, created_count, updated_count, error_count, skipped_count

            while True:
                try:
                    # Get next content_id from queue (non-blocking)
                    content_id = work_queue.get_nowait()
                except queue.Empty:
                    # No more work
                    break

                try:
                    # Step 4: Call restorer.restore_single() with rate limiting
                    result = self.restorer.restore_single(
                        content_id, content_type, dry_run=self.config.dry_run
                    )

                    # Aggregate results
                    with results_lock:
                        if result.status == "created":
                            success_count += 1
                            created_count += 1
                            completed_ids.append(content_id)
                        elif result.status == "updated":
                            success_count += 1
                            updated_count += 1
                            completed_ids.append(content_id)
                        elif result.status == "success":
                            # Dry run success
                            success_count += 1
                            completed_ids.append(content_id)
                        elif result.status == "skipped":
                            skipped_count += 1
                            completed_ids.append(content_id)
                        elif result.status == "failed":
                            error_count += 1

                            # Track error breakdown by error type
                            if result.error_message:
                                error_type = self._extract_error_type(result.error_message)
                                error_breakdown[error_type] = error_breakdown.get(error_type, 0) + 1

                            # Step 6: Add to DLQ after max retries exhausted
                            if result.retry_count >= self.config.max_retries:
                                self._add_to_dlq(
                                    session_id=session_id,
                                    content_id=content_id,
                                    content_type=content_type,
                                    result=result,
                                )

                        # Update metrics
                        self.metrics.increment_processed(content_type.value, count=1)

                        # Step 5: Save checkpoint every N items
                        if len(completed_ids) % self.config.checkpoint_interval == 0:
                            self._save_checkpoint(
                                session_id=session_id,
                                content_type=content_type,
                                completed_ids=completed_ids.copy(),
                                item_count=len(completed_ids),
                                error_count=error_count,
                            )
                            logger.info(
                                f"Checkpoint saved: {len(completed_ids)}/{total_items} items processed"
                            )

                except Exception as e:
                    # Step 7: Handle worker errors
                    with results_lock:
                        error_count += 1
                        error_type = type(e).__name__
                        error_breakdown[error_type] = error_breakdown.get(error_type, 0) + 1

                    logger.exception(
                        f"Unexpected error in worker processing {content_type.name} {content_id}: {e}"
                    )

                    # Record error in metrics
                    self.metrics.record_error(threading.current_thread().name, str(e))

                finally:
                    work_queue.task_done()

        # Execute workers
        with ThreadPoolExecutor(max_workers=self.config.workers) as executor:
            # Submit worker tasks
            futures = [executor.submit(worker) for _ in range(self.config.workers)]

            # Wait for all workers to complete
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.exception(f"Worker thread raised exception: {e}")

        # Save final checkpoint
        if completed_ids:
            self._save_checkpoint(
                session_id=session_id,
                content_type=content_type,
                completed_ids=completed_ids,
                item_count=len(completed_ids),
                error_count=error_count,
            )
            logger.info(f"Final checkpoint saved: {len(completed_ids)} total items completed")

        # Calculate duration and throughput
        duration_seconds = time.time() - start_time
        average_throughput = total_items / duration_seconds if duration_seconds > 0 else 0.0

        logger.info(
            f"Parallel restoration completed: {total_items} items in {duration_seconds:.1f}s "
            f"({average_throughput:.1f} items/sec) - "
            f"Success: {success_count}, Errors: {error_count}"
        )

        # Create and return RestorationSummary
        return RestorationSummary(
            session_id=session_id,
            total_items=total_items,
            success_count=success_count,
            created_count=created_count,
            updated_count=updated_count,
            error_count=error_count,
            skipped_count=skipped_count,
            duration_seconds=duration_seconds,
            average_throughput=average_throughput,
            content_type_breakdown={content_type.value: total_items},
            error_breakdown=error_breakdown,
        )

    def restore_all(self, requested_types: list[ContentType] | None = None) -> RestorationSummary:
        """Restore all content types in dependency-aware order.

        Uses DependencyGraph.get_restoration_order() to determine the correct
        restoration sequence (e.g., Users before Dashboards, Looks before Boards).
        Calls restore() for each content type sequentially, aggregating results
        across all types.

        Args:
            requested_types: Specific content types to restore. If None, restores
                           all supported types in dependency order.

        Returns:
            RestorationSummary aggregated across all content types:
            - content_type_breakdown: Items per content type
            - All other metrics summed across types

        Examples:
            >>> # Restore all content types
            >>> summary = orchestrator.restore_all()
            >>> print(f"Total items: {summary.total_items}")
            >>> print(f"Breakdown: {summary.content_type_breakdown}")

            >>> # Restore specific types in dependency order
            >>> summary = orchestrator.restore_all(
            ...     [
            ...         ContentType.FOLDER,
            ...         ContentType.DASHBOARD,
            ...         ContentType.BOARD,
            ...     ]
            ... )
            >>> # Folders restored first, then Dashboards, then Boards

            >>> # Check individual type results
            >>> for content_type, count in summary.content_type_breakdown.items():
            ...     print(f"{ContentType(content_type).name}: {count} items")
        """
        start_time = time.time()
        session_id = f"restore_all_{int(start_time)}"

        logger.info(
            f"Starting restore_all: "
            f"requested_types={[ct.name for ct in requested_types] if requested_types else 'all'}, "
            f"session_id={session_id}"
        )

        # Step 1: Get restoration order from DependencyGraph
        content_types = self.dependency_graph.get_restoration_order(requested_types)

        logger.info(f"Dependency-ordered restoration sequence: {[ct.name for ct in content_types]}")

        # Initialize aggregated results
        total_items = 0
        success_count = 0
        created_count = 0
        updated_count = 0
        error_count = 0
        skipped_count = 0
        content_type_breakdown: dict[int, int] = {}
        error_breakdown: dict[str, int] = {}

        # Step 2: Call restore() for each content type sequentially
        for content_type in content_types:
            logger.info(f"Restoring content type: {content_type.name}")

            # Use type-specific session ID for checkpointing
            type_session_id = f"{session_id}_{content_type.name}"

            try:
                summary = self.restore(content_type, type_session_id)

                # Step 3: Aggregate results
                total_items += summary.total_items
                success_count += summary.success_count
                created_count += summary.created_count
                updated_count += summary.updated_count
                error_count += summary.error_count
                skipped_count += summary.skipped_count

                # Merge content_type_breakdown
                for ct, count in summary.content_type_breakdown.items():
                    content_type_breakdown[ct] = content_type_breakdown.get(ct, 0) + count

                # Merge error_breakdown
                for error_type, count in summary.error_breakdown.items():
                    error_breakdown[error_type] = error_breakdown.get(error_type, 0) + count

                logger.info(
                    f"Completed {content_type.name}: "
                    f"{summary.success_count}/{summary.total_items} successful"
                )

            except Exception as e:
                logger.exception(f"Error restoring {content_type.name}: {e}")
                # Continue with next content type
                error_count += 1
                error_type = type(e).__name__
                error_breakdown[error_type] = error_breakdown.get(error_type, 0) + 1

        # Calculate overall duration and throughput
        duration_seconds = time.time() - start_time
        average_throughput = total_items / duration_seconds if duration_seconds > 0 else 0.0

        logger.info(
            f"restore_all completed: {total_items} total items in {duration_seconds:.1f}s "
            f"({average_throughput:.1f} items/sec) - "
            f"Success: {success_count}, Errors: {error_count}"
        )

        # Create and return aggregated RestorationSummary
        return RestorationSummary(
            session_id=session_id,
            total_items=total_items,
            success_count=success_count,
            created_count=created_count,
            updated_count=updated_count,
            error_count=error_count,
            skipped_count=skipped_count,
            duration_seconds=duration_seconds,
            average_throughput=average_throughput,
            content_type_breakdown=content_type_breakdown,
            error_breakdown=error_breakdown,
        )

    def resume(self, content_type: ContentType, session_id: str) -> RestorationSummary:
        """Resume interrupted restoration from latest checkpoint.

        Queries incomplete checkpoints for the specified session and content type,
        extracts completed_ids from checkpoint_data, filters them out from the
        full content ID list, and calls restore() with the remaining IDs.

        Args:
            content_type: ContentType enum value to resume
            session_id: Session identifier to resume from

        Returns:
            RestorationSummary for the resumed restoration (only new items)

        Examples:
            >>> # Resume interrupted restoration
            >>> summary = orchestrator.resume(
            ...     content_type=ContentType.DASHBOARD, session_id="abc-123"
            ... )
            >>> print(f"Resumed: {summary.success_count} additional items restored")

            >>> # Check if checkpoint exists
            >>> checkpoint = repo.get_latest_restoration_checkpoint(ContentType.DASHBOARD.value)
            >>> if checkpoint:
            ...     summary = orchestrator.resume(ContentType.DASHBOARD, checkpoint.session_id)
            ... else:
            ...     print("No checkpoint found, starting fresh restoration")
        """
        logger.info(
            f"Resuming restoration: content_type={content_type.name}, session_id={session_id}"
        )

        # Step 1: Query incomplete checkpoints
        checkpoint = self.repository.get_latest_restoration_checkpoint(content_type.value)

        if not checkpoint:
            logger.warning(
                f"No checkpoint found for {content_type.name} session {session_id}. "
                "Starting fresh restoration."
            )
            return self.restore(content_type, session_id)

        # Step 2: Extract completed_ids from checkpoint_data
        completed_ids = set(checkpoint.checkpoint_data.get("completed_ids", []))

        logger.info(
            f"Found checkpoint for {content_type.name}: "
            f"{len(completed_ids)} items already completed"
        )

        # Step 3: Query all content IDs and filter out completed ones
        all_content_ids = self.repository.get_content_ids(content_type.value)
        remaining_ids = [cid for cid in all_content_ids if cid not in completed_ids]

        if not remaining_ids:
            logger.info(
                f"All {len(all_content_ids)} items already completed for {content_type.name}"
            )
            # Return empty summary
            return RestorationSummary(
                session_id=session_id,
                total_items=0,
                success_count=0,
                created_count=0,
                updated_count=0,
                error_count=0,
                skipped_count=0,
                duration_seconds=0.0,
                average_throughput=0.0,
                content_type_breakdown={content_type.value: 0},
                error_breakdown={},
            )

        logger.info(
            f"Resuming {content_type.name}: "
            f"{len(remaining_ids)} items remaining "
            f"(skipped {len(completed_ids)} completed)"
        )

        # Step 4: Call restore() with remaining content IDs
        summary = self.restore(content_type, session_id, content_ids=remaining_ids)

        logger.info(
            f"Resume completed: {summary.success_count}/{summary.total_items} items restored"
        )

        return summary

    def _create_empty_summary(
        self, session_id: str, content_type: ContentType
    ) -> RestorationSummary:
        """Create empty RestorationSummary when no content found.

        Args:
            session_id: Session identifier
            content_type: ContentType enum value

        Returns:
            RestorationSummary with all counts set to zero
        """
        return RestorationSummary(
            session_id=session_id,
            total_items=0,
            success_count=0,
            created_count=0,
            updated_count=0,
            error_count=0,
            skipped_count=0,
            duration_seconds=0.0,
            average_throughput=0.0,
            content_type_breakdown={content_type.value: 0},
            error_breakdown={},
        )

    def _extract_error_type(self, error_message: str) -> str:
        """Extract error type from error message for categorization.

        Args:
            error_message: Error message string

        Returns:
            Categorized error type (e.g., "ValidationError", "RateLimitError")
        """
        # Common error patterns to extract
        if "not found" in error_message.lower():
            return "NotFoundError"
        elif "validation" in error_message.lower() or "422" in error_message:
            return "ValidationError"
        elif "rate limit" in error_message.lower() or "429" in error_message:
            return "RateLimitError"
        elif "authentication" in error_message.lower() or "401" in error_message:
            return "AuthenticationError"
        elif "authorization" in error_message.lower() or "403" in error_message:
            return "AuthorizationError"
        elif "timeout" in error_message.lower():
            return "TimeoutError"
        elif "dependency" in error_message.lower():
            return "DependencyError"
        else:
            return "APIError"

    def _save_checkpoint(
        self,
        session_id: str,
        content_type: ContentType,
        completed_ids: list[str],
        item_count: int,
        error_count: int,
    ) -> None:
        """Save restoration checkpoint to enable resume capability.

        Args:
            session_id: Unique restoration session identifier
            content_type: ContentType enum value being restored
            completed_ids: List of all completed content IDs (including from previous checkpoint)
            item_count: Number of items processed in this checkpoint interval
            error_count: Total errors encountered so far

        Examples:
            >>> # Save checkpoint every 100 items
            >>> self._save_checkpoint(
            ...     session_id="abc-123",
            ...     content_type=ContentType.DASHBOARD,
            ...     completed_ids=["1", "2", "3", ..., "100"],
            ...     item_count=100,
            ...     error_count=2,
            ... )
        """
        checkpoint = RestorationCheckpoint(
            session_id=session_id,
            content_type=content_type.value,
            checkpoint_data={"completed_ids": completed_ids},
            item_count=item_count,
            error_count=error_count,
        )

        # Save to repository
        self.repository.save_restoration_checkpoint(checkpoint)

        logger.debug(
            f"Saved checkpoint for session {session_id}: "
            f"{len(completed_ids)} total completed, {error_count} errors"
        )

    def _add_to_dlq(
        self,
        session_id: str,
        content_id: str,
        content_type: ContentType,
        result: RestorationResult,
    ) -> None:
        """Add failed item to Dead Letter Queue after max retries exhausted.

        Args:
            session_id: Restoration session identifier
            content_id: Content ID that failed
            content_type: ContentType enum value
            result: RestorationResult with error details

        Examples:
            >>> # Add to DLQ after 5 retries
            >>> self._add_to_dlq(
            ...     session_id="abc-123",
            ...     content_id="dashboard-42",
            ...     content_type=ContentType.DASHBOARD,
            ...     result=RestorationResult(
            ...         content_id="dashboard-42",
            ...         content_type=ContentType.DASHBOARD.value,
            ...         status="failed",
            ...         error_message="Missing folder_id dependency",
            ...         retry_count=5,
            ...     ),
            ... )
        """
        try:
            # Add to DLQ using the add() method
            dlq_id = self.dlq.add(
                content_id=content_id,
                content_type=content_type,
                error_message=result.error_message or "Unknown error",
                session_id=session_id,
                retry_count=result.retry_count,
            )

            logger.warning(
                f"Added to DLQ: {content_type.name} {content_id} "
                f"(dlq_id={dlq_id}, retries={result.retry_count}, "
                f"error={result.error_message})"
            )

        except Exception as e:
            logger.exception(f"Failed to add {content_type.name} {content_id} to DLQ: {e}")
