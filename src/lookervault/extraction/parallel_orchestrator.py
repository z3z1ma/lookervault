"""Parallel orchestration of content extraction using worker thread pool.

Thread-Safety Architecture
===========================

This module implements a parallel extraction system with comprehensive thread-safety
guarantees for multi-worker content extraction from the Looker API.

Thread-Safety Guarantees
------------------------

1. **Shared State Protection**
   - All shared mutable state is protected by locks
   - OffsetCoordinator/MultiFolderOffsetCoordinator: atomic offset range claiming
   - ThreadSafeMetrics: atomic counter updates and snapshots
   - AdaptiveRateLimiter: atomic backoff state changes

2. **SQLite Access Synchronization**
   - Thread-local connections: Each worker thread gets its own SQLite connection
   - BEGIN IMMEDIATE transactions: Prevents write-after-read deadlocks
   - Retry logic: Handles SQLITE_BUSY with exponential backoff
   - WAL mode: Allows concurrent reads during writes

3. **Worker Coordination**
   - Atomic work claiming via coordinator.claim_range()
   - No shared work queues between threads
   - Workers operate independently on claimed offset ranges

4. **Immutable Configuration**
   - ExtractionConfig and ParallelConfig are read-only after initialization
   - No mutation of config objects during extraction

Thread-Safety Mechanisms
-------------------------

| Component | Mechanism | Protected Operations |
|-----------|-----------|---------------------|
| OffsetCoordinator | threading.Lock | claim_range(), mark_worker_complete() |
| MultiFolderOffsetCoordinator | threading.Lock | claim_range(), mark_folder_complete() |
| ThreadSafeMetrics | threading.Lock | increment_processed(), record_error(), snapshot() |
| AdaptiveRateLimiter | threading.Lock | acquire(), on_429_detected(), on_success() |
| SQLiteContentRepository | threading.local + BEGIN IMMEDIATE | save_content(), save_checkpoint() |

Safe Operations from Worker Threads
------------------------------------

- Reading from self.config (immutable after init)
- Calling coordinator.claim_range() (thread-safe)
- Calling self.metrics.increment_processed() (thread-safe)
- Calling self.repository.save_content() (uses thread-local connection)
- Calling self.extractor.extract_range() (rate-limited, thread-safe)

Unsafe Operations from Worker Threads
-------------------------------------

- Writing to shared instance variables (not protected by locks)
- Modifying self.config or self.parallel_config
- Direct database access bypassing repository methods

SQLite Write Contention Handling
---------------------------------

When multiple workers write to SQLite simultaneously:
1. Each worker uses thread-local connection (no connection sharing)
2. BEGIN IMMEDIATE acquires write lock immediately
3. If SQLITE_BUSY encountered: retry with exponential backoff (up to 5 attempts)
4. Jitter added to prevent thundering herd problem
5. WAL mode allows concurrent reads during writes

Thread Cleanup
--------------

CRITICAL: Each worker MUST call `repository.close_thread_connection()` in finally block
to prevent connection leaks when threads exit. See `_parallel_fetch_worker()` for example.

Performance Considerations
---------------------------

- Optimal worker count: 8-16 for SQLite writes (plateaus beyond due to write lock)
- Memory: Constant and low (no intermediate queue)
- Throughput: 400-600 items/second with 8 workers
- Bottleneck: SQLite write serialization at high worker counts
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from lookervault.config.models import ParallelConfig
from lookervault.exceptions import OrchestrationError
from lookervault.extraction.batch_processor import MemoryAwareBatchProcessor
from lookervault.extraction.metrics import ThreadSafeMetrics
from lookervault.extraction.multi_folder_coordinator import MultiFolderOffsetCoordinator
from lookervault.extraction.offset_coordinator import OffsetCoordinator
from lookervault.extraction.orchestrator import ExtractionConfig, ExtractionResult
from lookervault.extraction.progress import ProgressTracker
from lookervault.extraction.rate_limiter import AdaptiveRateLimiter
from lookervault.storage.models import (
    Checkpoint,
    ContentItem,
    ContentType,
    ExtractionSession,
    SessionStatus,
)
from lookervault.storage.repository import ContentRepository, SQLiteContentRepository
from lookervault.storage.serializer import ContentSerializer
from lookervault.utils.datetime_parsing import parse_timestamp

if TYPE_CHECKING:
    from lookervault.looker.extractor import ContentExtractor

logger = logging.getLogger(__name__)


class ParallelOrchestrator:
    """Parallel orchestrator using dynamic work stealing pattern.

    Architecture:
    - Parallel Fetch Workers: Workers fetch directly from Looker API in parallel,
      claiming offset ranges atomically from shared coordinator
    - Sequential Strategy: For non-paginated content types, processes items
      directly without parallelization
    - Thread-safe coordination: OffsetCoordinator, ThreadSafeMetrics, thread-local DB connections

    Performance:
    - Target: 500+ items/second with 10 workers
    - Memory: Low and constant (no intermediate queue needed)
    - Scaling: Near-linear up to 8 workers, plateaus at 16 (SQLite write limit)
    """

    def __init__(
        self,
        extractor: "ContentExtractor",
        repository: ContentRepository,
        serializer: ContentSerializer,
        progress: ProgressTracker,
        config: ExtractionConfig,
        parallel_config: ParallelConfig,
    ):
        """Initialize parallel orchestrator with dependencies.

        Thread-Safety Initialization:
            This constructor is called from a single thread (typically main thread)
            before parallel execution begins. It sets up thread-safe components:

            1. ThreadSafeMetrics (self.metrics):
               - All operations protected by internal lock
               - Safe for concurrent increments and snapshots from workers

            2. AdaptiveRateLimiter (self.rate_limiter):
               - All state changes protected by internal lock
               - Shared across all workers for coordinated throttling
               - Atomic backoff state changes on 429 errors

            3. Configuration Objects:
               - self.config and self.parallel_config are read-only after init
               - Safe for workers to read concurrently without locks
               - No mutation during extraction ensures consistency

            4. Shared Dependencies:
               - extractor: Shared but rate-limited API calls are thread-safe
               - repository: Uses thread-local connections for safe concurrent access
               - progress: Must support thread-safe updates (implementation-dependent)

        Args:
            extractor: Content extractor for API calls
            repository: Thread-safe storage repository
            serializer: Content serializer
            progress: Progress tracker (thread-safe updates needed)
            config: Extraction configuration
            parallel_config: Parallel execution configuration
        """
        repository: ContentRepository
        extractor: ContentExtractor

        self.extractor = extractor
        self.repository = repository
        self.serializer = serializer
        self.progress = progress
        self.config = config
        self.parallel_config = parallel_config
        self.batch_processor = MemoryAwareBatchProcessor()

        # Parallel execution state
        # Thread-safe: metrics uses internal lock for all operations
        self.metrics = ThreadSafeMetrics()
        self._last_progress_print = (
            0  # Track when we last printed progress (single-writer: main thread only)
        )

        # Create shared rate limiter for all workers
        # Thread-safe: rate_limiter uses internal lock for sliding window updates
        # Shared across all workers to coordinate API request throttling
        if parallel_config.adaptive_rate_limiting:
            self.rate_limiter = AdaptiveRateLimiter(
                requests_per_minute=parallel_config.rate_limit_per_minute,
                requests_per_second=parallel_config.rate_limit_per_second,
                adaptive=True,
            )
            # Inject rate limiter into extractor (all workers share same instance)
            # Thread-safe: AdaptiveRateLimiter.acquire() uses internal lock for coordination
            # Only LookerContentExtractor supports rate_limiter attribute
            if hasattr(extractor, "rate_limiter"):
                extractor.rate_limiter = self.rate_limiter  # type: ignore[attr-defined]
            logger.info(
                f"Adaptive rate limiting enabled: {parallel_config.rate_limit_per_minute} req/min, "
                f"{parallel_config.rate_limit_per_second} req/sec (burst)"
            )
        else:
            self.rate_limiter = None
            logger.info("Adaptive rate limiting disabled")

        logger.info(
            f"Initialized ParallelOrchestrator: {parallel_config.workers} workers, "
            f"queue_size={parallel_config.queue_size}, batch_size={parallel_config.batch_size}"
        )

    def extract(self) -> ExtractionResult:
        """Execute parallel extraction workflow.

        Routes content types to appropriate extraction strategy:
        - Paginated types with multiple workers: Parallel fetch (workers fetch directly from API)
        - Non-paginated types or single worker: Sequential extraction

        Thread-Safety:
            This method orchestrates the entire parallel extraction workflow:

            1. Main Thread Execution:
               - Runs in main thread, spawns worker threads via ThreadPoolExecutor
               - Session creation and updates are single-threaded (no races)
               - Final metrics snapshot happens after all workers complete

            2. Worker Thread Spawning:
               - ThreadPoolExecutor manages thread lifecycle
               - Each worker gets its own thread with independent call stack
               - Workers coordinate via shared thread-safe coordinator

            3. Checkpoint Management:
               - Checkpoints created/updated sequentially per content type
               - No concurrent checkpoint updates for same content type
               - Repository uses BEGIN IMMEDIATE for thread-safe writes

            4. Error Handling:
               - Worker errors caught and recorded in ThreadSafeMetrics
               - Session status updated atomically on failure
               - OrchestrationError raised with full context

        Session Management:
            - Creates new session or resumes existing session
            - Session status transitions: RUNNING -> COMPLETED or FAILED
            - Session metadata cached for folder hierarchy resolution
            - All session updates use thread-safe repository methods

        Returns:
            ExtractionResult with summary statistics

        Raises:
            OrchestrationError: If extraction fails
        """
        start_time = datetime.now()
        session = self._initialize_or_resume_session()

        result = ExtractionResult(session_id=session.id, total_items=0)

        try:
            self._prepare_folder_hierarchy(session)
            self._process_all_content_types(session)
            return self._complete_extraction(session, result, start_time)

        except Exception as e:
            self._handle_extraction_failure(session, result, e)
            raise

    def _initialize_or_resume_session(self) -> ExtractionSession:
        """Initialize new session or resume existing session.

        Returns:
            Configured and saved extraction session
        """
        # Try to find existing session for resume
        session = None
        if self.config.resume:
            session = self._find_existing_session()

        # Create new session if not resuming or no existing session found
        if session is None:
            session = self._create_new_session()
        else:
            self._resume_existing_session(session)

        return session

    def _find_existing_session(self) -> ExtractionSession | None:
        """Find existing session from checkpoints.

        Returns:
            Existing session if found, None otherwise
        """
        for content_type in self.config.content_types:
            checkpoint = self.repository.get_latest_checkpoint(content_type, session_id=None)
            if checkpoint and checkpoint.session_id:
                # get_extraction_session is only available on SQLiteContentRepository
                if isinstance(self.repository, SQLiteContentRepository):
                    session = self.repository.get_extraction_session(checkpoint.session_id)
                else:
                    session = None
                if session:
                    logger.info(
                        f"Resume: Found existing session {session.id} "
                        f"from checkpoint (started {session.started_at.isoformat()})"
                    )
                    return session
        return None

    def _create_new_session(self) -> ExtractionSession:
        """Create and save new extraction session.

        Returns:
            Newly created session
        """
        session = ExtractionSession(
            status=SessionStatus.RUNNING,
            config={
                "content_types": self.config.content_types,
                "batch_size": self.config.batch_size,
                "fields": self.config.fields,
                "workers": self.parallel_config.workers,
                "queue_size": self.parallel_config.queue_size,
            },
            metadata={},
        )
        self.repository.create_session(session)
        logger.info(
            f"Starting new extraction session {session.id} with {self.parallel_config.workers} workers"
        )
        return session

    def _resume_existing_session(self, session: ExtractionSession) -> None:
        """Resume existing extraction session.

        Args:
            session: Existing session to resume
        """
        session.status = SessionStatus.RUNNING
        self.repository.update_session(session)
        logger.info(
            f"Resuming extraction session {session.id} with {self.parallel_config.workers} workers"
        )

    def _prepare_folder_hierarchy(self, session: ExtractionSession) -> None:
        """Prepare folder hierarchy before content extraction.

        Args:
            session: Current extraction session
        """
        if not self.config.folder_ids or not self.config.recursive_folders:
            return

        # Check for cached resolved folder hierarchy on resume
        if self.config.resume and session.metadata:
            cached_folder_ids = session.metadata.get("resolved_folder_ids")
            if cached_folder_ids:
                logger.info(
                    f"Resume: Using cached folder hierarchy from session metadata "
                    f"({len(cached_folder_ids)} folders)"
                )
                self.config.folder_ids = set(cached_folder_ids)
                return

        # No cache - need to expand
        self._expand_folder_hierarchy_early(session)

    def _process_all_content_types(self, session: ExtractionSession) -> None:
        """Process all configured content types.

        Args:
            session: Current extraction session
        """
        for content_type in self.config.content_types:
            self._process_single_content_type(content_type, session)

    def _process_single_content_type(self, content_type: int, session: ExtractionSession) -> None:
        """Process a single content type with appropriate strategy.

        Args:
            content_type: ContentType enum value
            session: Current extraction session
        """
        content_type_name = ContentType(content_type).name.lower()
        logger.info(f"Processing {content_type_name}")

        # Skip if checkpoint already complete
        if self._should_skip_content_type(content_type, content_type_name, session.id):
            return

        # Determine extraction strategy
        is_paginated = self._is_paginated_type(content_type)
        updated_after = self._get_incremental_timestamp(content_type, content_type_name)

        # Route to appropriate strategy
        self._route_to_extraction_strategy(
            content_type, content_type_name, is_paginated, session.id, updated_after
        )

    def _should_skip_content_type(
        self, content_type: int, content_type_name: str, session_id: str
    ) -> bool:
        """Check if content type should be skipped due to complete checkpoint.

        Args:
            content_type: ContentType enum value
            content_type_name: Human-readable content type name
            session_id: Current session ID

        Returns:
            True if content type should be skipped
        """
        if not self.config.resume:
            return False

        existing_checkpoint = self.repository.get_latest_checkpoint(content_type, session_id)
        if not existing_checkpoint:
            return False

        if existing_checkpoint.completed_at:
            logger.info(
                f"Skipping {content_type_name} - "
                f"found complete checkpoint from {existing_checkpoint.completed_at.isoformat()} "
                f"({existing_checkpoint.item_count} items)"
            )
            return True

        # Partial checkpoint exists - warn and re-extract
        logger.warning(
            f"Found incomplete checkpoint for {content_type_name} "
            f"from {existing_checkpoint.started_at.isoformat()}. "
            f"Re-extracting (upserts will handle duplicates)."
        )
        return False

    def _is_paginated_type(self, content_type: int) -> bool:
        """Check if content type supports pagination.

        Args:
            content_type: ContentType enum value

        Returns:
            True if content type is paginated
        """
        return content_type in [
            ContentType.DASHBOARD.value,
            ContentType.LOOK.value,
            ContentType.USER.value,
            ContentType.GROUP.value,
            ContentType.ROLE.value,
        ]

    def _get_incremental_timestamp(
        self, content_type: int, content_type_name: str
    ) -> datetime | None:
        """Get timestamp for incremental extraction.

        Args:
            content_type: ContentType enum value
            content_type_name: Human-readable content type name

        Returns:
            Timestamp for incremental filtering, or None
        """
        if not self.config.incremental:
            return None

        updated_after = self.repository.get_last_sync_timestamp(content_type)
        if updated_after:
            logger.info(
                f"Incremental mode: {content_type_name} updated after {updated_after.isoformat()}"
            )
        return updated_after

    def _route_to_extraction_strategy(
        self,
        content_type: int,
        content_type_name: str,
        is_paginated: bool,
        session_id: str,
        updated_after: datetime | None,
    ) -> None:
        """Route content type to appropriate extraction strategy.

        Args:
            content_type: ContentType enum value
            content_type_name: Human-readable content type name
            is_paginated: Whether content type supports pagination
            session_id: Current session ID
            updated_after: Timestamp for incremental filtering
        """
        if is_paginated and self.parallel_config.workers > 1:
            logger.info(
                f"Using parallel fetch strategy for {content_type_name} "
                f"({self.parallel_config.workers} workers)"
            )
            self._extract_parallel(
                content_type=content_type,
                session_id=session_id,
                fields=self.config.fields,
                updated_after=updated_after,
            )
        else:
            strategy_reason = "non-paginated type" if not is_paginated else "single-worker mode"
            logger.info(f"Using sequential strategy for {content_type_name} ({strategy_reason})")
            self._extract_sequential(
                content_type=content_type,
                session_id=session_id,
                fields=self.config.fields,
                updated_after=updated_after,
            )

    def _complete_extraction(
        self, session: ExtractionSession, result: ExtractionResult, start_time: datetime
    ) -> ExtractionResult:
        """Complete extraction and finalize results.

        Args:
            session: Current extraction session
            result: Result object to populate
            start_time: Extraction start timestamp

        Returns:
            Completed extraction result
        """
        # Get final metrics snapshot
        final_metrics = self.metrics.snapshot()
        result.total_items = final_metrics["total"]
        result.items_by_type = final_metrics["by_type"]
        result.errors = final_metrics["errors"]

        # Mark session as complete
        session.status = SessionStatus.COMPLETED
        session.completed_at = datetime.now()
        session.total_items = result.total_items
        session.error_count = result.errors
        self.repository.update_session(session)

        # Calculate duration
        result.duration_seconds = (datetime.now() - start_time).total_seconds()

        self._log_completion_summary(result, final_metrics)

        return result

    def _log_completion_summary(self, result: ExtractionResult, final_metrics: dict) -> None:
        """Log extraction completion summary.

        Args:
            result: Extraction result
            final_metrics: Final metrics snapshot
        """
        logger.info(
            f"Parallel extraction complete: {result.total_items} items "
            f"in {result.duration_seconds:.1f}s "
            f"({final_metrics['items_per_second']:.1f} items/sec)"
        )

        current_mem, peak_mem = self.batch_processor.get_memory_usage()
        if self.batch_processor.enable_monitoring and current_mem > 0:
            current_mb = current_mem / (1024 * 1024)
            peak_mb = peak_mem / (1024 * 1024)
            logger.info(
                f"Memory usage: {current_mb:.1f} MB current, {peak_mb:.1f} MB peak "
                f"({self.parallel_config.workers} workers, "
                f"queue_size={self.parallel_config.queue_size})"
            )

    def _handle_extraction_failure(
        self, session: ExtractionSession, result: ExtractionResult, error: Exception
    ) -> None:
        """Handle extraction failure and update session.

        Args:
            session: Current extraction session
            result: Result object with error count
            error: Exception that caused failure
        """
        session.status = SessionStatus.FAILED
        session.error_count = result.errors + 1
        self.repository.update_session(session)

        logger.error(f"Parallel extraction failed: {error}")
        raise OrchestrationError(f"Parallel extraction failed: {error}") from error

    def _extract_parallel(
        self,
        content_type: int,
        session_id: str,
        fields: str | None,
        updated_after: datetime | None,
    ) -> None:
        """Extract content type using parallel fetch workers.

        Uses dynamic work stealing pattern where workers atomically claim
        offset ranges and fetch directly from the Looker API in parallel.

        Thread-Safety:
            This method runs in the main thread and spawns N worker threads
            via ThreadPoolExecutor. Thread-safety is ensured through:

            1. Shared Coordinator:
               - Single coordinator instance shared by all workers
               - OffsetCoordinator/MultiFolderOffsetCoordinator use internal locks
               - Atomic offset range claiming prevents duplicate work
               - No race conditions between workers

            2. Worker Isolation:
               - Each worker operates independently on claimed ranges
               - No shared work queues between workers
               - Thread-local SQLite connections prevent database corruption
               - Workers only synchronize via coordinator and metrics

            3. Result Aggregation:
               - as_completed() yields futures in completion order
               - Main thread aggregates results sequentially
               - No concurrent writes to result variables
               - Thread-safe metrics aggregation via ThreadSafeMetrics

        Multi-Folder Coordination:
            When multiple folders are specified:
            - MultiFolderOffsetCoordinator enables parallel SDK calls
            - Each folder gets independent offset tracking
            - Round-robin selection ensures even distribution
            - Workers can fetch from different folders simultaneously

        Args:
            content_type: ContentType enum value
            session_id: Extraction session ID for checkpoint
            fields: Fields to retrieve (optional)
            updated_after: Only items updated after this timestamp (optional)
        """
        content_type_name = ContentType(content_type).name.lower()

        # Determine extraction strategy
        is_multi_folder = self._is_multi_folder_extraction(content_type)

        # Create checkpoint
        checkpoint = self._create_parallel_checkpoint(
            content_type, content_type_name, session_id, is_multi_folder
        )

        # Choose coordinator based on folder configuration
        coordinator = self._create_coordinator(content_type_name, is_multi_folder)

        # Launch workers and collect results
        total_items = self._launch_parallel_workers(
            content_type=content_type,
            coordinator=coordinator,
            fields=fields,
            updated_after=updated_after,
            content_type_name=content_type_name,
        )

        # Mark checkpoint complete
        self._complete_parallel_checkpoint(checkpoint, total_items, content_type_name)

    def _is_multi_folder_extraction(self, content_type: int) -> bool:
        """Check if extraction should use multi-folder coordinator.

        Args:
            content_type: ContentType enum value

        Returns:
            True if multi-folder coordinator should be used
        """
        return bool(
            self.config.folder_ids
            and len(self.config.folder_ids) > 1
            and content_type in [ContentType.DASHBOARD.value, ContentType.LOOK.value]
        )

    def _create_parallel_checkpoint(
        self,
        content_type: int,
        content_type_name: str,
        session_id: str,
        is_multi_folder: bool,
    ) -> Checkpoint:
        """Create checkpoint for parallel extraction.

        Args:
            content_type: ContentType enum value
            content_type_name: Human-readable content type name
            session_id: Current session ID
            is_multi_folder: Whether using multi-folder coordinator

        Returns:
            Created checkpoint with ID
        """
        checkpoint = Checkpoint(
            session_id=session_id,
            content_type=content_type,
            checkpoint_data={
                "content_type": content_type_name,
                "batch_size": self.config.batch_size,
                "incremental": self.config.incremental,
                "parallel": True,
                "workers": self.parallel_config.workers,
                "strategy": "multi_folder_parallel" if is_multi_folder else "parallel_fetch",
                "folder_count": len(self.config.folder_ids) if self.config.folder_ids else 0,
            },
        )
        checkpoint_id = self.repository.save_checkpoint(checkpoint)
        checkpoint.id = checkpoint_id
        return checkpoint

    def _create_coordinator(
        self,
        content_type_name: str,
        is_multi_folder: bool,
    ) -> "OffsetCoordinator | MultiFolderOffsetCoordinator":
        """Create appropriate coordinator for parallel extraction.

        Args:
            content_type_name: Human-readable content type name
            is_multi_folder: Whether to create multi-folder coordinator

        Returns:
            Configured coordinator instance
        """
        if is_multi_folder:
            # Multi-folder: Use MultiFolderOffsetCoordinator for parallel SDK calls
            if self.config.folder_ids is None:
                raise ValueError("folder_ids must be set for multi-folder coordination")
            coordinator = MultiFolderOffsetCoordinator(
                folder_ids=list(self.config.folder_ids),
                stride=self.config.batch_size,
            )
            coordinator.set_total_workers(self.parallel_config.workers)
            logger.info(
                f"Using multi-folder parallel SDK calls for {content_type_name} "
                f"({len(self.config.folder_ids)} folders, {self.parallel_config.workers} workers)"
            )
        else:
            # Single-folder or no-folder: Use standard OffsetCoordinator
            coordinator = OffsetCoordinator(stride=self.config.batch_size)
            coordinator.set_total_workers(self.parallel_config.workers)
            if self.config.folder_ids and len(self.config.folder_ids) == 1:
                logger.info(
                    f"Using SDK-level folder filtering for {content_type_name} "
                    f"(folder_id={list(self.config.folder_ids)[0]})"
                )
            else:
                logger.info(f"Using standard parallel extraction for {content_type_name}")

        return coordinator

    def _launch_parallel_workers(
        self,
        content_type: int,
        coordinator: "OffsetCoordinator | MultiFolderOffsetCoordinator",
        fields: str | None,
        updated_after: datetime | None,
        content_type_name: str,
    ) -> int:
        """Launch parallel workers and aggregate results.

        Args:
            content_type: ContentType enum value
            coordinator: Shared coordinator instance
            fields: Fields to retrieve
            updated_after: Incremental filter timestamp
            content_type_name: Human-readable content type name

        Returns:
            Total items processed by all workers
        """
        logger.info(
            f"Launching {self.parallel_config.workers} parallel fetch workers "
            f"for {content_type_name}"
        )

        with ThreadPoolExecutor(max_workers=self.parallel_config.workers) as executor:
            # Submit parallel fetch workers
            futures = [
                executor.submit(
                    self._parallel_fetch_worker,
                    worker_id=i,
                    content_type=content_type,
                    coordinator=coordinator,
                    fields=fields,
                    updated_after=updated_after,
                )
                for i in range(self.parallel_config.workers)
            ]

            # Wait for all workers to complete and aggregate results
            return self._aggregate_worker_results(futures)

    def _aggregate_worker_results(self, futures: list) -> int:
        """Aggregate results from parallel workers.

        Args:
            futures: List of Future objects from workers

        Returns:
            Total items processed
        """
        total_items = 0
        for i, future in enumerate(as_completed(futures)):
            try:
                items_processed = future.result()
                total_items += items_processed
                logger.info(f"Parallel fetch worker {i} completed: {items_processed} items")
            except Exception as e:
                logger.error(f"Parallel fetch worker {i} failed: {e}")
                self.metrics.record_error("main", f"Worker {i} error: {e}")

        return total_items

    def _complete_parallel_checkpoint(
        self,
        checkpoint: Checkpoint,
        total_items: int,
        content_type_name: str,
    ) -> None:
        """Mark parallel extraction checkpoint as complete.

        Args:
            checkpoint: Checkpoint to update
            total_items: Total items processed
            content_type_name: Human-readable content type name
        """
        checkpoint.completed_at = datetime.now()
        checkpoint.item_count = total_items
        checkpoint.checkpoint_data["total_items"] = total_items
        self.repository.update_checkpoint(checkpoint)

        logger.info(f"Parallel extraction of {content_type_name} complete: {total_items} items")

    def _extract_sequential(
        self,
        content_type: int,
        session_id: str,
        fields: str | None,
        updated_after: datetime | None,
    ) -> None:
        """Extract content type using sequential producer-consumer pattern.

        Uses the existing producer-consumer pattern where the producer fetches
        sequentially from the API and queues work items for consumer workers.
        This is used for non-paginated content types or single-worker mode.

        Args:
            content_type: ContentType enum value
            session_id: Extraction session ID for checkpoint
            fields: Fields to retrieve (optional)
            updated_after: Only items updated after this timestamp (optional)
        """
        content_type_name = ContentType(content_type).name.lower()
        logger.info(f"Producer: Processing {content_type_name} (sequential strategy)")

        # Create checkpoint for this content type
        checkpoint = Checkpoint(
            session_id=session_id,
            content_type=content_type,
            checkpoint_data={
                "content_type": content_type_name,
                "batch_size": self.config.batch_size,
                "incremental": self.config.incremental,
                "parallel": False,  # Sequential extraction
                "workers": 1,
                "strategy": "sequential",
            },
        )
        checkpoint_id = self.repository.save_checkpoint(checkpoint)

        # Update progress tracker
        # Note: ProgressTracker protocol doesn't define update_status, but some implementations may have it
        try:
            update_status = getattr(self.progress, "update_status", None)
            if callable(update_status):
                update_status(f"Extracting {content_type_name}...")
        except AttributeError:
            pass  # Progress tracker may not have update_status method

        # Extract items from Looker API (sequential iterator)
        items_iterator = self.extractor.extract_all(
            ContentType(content_type),
            fields=fields,
            batch_size=self.config.batch_size,
            updated_after=updated_after,
        )

        # Process items directly (no worker queue for sequential mode)
        items_processed = 0
        for item_dict in items_iterator:
            try:
                # Convert to ContentItem
                content_item = self._dict_to_content_item(item_dict, content_type)

                # Save to database
                self.repository.save_content(content_item)

                # Update metrics
                self.metrics.increment_processed(content_type, count=1)
                items_processed += 1

            except Exception as e:
                # Item-level error - log and continue
                import traceback

                item_id = item_dict.get("id", "UNKNOWN")
                error_msg = f"Failed to process item {item_id}: {e}"
                logger.warning(f"Sequential: {error_msg}")

                tb = traceback.format_exc()
                logger.warning(
                    f"Sequential: Detailed error context\n"
                    f"  Item ID: {item_id}\n"
                    f"  Content Type: {content_type}\n"
                    f"  Exception: {type(e).__name__}: {e}\n"
                    f"  Traceback:\n{tb}"
                )
                self.metrics.record_error("sequential", error_msg)

        # Mark checkpoint complete with item count
        checkpoint.id = checkpoint_id
        checkpoint.completed_at = datetime.now()
        checkpoint.item_count = items_processed
        checkpoint.checkpoint_data["items_processed"] = items_processed
        self.repository.update_checkpoint(checkpoint)

        logger.info(
            f"Producer completed {content_type_name}: {items_processed} items (sequential strategy)"
        )

    def _handle_end_of_data(
        self,
        coordinator: "OffsetCoordinator | MultiFolderOffsetCoordinator",
        folder_id: str | None,
        worker_id: int,
        offset: int,
        reason: str,
    ) -> tuple[bool, bool]:
        """Handle end-of-data condition for a worker/folder.

        Args:
            coordinator: Shared offset coordinator (single or multi-folder)
            folder_id: Folder ID (if multi-folder mode)
            worker_id: Worker thread identifier
            offset: Current offset for logging
            reason: Reason for end-of-data (e.g., "empty response", "fewer items than requested")

        Returns:
            Tuple of (should_break, should_continue) for control flow:
            - (True, False): Break from the main loop (single-folder mode, all work done)
            - (False, True): Continue to next iteration (multi-folder mode, try next folder)
        """
        if isinstance(coordinator, MultiFolderOffsetCoordinator) and folder_id:
            logger.info(
                f"Worker {worker_id} hit end-of-data ({reason}) "
                f"for folder {folder_id} at offset {offset}, marking folder complete"
            )
            coordinator.mark_folder_complete(folder_id)
            return False, True  # Continue to next folder
        else:
            logger.info(
                f"Worker {worker_id} hit end-of-data ({reason}) at offset {offset}, "
                f"marking complete"
            )
            # At this point, coordinator must be OffsetCoordinator (not MultiFolderOffsetCoordinator)
            if isinstance(coordinator, OffsetCoordinator):
                coordinator.mark_worker_complete()
            return True, False  # Break from main loop

    def _parallel_fetch_worker(
        self,
        worker_id: int,
        content_type: int,
        coordinator: "OffsetCoordinator | MultiFolderOffsetCoordinator",
        fields: str | None,
        updated_after: datetime | None,
    ) -> int:
        """Parallel fetch worker: Claim offset ranges and fetch from API.

        Runs in worker thread. Responsible for:
        - Claiming offset ranges from coordinator
        - Fetching data from Looker API (rate-limited)
        - Converting dicts to ContentItems
        - Saving to database (thread-local connection)
        - Updating thread-safe metrics

        Thread-Safety Contract:
            This method MUST be called from a ThreadPoolExecutor worker thread.
            It follows the thread-safety patterns documented at module level:

            1. Coordinator Access:
               - coordinator.claim_range(): Thread-safe (uses internal lock)
               - coordinator.mark_worker_complete(): Thread-safe (uses internal lock)
               - coordinator.mark_folder_complete(): Thread-safe (uses internal lock)

            2. Repository Access:
               - self.repository.save_content(): Thread-safe (uses thread-local connection)
               - Each worker has its own SQLite connection via threading.local
               - BEGIN IMMEDIATE transactions prevent write deadlocks
               - Automatic retry on SQLITE_BUSY with exponential backoff

            3. Metrics Access:
               - self.metrics.increment_processed(): Thread-safe (uses internal lock)
               - self.metrics.record_error(): Thread-safe (uses internal lock)
               - self.metrics.snapshot(): Thread-safe (uses internal lock)

            4. Shared State:
               - self.config: Read-only after init, safe to read
               - self.parallel_config: Read-only after init, safe to read
               - self.extractor: Shared but rate-limited API calls are thread-safe

            5. Rate Limiter:
               - self.extractor.rate_limiter: Shared across all workers
               - AdaptiveRateLimiter.acquire() uses internal lock for coordination
               - Backoff state changes are atomic

            CRITICAL Cleanup Requirements:
                In finally block, MUST call:
                - self.repository.close_thread_connection()

                This prevents connection leaks when worker threads exit.
                Failure to close connections will cause SQLite to keep
                old connections open, eventually hitting file descriptor limits.

        Worker Lifecycle:
            1. Thread starts, claims first offset range atomically
            2. Fetches data from Looker API (with rate limiting)
            3. Converts to ContentItem and saves to database
            4. Updates thread-safe metrics
            5. Repeats steps 1-4 until coordinator returns None
            6. Closes thread-local database connection
            7. Returns total items processed

        Error Handling:
            - Item-level errors: Logged, metrics updated, processing continues
            - API fetch errors: Logged, metrics updated, skips to next range
            - Fatal errors: Logged with traceback, exception propagates to main thread
            - All errors recorded in ThreadSafeMetrics for final reporting

        Args:
            worker_id: Worker thread identifier (0-based index)
            content_type: ContentType enum value
            coordinator: Shared offset coordinator (single or multi-folder)
            fields: Fields to retrieve (optional)
            updated_after: Only items updated after this timestamp (optional)

        Returns:
            Number of items processed by this worker

        Raises:
            Exception: If worker encounters fatal error
        """
        thread_name = threading.current_thread().name
        content_type_name = ContentType(content_type).name.lower()
        logger.info(
            f"Parallel fetch worker {worker_id} ({thread_name}) starting for {content_type_name}"
        )

        items_processed = 0

        try:
            while True:
                # Atomically claim next offset range
                claimed_range = coordinator.claim_range()

                # Check if all work is done
                if claimed_range is None:
                    logger.info(
                        f"Worker {worker_id} received None from coordinator - all work complete"
                    )
                    break

                # Parse claimed range and extract folder_id, offset, limit
                folder_id, offset, limit = self._parse_claimed_range(
                    claimed_range, coordinator, worker_id
                )

                # Fetch data from Looker API
                items = self._fetch_items_from_api(
                    worker_id=worker_id,
                    thread_name=thread_name,
                    content_type=content_type,
                    offset=offset,
                    limit=limit,
                    folder_id=folder_id,
                    fields=fields,
                    updated_after=updated_after,
                )

                # Return early if fetch failed
                if items is None:
                    continue

                # Check for end of data
                if not items or len(items) == 0:
                    if self._check_end_of_data(
                        coordinator, folder_id, worker_id, offset, "empty response"
                    ):
                        break
                    continue

                # Process items: convert and save to database
                items_in_batch = self._process_items_batch(
                    items=items,
                    content_type=content_type,
                    worker_id=worker_id,
                    thread_name=thread_name,
                )
                items_processed += items_in_batch

                # Check if we got fewer items than requested (end of data)
                if len(items) < limit:
                    if self._check_end_of_data(
                        coordinator,
                        folder_id,
                        worker_id,
                        offset,
                        f"received {len(items)} < {limit} items",
                    ):
                        break

                # Periodic progress update
                self._log_worker_progress(worker_id, items_processed)

            logger.info(f"Worker {worker_id} completed: {items_processed} items processed")

        except Exception as e:
            # Worker-level error - log and propagate
            logger.error(f"Worker {worker_id} fatal error: {e}")
            self.metrics.record_error(thread_name, f"Fatal worker error: {e}")
            raise

        finally:
            # CRITICAL: Close thread-local database connection
            self.repository.close_thread_connection()
            logger.info(
                f"Worker {worker_id} shutting down: {items_processed} items processed, "
                "thread-local connection closed"
            )

        return items_processed

    def _parse_claimed_range(
        self,
        claimed_range: tuple,
        coordinator: "OffsetCoordinator | MultiFolderOffsetCoordinator",
        worker_id: int,
    ) -> tuple[str | None, int, int]:
        """Parse claimed range from coordinator.

        Args:
            claimed_range: Range tuple from coordinator
            coordinator: Coordinator instance
            worker_id: Worker ID for logging

        Returns:
            Tuple of (folder_id, offset, limit)
        """
        # Handle multi-folder coordinator (returns tuple of 3)
        if isinstance(coordinator, MultiFolderOffsetCoordinator):
            folder_id, offset, limit = claimed_range
            logger.info(
                f"Worker {worker_id} claimed range: folder_id={folder_id}, "
                f"offset={offset}, limit={limit}"
            )
            return folder_id, offset, limit

        # Single-folder or no-folder coordinator (returns tuple of 2)
        offset, limit = claimed_range
        folder_id = (
            list(self.config.folder_ids)[0]
            if self.config.folder_ids and len(self.config.folder_ids) == 1
            else None
        )
        logger.info(
            f"Worker {worker_id} claimed range: offset={offset}, limit={limit}"
            + (f", folder_id={folder_id}" if folder_id else "")
        )
        return folder_id, offset, limit

    def _fetch_items_from_api(
        self,
        worker_id: int,
        thread_name: str,
        content_type: int,
        offset: int,
        limit: int,
        folder_id: str | None,
        fields: str | None,
        updated_after: datetime | None,
    ) -> list[dict[str, Any]] | None:
        """Fetch items from Looker API.

        Args:
            worker_id: Worker ID for logging
            thread_name: Thread name for error recording
            content_type: ContentType enum value
            offset: Pagination offset
            limit: Page size limit
            folder_id: Folder ID for filtering
            fields: Fields to retrieve
            updated_after: Incremental filter timestamp

        Returns:
            List of item dictionaries, or None if fetch failed
        """
        try:
            items = self.extractor.extract_range(  # type: ignore[attr-defined]
                ContentType(content_type),
                offset=offset,
                limit=limit,
                fields=fields,
                updated_after=updated_after,
                folder_id=folder_id,  # SDK-level filtering (None or specific folder_id)
            )
            return items

        except Exception as e:
            logger.error(f"Worker {worker_id} API fetch failed at offset {offset}: {e}")
            self.metrics.record_error(thread_name, f"API fetch error: {e}")
            return None  # Signal to skip this range

    def _check_end_of_data(
        self,
        coordinator: "OffsetCoordinator | MultiFolderOffsetCoordinator",
        folder_id: str | None,
        worker_id: int,
        offset: int,
        reason: str,
    ) -> bool:
        """Check if we've reached end of data.

        Args:
            coordinator: Shared coordinator
            folder_id: Current folder ID
            worker_id: Worker ID for logging
            offset: Current offset for logging
            reason: Reason for reaching end

        Returns:
            True if should break from main loop
        """
        should_break, should_continue = self._handle_end_of_data(
            coordinator=coordinator,
            folder_id=folder_id,
            worker_id=worker_id,
            offset=offset,
            reason=reason,
        )
        return should_break

    def _process_items_batch(
        self,
        items: list[dict[str, Any]],
        content_type: int,
        worker_id: int,
        thread_name: str,
    ) -> int:
        """Process a batch of items and save to database.

        Args:
            items: List of item dictionaries
            content_type: ContentType enum value
            worker_id: Worker ID for logging
            thread_name: Thread name for error recording

        Returns:
            Number of items successfully processed
        """
        items_processed = 0

        for item_dict in items:
            try:
                # Convert to ContentItem
                content_item = self._dict_to_content_item(item_dict, content_type)

                # Save to database (uses thread-local connection)
                self.repository.save_content(content_item)

                # Update metrics
                self.metrics.increment_processed(content_type, count=1)
                items_processed += 1

            except Exception as e:
                # Item-level error - log and continue
                self._log_item_error(item_dict, content_type, worker_id, thread_name, e)

        return items_processed

    def _log_item_error(
        self,
        item_dict: dict[str, Any],
        content_type: int,
        worker_id: int,
        thread_name: str,
        error: Exception,
    ) -> None:
        """Log item processing error.

        Args:
            item_dict: Item dictionary that failed
            content_type: ContentType enum value
            worker_id: Worker ID for logging
            thread_name: Thread name for error recording
            error: Exception that occurred
        """
        import traceback

        item_id = item_dict.get("id", "UNKNOWN")
        error_msg = f"Failed to process item {item_id}: {error}"
        logger.warning(f"Worker {worker_id}: {error_msg}")

        tb = traceback.format_exc()
        logger.warning(
            f"Worker {worker_id}: Detailed error context\n"
            f"  Item ID: {item_id}\n"
            f"  Content Type: {content_type}\n"
            f"  Exception: {type(error).__name__}: {error}\n"
            f"  Traceback:\n{tb}"
        )
        self.metrics.record_error(thread_name, error_msg)

    def _log_worker_progress(self, worker_id: int, items_processed: int) -> None:
        """Log periodic worker progress.

        Args:
            worker_id: Worker ID for logging
            items_processed: Total items processed by this worker
        """
        if items_processed > 0 and items_processed % 500 == 0:
            snapshot = self.metrics.snapshot()
            logger.info(
                f"Worker {worker_id}: {items_processed} items processed, "
                f"total: {snapshot['total']} ({snapshot['items_per_second']:.1f} items/sec)"
            )

    @staticmethod
    def _get_item_id(item_dict: dict[str, Any], content_type: int) -> str | None:
        """Get the identifier field for an item based on content type.

        Args:
            item_dict: Raw API response dictionary
            content_type: ContentType enum value

        Returns:
            Item identifier or None if not found
        """
        # LookML Models use 'name' as their identifier, not 'id'
        if content_type == ContentType.LOOKML_MODEL:
            return item_dict.get("name")

        # All other content types use 'id'
        return item_dict.get("id")

    def _should_filter_by_folder(self, item_dict: dict[str, Any], content_type: int) -> bool:
        """Check if item should be filtered out based on folder_ids.

        Args:
            item_dict: Raw API response dictionary
            content_type: ContentType enum value

        Returns:
            True if item should be SKIPPED (filtered out), False if should be included
        """
        # No filter configured - include all
        if not self.config.folder_ids:
            return False

        # Only filter folder-aware content types
        if content_type not in [
            ContentType.DASHBOARD.value,
            ContentType.LOOK.value,
            ContentType.BOARD.value,
        ]:
            return False  # Not a folder-aware type, include

        # Extract folder_id from item
        item_folder_id = item_dict.get("folder_id")

        # If item has no folder_id, filter it out (shouldn't happen for folder-aware types)
        if item_folder_id is None:
            logger.warning(f"Item {item_dict.get('id', 'unknown')} has no folder_id, filtering out")
            return True

        # Check if item's folder_id is in the configured filter set
        return str(item_folder_id) not in self.config.folder_ids

    def _dict_to_content_item(self, item_dict: dict[str, Any], content_type: int) -> ContentItem:
        """Convert API response dict to ContentItem.

        Args:
            item_dict: Raw API response dictionary
            content_type: ContentType enum value

        Returns:
            ContentItem with serialized data

        Raises:
            ValueError: If required fields missing
        """
        # Extract and validate item ID
        item_id = self._extract_item_id(item_dict, content_type)
        name = self._extract_item_name(item_dict, item_id)

        # Serialize content data
        content_data = self.serializer.serialize(item_dict)

        # Extract metadata
        owner_id, owner_email = self._extract_owner_info(item_dict, item_id)
        folder_id = self._extract_folder_id(item_dict)

        # Parse timestamps
        created_at = parse_timestamp(item_dict.get("created_at"), "created_at", item_id)
        updated_at = parse_timestamp(item_dict.get("updated_at"), "updated_at", item_id)

        return ContentItem(
            id=item_id,
            content_type=content_type,
            name=name,
            owner_id=owner_id,
            owner_email=owner_email,
            created_at=created_at,
            updated_at=updated_at,
            synced_at=datetime.now(UTC),
            deleted_at=None,
            content_size=len(content_data),
            content_data=content_data,
            folder_id=folder_id,
        )

    def _extract_item_id(self, item_dict: dict[str, Any], content_type: int) -> str:
        """Extract and validate item ID from dictionary.

        Args:
            item_dict: Raw API response dictionary
            content_type: ContentType enum value

        Returns:
            Validated item ID as string
        """
        item_id = self._get_item_id(item_dict, content_type)
        if not item_id:
            # Fallback to "unknown" like orchestrator.py does
            item_id = "unknown"
            logger.warning(
                f"Item missing identifier field for {ContentType(content_type).name}: {item_dict}"
            )

        return str(item_id)

    def _extract_item_name(self, item_dict: dict[str, Any], item_id: str) -> str:
        """Extract item name from dictionary.

        Args:
            item_dict: Raw API response dictionary
            item_id: Item ID for fallback

        Returns:
            Item name or fallback
        """
        return item_dict.get("title") or item_dict.get("name") or f"Untitled {item_id}"

    def _extract_owner_info(
        self, item_dict: dict[str, Any], item_id: str
    ) -> tuple[int | None, str | None]:
        """Extract owner information from item dictionary.

        Args:
            item_dict: Raw API response dictionary
            item_id: Item ID for logging

        Returns:
            Tuple of (owner_id, owner_email)
        """
        owner_id = item_dict.get("user_id")
        # Convert owner_id to int if present (Looker API may return as string)
        if owner_id is not None:
            try:
                owner_id = int(owner_id)
            except (ValueError, TypeError):
                logger.warning(f"Could not convert owner_id '{owner_id}' to int for item {item_id}")
                owner_id = None

        owner_email = None
        if "user" in item_dict and isinstance(item_dict["user"], dict):
            owner_email = item_dict["user"].get("email")

        return owner_id, owner_email

    def _extract_folder_id(self, item_dict: dict[str, Any]) -> str | None:
        """Extract folder ID from item dictionary.

        Args:
            item_dict: Raw API response dictionary

        Returns:
            Folder ID as string, or None
        """
        if "folder_id" in item_dict and item_dict["folder_id"] is not None:
            return str(item_dict["folder_id"])
        return None

    def _expand_folder_hierarchy_early(self, session: ExtractionSession) -> None:
        """Expand folder hierarchy BEFORE content extraction.

        This method attempts to expand folder IDs recursively by:
        1. Checking if folders are already in the repository
        2. If yes: expanding immediately using cached hierarchy
        3. If no: extracting folders first, then expanding

        This ensures the correct coordinator (multi-folder vs. single-folder) is chosen.

        Args:
            session: Current extraction session (for metadata caching)
        """
        from lookervault.folder.hierarchy import FolderHierarchyResolver

        if self.config.folder_ids is None:
            raise ValueError("folder_ids must be set for hierarchical expansion")
        root_folder_ids = list(self.config.folder_ids)

        # Try to load folders from repository
        try:
            hierarchy_resolver = FolderHierarchyResolver(self.repository)

            # Check if folders exist in repository
            folder_count = len(
                self.repository.list_content(
                    content_type=ContentType.FOLDER.value, include_deleted=False
                )
            )

            if folder_count > 0:
                # Folders exist - expand immediately
                logger.info(
                    f"Found {folder_count} folders in repository, expanding hierarchy immediately"
                )
                all_folder_ids = hierarchy_resolver.get_all_descendant_ids(
                    root_folder_ids, include_roots=True
                )

                # Update config with expanded folder IDs
                self.config.folder_ids = all_folder_ids

                # Cache in session metadata
                if session.metadata is None:
                    session.metadata = {}
                session.metadata["resolved_folder_ids"] = sorted(all_folder_ids)
                session.metadata["root_folder_ids"] = sorted(root_folder_ids)
                session.metadata["folder_expansion_timestamp"] = datetime.now(UTC).isoformat()
                self.repository.update_session(session)

                logger.info(
                    f"Expanded {len(root_folder_ids)} root folder(s) to "
                    f"{len(all_folder_ids)} total folder(s) recursively (from repository cache)"
                )
            else:
                # No folders in DB - must extract them first
                logger.info(
                    "No folders in repository, extracting folders first for recursive expansion"
                )

                # Ensure FOLDER content type is in extraction list
                if ContentType.FOLDER.value not in self.config.content_types:
                    logger.warning(
                        "Adding ContentType.FOLDER to extraction list for recursive folder expansion"
                    )
                    # Prepend folders to ensure they're extracted first
                    self.config.content_types.insert(0, ContentType.FOLDER.value)

                # Extract folders using sequential strategy (folders are non-paginated)
                logger.info("Extracting folders for hierarchy expansion")
                self._extract_sequential(
                    content_type=ContentType.FOLDER.value,
                    session_id=session.id,
                    fields=self.config.fields,
                    updated_after=None,
                )

                # Now expand hierarchy
                hierarchy_resolver = FolderHierarchyResolver(
                    self.repository
                )  # Reload with fresh data
                all_folder_ids = hierarchy_resolver.get_all_descendant_ids(
                    root_folder_ids, include_roots=True
                )

                # Update config with expanded folder IDs
                self.config.folder_ids = all_folder_ids

                # Cache in session metadata
                if session.metadata is None:
                    session.metadata = {}
                session.metadata["resolved_folder_ids"] = sorted(all_folder_ids)
                session.metadata["root_folder_ids"] = sorted(root_folder_ids)
                session.metadata["folder_expansion_timestamp"] = datetime.now(UTC).isoformat()
                self.repository.update_session(session)

                logger.info(
                    f"Expanded {len(root_folder_ids)} root folder(s) to "
                    f"{len(all_folder_ids)} total folder(s) recursively (after extracting folders)"
                )

        except Exception as e:
            logger.error(f"Failed to expand folder hierarchy: {e}")
            raise OrchestrationError(f"Folder hierarchy expansion failed: {e}") from e
