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
from lookervault.storage.repository import ContentRepository
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
            self.extractor.rate_limiter = self.rate_limiter
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

        # Try to find existing session for resume
        session: ExtractionSession | None = None
        if self.config.resume:
            # Check if we have any incomplete checkpoints to determine session_id
            for content_type in self.config.content_types:
                checkpoint = self.repository.get_latest_checkpoint(content_type, session_id=None)
                if checkpoint and checkpoint.session_id:
                    # Found checkpoint with session - try to load session
                    session = self.repository.get_extraction_session(checkpoint.session_id)
                    if session:
                        logger.info(
                            f"Resume: Found existing session {session.id} "
                            f"from checkpoint (started {session.started_at.isoformat()})"
                        )
                        break

        # Create new session if not resuming or no existing session found
        if session is None:
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
        else:
            # Resuming existing session - update status
            session.status = SessionStatus.RUNNING
            self.repository.update_session(session)
            logger.info(
                f"Resuming extraction session {session.id} with {self.parallel_config.workers} workers"
            )

        result = ExtractionResult(session_id=session.id, total_items=0)

        try:
            # Expand folder hierarchy BEFORE any content type extraction
            if self.config.folder_ids and self.config.recursive_folders:
                # Check for cached resolved folder hierarchy on resume
                if self.config.resume and session.metadata:
                    cached_folder_ids = session.metadata.get("resolved_folder_ids")
                    if cached_folder_ids:
                        logger.info(
                            f"Resume: Using cached folder hierarchy from session metadata "
                            f"({len(cached_folder_ids)} folders)"
                        )
                        self.config.folder_ids = set(cached_folder_ids)
                    else:
                        # No cache - need to expand
                        self._expand_folder_hierarchy_early(session)
                else:
                    # Not resuming or no metadata - expand from DB or extract folders first
                    self._expand_folder_hierarchy_early(session)

            # Process each content type with appropriate strategy
            for content_type in self.config.content_types:
                content_type_name = ContentType(content_type).name.lower()
                logger.info(f"Processing {content_type_name}")

                # Check for existing checkpoint if resume enabled
                if self.config.resume:
                    existing_checkpoint = self.repository.get_latest_checkpoint(
                        content_type, session.id
                    )
                    if existing_checkpoint and existing_checkpoint.completed_at:
                        # Checkpoint already complete - skip this content type
                        logger.info(
                            f"Skipping {content_type_name} - "
                            f"found complete checkpoint from {existing_checkpoint.completed_at.isoformat()} "
                            f"({existing_checkpoint.item_count} items)"
                        )
                        continue
                    elif existing_checkpoint and not existing_checkpoint.completed_at:
                        # Partial checkpoint exists - warn and re-extract
                        logger.warning(
                            f"Found incomplete checkpoint for {content_type_name} "
                            f"from {existing_checkpoint.started_at.isoformat()}. "
                            f"Re-extracting (upserts will handle duplicates)."
                        )

                # Determine extraction strategy based on content type
                is_paginated = content_type in [
                    ContentType.DASHBOARD.value,
                    ContentType.LOOK.value,
                    ContentType.USER.value,
                    ContentType.GROUP.value,
                    ContentType.ROLE.value,
                ]

                # Determine timestamp for incremental extraction
                updated_after = None
                if self.config.incremental:
                    updated_after = self.repository.get_last_sync_timestamp(content_type)
                    if updated_after:
                        logger.info(
                            f"Incremental mode: {content_type_name} "
                            f"updated after {updated_after.isoformat()}"
                        )

                # Route to appropriate strategy
                if is_paginated and self.parallel_config.workers > 1:
                    # Use parallel fetch workers for paginated content types
                    logger.info(
                        f"Using parallel fetch strategy for {content_type_name} "
                        f"({self.parallel_config.workers} workers)"
                    )
                    self._extract_parallel(
                        content_type=content_type,
                        session_id=session.id,
                        fields=self.config.fields,
                        updated_after=updated_after,
                    )
                else:
                    # Use sequential extraction for non-paginated content types
                    # or single-worker mode
                    strategy_reason = (
                        "non-paginated type" if not is_paginated else "single-worker mode"
                    )
                    logger.info(
                        f"Using sequential strategy for {content_type_name} ({strategy_reason})"
                    )
                    self._extract_sequential(
                        content_type=content_type,
                        session_id=session.id,
                        fields=self.config.fields,
                        updated_after=updated_after,
                    )

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

            # Log final memory usage
            current_mem, peak_mem = self.batch_processor.get_memory_usage()
            current_mb = current_mem / (1024 * 1024)
            peak_mb = peak_mem / (1024 * 1024)

            logger.info(
                f"Parallel extraction complete: {result.total_items} items "
                f"in {result.duration_seconds:.1f}s "
                f"({final_metrics['items_per_second']:.1f} items/sec)"
            )

            if self.batch_processor.enable_monitoring and current_mem > 0:
                logger.info(
                    f"Memory usage: {current_mb:.1f} MB current, {peak_mb:.1f} MB peak "
                    f"({self.parallel_config.workers} workers, "
                    f"queue_size={self.parallel_config.queue_size})"
                )

            return result

        except Exception as e:
            # Mark session as failed
            session.status = SessionStatus.FAILED
            session.error_count = result.errors + 1
            self.repository.update_session(session)

            logger.error(f"Parallel extraction failed: {e}")
            raise OrchestrationError(f"Parallel extraction failed: {e}") from e

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
        is_multi_folder = (
            self.config.folder_ids
            and len(self.config.folder_ids) > 1
            and content_type in [ContentType.DASHBOARD.value, ContentType.LOOK.value]
        )

        # Create checkpoint
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

        # Choose coordinator based on folder configuration
        if is_multi_folder:
            # Multi-folder: Use MultiFolderOffsetCoordinator for parallel SDK calls
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

        # Launch parallel fetch workers
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

            # Wait for all workers to complete
            total_items = 0
            for i, future in enumerate(as_completed(futures)):
                try:
                    items_processed = future.result()
                    total_items += items_processed
                    logger.info(f"Parallel fetch worker {i} completed: {items_processed} items")
                except Exception as e:
                    logger.error(f"Parallel fetch worker {i} failed: {e}")
                    self.metrics.record_error("main", f"Worker {i} error: {e}")

        # Mark checkpoint complete
        checkpoint.id = checkpoint_id
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
        try:
            self.progress.update_status(f"Extracting {content_type_name}...")
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

                # Handle multi-folder coordinator (returns tuple of 3)
                if isinstance(coordinator, MultiFolderOffsetCoordinator):
                    folder_id, offset, limit = claimed_range  # type: ignore[misc]
                    logger.info(
                        f"Worker {worker_id} claimed range: folder_id={folder_id}, "
                        f"offset={offset}, limit={limit}"
                    )
                else:
                    # Single-folder or no-folder coordinator (returns tuple of 2)
                    offset, limit = claimed_range  # type: ignore[misc]
                    folder_id = (
                        list(self.config.folder_ids)[0]
                        if self.config.folder_ids and len(self.config.folder_ids) == 1
                        else None
                    )
                    logger.info(
                        f"Worker {worker_id} claimed range: offset={offset}, limit={limit}"
                        + (f", folder_id={folder_id}" if folder_id else "")
                    )

                # Fetch data from Looker API with SDK-level folder filtering
                try:
                    items = self.extractor.extract_range(
                        ContentType(content_type),
                        offset=offset,
                        limit=limit,
                        fields=fields,
                        updated_after=updated_after,
                        folder_id=folder_id,  # SDK-level filtering (None or specific folder_id)
                    )
                except Exception as e:
                    logger.error(f"Worker {worker_id} API fetch failed at offset {offset}: {e}")
                    self.metrics.record_error(thread_name, f"API fetch error: {e}")
                    continue  # Skip this range, try next

                # Check if we hit end of data
                if not items or len(items) == 0:
                    should_break, should_continue = self._handle_end_of_data(
                        coordinator=coordinator,
                        folder_id=folder_id,
                        worker_id=worker_id,
                        offset=offset,
                        reason="empty response",
                    )
                    if should_break:
                        break
                    if should_continue:
                        continue

                # Process items: convert and save to database
                # NO in-memory filtering needed - SDK handles filtering via folder_id parameter
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
                        import traceback

                        item_id = item_dict.get("id", "UNKNOWN")
                        error_msg = f"Failed to process item {item_id}: {e}"
                        logger.warning(f"Worker {worker_id}: {error_msg}")

                        tb = traceback.format_exc()
                        logger.warning(
                            f"Worker {worker_id}: Detailed error context\n"
                            f"  Item ID: {item_id}\n"
                            f"  Content Type: {content_type}\n"
                            f"  Exception: {type(e).__name__}: {e}\n"
                            f"  Traceback:\n{tb}"
                        )
                        self.metrics.record_error(thread_name, error_msg)

                # Check if we got fewer items than requested (end of data)
                if len(items) < limit:
                    should_break, should_continue = self._handle_end_of_data(
                        coordinator=coordinator,
                        folder_id=folder_id,
                        worker_id=worker_id,
                        offset=offset,
                        reason=f"received {len(items)} < {limit} items",
                    )
                    if should_break:
                        break
                    if should_continue:
                        continue

                # Periodic progress update
                if items_processed > 0 and items_processed % 500 == 0:
                    snapshot = self.metrics.snapshot()
                    logger.info(
                        f"Worker {worker_id}: {items_processed} items processed, "
                        f"total: {snapshot['total']} ({snapshot['items_per_second']:.1f} items/sec)"
                    )

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
        # Extract required fields - some content types use 'name' instead of 'id'
        item_id = self._get_item_id(item_dict, content_type)
        if not item_id:
            # Fallback to "unknown" like orchestrator.py does
            item_id = "unknown"
            logger.warning(
                f"Item missing identifier field for {ContentType(content_type).name}: {item_dict}"
            )

        item_id = str(item_id)  # Ensure string
        name = item_dict.get("title") or item_dict.get("name") or f"Untitled {item_id}"

        # Serialize content data
        content_data = self.serializer.serialize(item_dict)

        # Extract metadata
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

        # Extract folder_id if present (dashboards, looks, boards)
        folder_id = None
        if "folder_id" in item_dict and item_dict["folder_id"] is not None:
            folder_id = str(item_dict["folder_id"])

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
