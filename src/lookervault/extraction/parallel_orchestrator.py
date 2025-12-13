"""Parallel orchestration of content extraction using worker thread pool."""

import logging
import queue
import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from lookervault.config.models import ParallelConfig
from lookervault.exceptions import OrchestrationError
from lookervault.extraction.batch_processor import MemoryAwareBatchProcessor
from lookervault.extraction.metrics import ThreadSafeMetrics
from lookervault.extraction.orchestrator import ExtractionConfig, ExtractionResult
from lookervault.extraction.progress import ProgressTracker
from lookervault.extraction.rate_limiter import AdaptiveRateLimiter
from lookervault.extraction.work_queue import WorkItem, WorkQueue
from lookervault.storage.models import (
    Checkpoint,
    ContentItem,
    ContentType,
    ExtractionSession,
    SessionStatus,
)
from lookervault.storage.repository import ContentRepository
from lookervault.storage.serializer import ContentSerializer

if TYPE_CHECKING:
    from lookervault.looker.extractor import ContentExtractor

logger = logging.getLogger(__name__)


class ParallelOrchestrator:
    """Parallel orchestrator using producer-consumer pattern with thread pool.

    Architecture:
    - Producer (main thread): Fetches from Looker API, creates WorkItems, queues them
    - Consumers (worker threads): Process WorkItems, save to database
    - Thread-safe coordination: WorkQueue, ThreadSafeMetrics, thread-local DB connections

    Performance:
    - Target: 500+ items/second with 10 workers
    - Memory: <2GB regardless of worker count (bounded queue)
    - Scaling: Linear up to 8 workers, plateaus at 16 (SQLite write limit)
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
        self.work_queue = WorkQueue(maxsize=parallel_config.queue_size)
        self.metrics = ThreadSafeMetrics()

        # Create shared rate limiter for all workers
        if parallel_config.adaptive_rate_limiting:
            self.rate_limiter = AdaptiveRateLimiter(
                requests_per_minute=parallel_config.rate_limit_per_minute,
                requests_per_second=parallel_config.rate_limit_per_second,
                adaptive=True,
            )
            # Inject rate limiter into extractor (all workers share same instance)
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

        Returns:
            ExtractionResult with summary statistics

        Raises:
            OrchestrationError: If extraction fails
        """
        start_time = datetime.now()

        # Create extraction session
        session = ExtractionSession(
            status=SessionStatus.RUNNING,
            config={
                "content_types": self.config.content_types,
                "batch_size": self.config.batch_size,
                "fields": self.config.fields,
                "workers": self.parallel_config.workers,
                "queue_size": self.parallel_config.queue_size,
            },
        )
        self.repository.create_session(session)

        logger.info(
            f"Starting parallel extraction session {session.id} "
            f"with {self.parallel_config.workers} workers"
        )

        result = ExtractionResult(session_id=session.id, total_items=0)

        try:
            # Launch consumer workers in thread pool
            logger.info(f"Launching {self.parallel_config.workers} consumer worker threads")
            with ThreadPoolExecutor(max_workers=self.parallel_config.workers) as executor:
                # Submit consumer workers
                consumer_futures: list[Future[int]] = [
                    executor.submit(self._consumer_worker, i)
                    for i in range(self.parallel_config.workers)
                ]
                logger.info(f"All {self.parallel_config.workers} workers submitted to thread pool")

                # Run producer in main thread (API fetching)
                logger.info("Starting producer worker in main thread")
                self._producer_worker(session.id)
                logger.info("Producer worker completed - all work queued")

                # Wait for all consumers to complete and collect results
                logger.info(f"Waiting for {len(consumer_futures)} consumer workers to complete")
                completed_count = 0
                for future in as_completed(consumer_futures):
                    try:
                        items_processed = future.result()
                        completed_count += 1
                        logger.info(
                            f"Worker {completed_count}/{len(consumer_futures)} completed: "
                            f"{items_processed} items processed"
                        )
                    except Exception as e:
                        # Worker failure - log but continue with others
                        worker_error = str(e)
                        logger.error(f"Worker thread failed: {worker_error}")
                        result.errors += 1
                        self.metrics.record_error("main", worker_error)

                logger.info(f"All {len(consumer_futures)} workers completed")

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

    def _producer_worker(self, session_id: str) -> None:
        """Producer thread: Fetch from API and queue work batches.

        Runs in main thread. Responsible for:
        - Creating checkpoints for each content type
        - Fetching data from Looker API (sequential, respects pagination)
        - Batching items into WorkItems
        - Queuing WorkItems for consumers
        - Marking checkpoints complete
        - Sending stop signals to workers

        Args:
            session_id: Extraction session ID for checkpoint association
        """
        logger.info("Producer starting: fetching from API and queuing work")

        try:
            for content_type in self.config.content_types:
                content_type_name = ContentType(content_type).name.lower()
                logger.info(f"Producer: Processing {content_type_name}")

                # Check for existing checkpoint if resume enabled
                if self.config.resume:
                    existing_checkpoint = self.repository.get_latest_checkpoint(
                        content_type, session_id
                    )
                    if existing_checkpoint and existing_checkpoint.completed_at:
                        # Checkpoint already complete - skip this content type
                        logger.info(
                            f"Producer: Skipping {content_type_name} - "
                            f"found complete checkpoint from {existing_checkpoint.completed_at.isoformat()} "
                            f"({existing_checkpoint.item_count} items)"
                        )
                        continue
                    elif existing_checkpoint and not existing_checkpoint.completed_at:
                        # Partial checkpoint exists - warn and re-extract
                        logger.warning(
                            f"Producer: Found incomplete checkpoint for {content_type_name} "
                            f"from {existing_checkpoint.started_at.isoformat()}. "
                            f"Re-extracting (upserts will handle duplicates)."
                        )

                logger.info(f"Producer: Fetching {content_type_name}")

                # Create checkpoint for this content type
                checkpoint = Checkpoint(
                    session_id=session_id,
                    content_type=content_type,
                    checkpoint_data={
                        "content_type": content_type_name,
                        "batch_size": self.config.batch_size,
                        "incremental": self.config.incremental,
                        "parallel": True,  # Mark as parallel extraction
                        "workers": self.parallel_config.workers,
                    },
                )
                checkpoint_id = self.repository.save_checkpoint(checkpoint)

                # Determine timestamp for incremental extraction
                updated_after = None
                if self.config.incremental:
                    updated_after = self.repository.get_last_sync_timestamp(content_type)
                    if updated_after:
                        logger.info(
                            f"Incremental mode: {content_type_name} "
                            f"updated after {updated_after.isoformat()}"
                        )

                # Extract items from Looker API (sequential iterator)
                items_iterator = self.extractor.extract_all(
                    ContentType(content_type),
                    fields=self.config.fields,
                    batch_size=self.config.batch_size,
                    updated_after=updated_after,
                )

                # Batch items and queue them
                batch: list[dict[str, Any]] = []
                batch_number = 0
                items_queued = 0  # Track total items queued for checkpoint

                for item_dict in items_iterator:
                    batch.append(item_dict)

                    # Queue batch when full
                    if len(batch) >= self.parallel_config.batch_size:
                        work_item = WorkItem(
                            content_type=content_type,
                            items=batch,
                            batch_number=batch_number,
                            is_final_batch=False,
                        )
                        self.work_queue.put_work(work_item)  # Blocks if queue full
                        items_queued += len(batch)

                        # Log queue depth every 10 batches for monitoring
                        if batch_number % 10 == 0:
                            queue_depth = self.work_queue.qsize()
                            queue_pct = (
                                (queue_depth / self.parallel_config.queue_size * 100)
                                if self.parallel_config.queue_size > 0
                                else 0
                            )
                            logger.debug(
                                f"Producer queued batch {batch_number} "
                                f"({len(batch)} {content_type_name}, total: {items_queued}), "
                                f"queue depth: {queue_depth}/{self.parallel_config.queue_size} ({queue_pct:.1f}%)"
                            )
                        else:
                            logger.debug(
                                f"Producer queued batch {batch_number} "
                                f"({len(batch)} {content_type_name}, total: {items_queued})"
                            )

                        batch = []
                        batch_number += 1

                # Queue final partial batch (if any)
                if batch:
                    work_item = WorkItem(
                        content_type=content_type,
                        items=batch,
                        batch_number=batch_number,
                        is_final_batch=True,
                    )
                    self.work_queue.put_work(work_item)
                    items_queued += len(batch)
                    logger.debug(
                        f"Producer queued final batch {batch_number} "
                        f"({len(batch)} {content_type_name}, total: {items_queued})"
                    )

                # Mark checkpoint complete with item count
                checkpoint.id = checkpoint_id
                checkpoint.completed_at = datetime.now()
                checkpoint.item_count = items_queued
                checkpoint.checkpoint_data["total_batches"] = batch_number + 1
                checkpoint.checkpoint_data["items_queued"] = items_queued
                self.repository.update_checkpoint(checkpoint)

                logger.info(
                    f"Producer completed {content_type_name}: "
                    f"{items_queued} items in {batch_number + 1} batches queued"
                )

        finally:
            # Send stop signals to all workers
            logger.info(f"Producer sending stop signals to {self.parallel_config.workers} workers")
            self.work_queue.send_stop_signals(self.parallel_config.workers)

    def _consumer_worker(self, worker_id: int) -> int:
        """Consumer thread: Process work items and save to database.

        Runs in worker thread. Responsible for:
        - Getting WorkItems from queue
        - Converting dicts to ContentItems
        - Saving to database (thread-local connection)
        - Updating thread-safe metrics
        - Cleaning up thread-local resources

        Args:
            worker_id: Worker thread identifier (0-based index)

        Returns:
            Number of items processed by this worker

        Raises:
            Exception: If worker encounters fatal error
        """
        thread_name = threading.current_thread().name
        logger.info(f"Consumer worker {worker_id} ({thread_name}) starting")

        items_processed = 0

        try:
            while True:
                try:
                    # Get work from queue (blocks if empty, 5sec timeout)
                    work_item = self.work_queue.get_work(timeout=5.0)

                    if work_item is None:
                        # Stop signal received
                        logger.info(f"Worker {worker_id} received stop signal, exiting")
                        break

                    # Process all items in this batch
                    for item_dict in work_item.items:
                        try:
                            # Convert to ContentItem
                            content_item = self._dict_to_content_item(
                                item_dict, work_item.content_type
                            )

                            # Save to database (uses thread-local connection)
                            self.repository.save_content(content_item)

                            # Update metrics
                            self.metrics.increment_processed(work_item.content_type, count=1)
                            items_processed += 1

                        except Exception as e:
                            # Item-level error - log and continue
                            import traceback

                            item_id = item_dict.get("id", "UNKNOWN")
                            error_msg = f"Failed to process item {item_id}: {e}"

                            # WARNING: Brief error message
                            logger.warning(f"Worker {worker_id}: {error_msg}")

                            # DEBUG: Full context with types and traceback
                            tb = traceback.format_exc()
                            logger.debug(
                                f"Worker {worker_id}: Detailed error context\n"
                                f"  Item ID: {item_id}\n"
                                f"  Content Type: {work_item.content_type}\n"
                                f"  Item Keys: {list(item_dict.keys())}\n"
                                f"  user_id: {item_dict.get('user_id')} (type: {type(item_dict.get('user_id')).__name__})\n"
                                f"  owner_id: {item_dict.get('owner_id')} (type: {type(item_dict.get('owner_id')).__name__})\n"
                                f"  created_at: {item_dict.get('created_at')} (type: {type(item_dict.get('created_at')).__name__})\n"
                                f"  updated_at: {item_dict.get('updated_at')} (type: {type(item_dict.get('updated_at')).__name__})\n"
                                f"  Exception: {type(e).__name__}: {e}\n"
                                f"  Traceback:\n{tb}"
                            )
                            self.metrics.record_error(thread_name, error_msg)

                    # Update metrics with batch completion
                    self.metrics.increment_batches(count=1)

                    # Log batch completion
                    logger.debug(
                        f"Worker {worker_id} completed batch {work_item.batch_number} "
                        f"({len(work_item.items)} items, "
                        f"total batches: {self.metrics.batches_completed})"
                    )

                    # Periodic memory check (every 100 batches across all workers)
                    if (
                        self.batch_processor.enable_monitoring
                        and self.metrics.batches_completed % 100 == 0
                    ):
                        current_mem, peak_mem = self.batch_processor.get_memory_usage()
                        current_mb = current_mem / (1024 * 1024)
                        logger.debug(
                            f"Memory check at batch {self.metrics.batches_completed}: "
                            f"{current_mb:.1f} MB, {items_processed} items processed by worker {worker_id}"
                        )

                except queue.Empty:
                    # Timeout waiting for work - check if producer is done
                    if self.work_queue.empty():
                        logger.debug(f"Worker {worker_id} timeout with empty queue, continuing...")
                    continue

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
        # Extract required fields
        item_id = item_dict.get("id")
        if not item_id:
            raise ValueError("Item missing required 'id' field")

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

        # Parse timestamps
        created_at = datetime.now(UTC)
        updated_at = datetime.now(UTC)

        if "created_at" in item_dict and item_dict["created_at"]:
            try:
                created_at_val = item_dict["created_at"]
                if isinstance(created_at_val, str):
                    created_at = datetime.fromisoformat(created_at_val.replace("Z", "+00:00"))
                elif isinstance(created_at_val, datetime):
                    created_at = created_at_val
                elif isinstance(created_at_val, (int, float)):
                    # Unix timestamp
                    created_at = datetime.fromtimestamp(created_at_val, tz=UTC)
                else:
                    logger.warning(
                        f"Unexpected type for created_at: {type(created_at_val).__name__} = {created_at_val}"
                    )
            except (ValueError, AttributeError, TypeError) as e:
                logger.warning(
                    f"Could not parse created_at (type: {type(item_dict['created_at']).__name__}) "
                    f"'{item_dict['created_at']}' for item {item_id}: {e}"
                )

        if "updated_at" in item_dict and item_dict["updated_at"]:
            try:
                updated_at_val = item_dict["updated_at"]
                if isinstance(updated_at_val, str):
                    updated_at = datetime.fromisoformat(updated_at_val.replace("Z", "+00:00"))
                elif isinstance(updated_at_val, datetime):
                    updated_at = updated_at_val
                elif isinstance(updated_at_val, (int, float)):
                    # Unix timestamp
                    updated_at = datetime.fromtimestamp(updated_at_val, tz=UTC)
                else:
                    logger.warning(
                        f"Unexpected type for updated_at: {type(updated_at_val).__name__} = {updated_at_val}"
                    )
            except (ValueError, AttributeError, TypeError) as e:
                logger.warning(
                    f"Could not parse updated_at (type: {type(item_dict['updated_at']).__name__}) "
                    f"'{item_dict['updated_at']}' for item {item_id}: {e}"
                )

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
        )
