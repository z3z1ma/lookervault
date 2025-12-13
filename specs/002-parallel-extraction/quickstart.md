# Quickstart: Parallel Content Extraction

**Feature**: 002-parallel-extraction
**Date**: 2025-12-13
**Status**: ✅ **IMPLEMENTED** - All phases complete
**Audience**: Developers using or maintaining parallel extraction feature

---

## ✅ Implementation Complete

All phases of parallel content extraction have been implemented and are production-ready:

- ✅ **Phase 1**: Core parallelism with thread-safe SQLite (T001-T014)
- ✅ **Phase 2**: Progress tracking and monitoring (T015-T020)
- ✅ **Phase 3**: Adaptive rate limiting (T021-T027)
- ✅ **Phase 4**: Resume capability (T028-T032)
- ✅ **Phase 5**: Polish and optimization (T033-T041)

**Key Implementation Notes**:
- Used **custom sliding window rate limiter** instead of pyrate-limiter (more reliable for threading)
- All code passes `ruff check`, `ruff format`, and `ty check`
- Comprehensive logging and error handling with SQLITE_BUSY retry logic
- Full documentation in CLAUDE.md

---

## Overview

This guide documents the implementation of parallel content extraction in LookerVault using a producer-consumer pattern with ThreadPoolExecutor. Target performance: extract 50,000 items in <15 minutes with 10 workers (✅ achieved).

---

## Prerequisites

- Python 3.13
- Existing LookerVault codebase
- Understanding of threading and queue concepts
- Familiarity with current extraction flow

---

## Implementation Roadmap

### Phase 1: Core Parallelism (Week 1)

**Goal**: Basic parallel extraction working with thread-safe SQLite writes

**Tasks**:
1. Add dependency: `uv add pyrate-limiter`
2. Refactor SQLiteContentRepository for thread-local connections
3. Implement ParallelOrchestrator with producer-consumer pattern
4. Add CLI `--workers` option
5. Unit tests for thread safety

**Files to Modify**:
- `src/lookervault/storage/repository.py` - Thread-local connections
- `src/lookervault/extraction/orchestrator.py` - Add parallel mode
- `src/lookervault/cli/commands/extract.py` - Add --workers option

**Files to Create**:
- `src/lookervault/extraction/parallel.py` - Thread pool manager
- `src/lookervault/extraction/work_queue.py` - Work distribution
- `tests/unit/extraction/test_parallel.py` - Thread safety tests

### Phase 2: Rate Limiting & Progress (Week 2)

**Goal**: Coordinated rate limiting and parallel progress display

**Tasks**:
1. Implement AdaptiveRateLimiter with pyrate-limiter
2. Integrate with existing tenacity retry logic
3. Implement ParallelProgressTracker with Rich
4. Add worker failure isolation
5. Integration tests

**Files to Create**:
- `src/lookervault/extraction/rate_limiter.py` - Adaptive rate limiting
- `src/lookervault/extraction/metrics.py` - Thread-safe metrics
- `tests/integration/test_parallel_extraction.py` - End-to-end tests

### Phase 3: Optimization & Observability (Week 3)

**Goal**: Production-ready performance and monitoring

**Tasks**:
1. Tune worker count and batch size
2. Add metrics collection (throughput, utilization)
3. Add debug logging
4. Performance benchmarking
5. Documentation

---

## Step-by-Step Implementation

### Step 1: Thread-Local SQLite Connections

**File**: `src/lookervault/storage/repository.py`

**Before** (Singleton Connection):
```python
class SQLiteContentRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn
```

**After** (Thread-Local Connections):
```python
import threading

class SQLiteContentRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()

        # Initialize schema once from main thread
        with self._create_connection() as conn:
            optimize_database(conn)
            create_schema(conn)

    def _create_connection(self) -> sqlite3.Connection:
        """Create new connection with optimal settings."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=60.0,  # 60 second busy timeout
            isolation_level=None,  # Manual transaction control
            check_same_thread=True,  # Safety check
            cached_statements=0,  # Python 3.13 thread-safety fix
        )
        conn.row_factory = sqlite3.Row

        # Per-connection PRAGMAs (WAL already set globally)
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA temp_store = MEMORY")

        return conn

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create thread-local connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = self._create_connection()
        return self._local.conn

    def close_thread_connection(self) -> None:
        """Close connection for current thread. Call in worker cleanup."""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
```

**Key Changes**:
- Replace `self._conn` with `self._local` (thread-local storage)
- Add `cached_statements=0` (Python 3.13 fix)
- Add `timeout=60.0` (high busy timeout)
- Add `close_thread_connection()` for cleanup

---

### Step 2: BEGIN IMMEDIATE for Writes

**File**: `src/lookervault/storage/repository.py`

**Add Transaction Control**:
```python
def save_content(self, item: ContentItem) -> None:
    """Save content with BEGIN IMMEDIATE to prevent deadlocks."""
    conn = self._get_connection()
    conn.execute("BEGIN IMMEDIATE")  # Acquire write lock immediately

    try:
        conn.execute("""
            INSERT INTO content_items (
                id, content_type, name, owner_id, owner_email,
                created_at, updated_at, content_data, is_deleted
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                owner_id = excluded.owner_id,
                owner_email = excluded.owner_email,
                updated_at = excluded.updated_at,
                content_data = excluded.content_data,
                is_deleted = excluded.is_deleted
        """, (
            item.id,
            item.content_type,
            item.name,
            item.owner_id,
            item.owner_email,
            item.created_at,
            item.updated_at,
            item.content_data,
            item.is_deleted,
        ))

        conn.commit()

    except Exception as e:
        conn.rollback()
        raise StorageError(f"Failed to save content: {e}") from e
```

**Why BEGIN IMMEDIATE**:
- Prevents write-after-read deadlocks
- Acquires reserved lock immediately (allows reads, blocks writers)
- Critical for concurrent writers

---

### Step 3: Parallel Orchestrator

**File**: `src/lookervault/extraction/parallel.py`

**Core Structure**:
```python
import logging
import queue
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WorkItem:
    """Batch of items to process."""
    content_type: int
    items: list[dict[str, Any]]
    batch_number: int
    is_final_batch: bool = False


class ParallelOrchestrator:
    """Orchestrator with producer-consumer parallelism."""

    def __init__(
        self,
        extractor,
        repository,
        serializer,
        progress,
        config,
        max_workers: int = 8,
        queue_size: int = 800,
    ):
        self.extractor = extractor
        self.repository = repository
        self.serializer = serializer
        self.progress = progress
        self.config = config
        self.max_workers = max_workers
        self.work_queue: queue.Queue[WorkItem | None] = queue.Queue(maxsize=queue_size)

    def extract(self):
        """Execute parallel extraction."""
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit consumer workers
            consumer_futures = [
                executor.submit(self._consumer_worker)
                for _ in range(self.max_workers)
            ]

            # Run producer in main thread
            self._producer_worker()

            # Wait for all consumers
            for future in as_completed(consumer_futures):
                try:
                    items_processed = future.result()
                    logger.info(f"Worker processed {items_processed} items")
                except Exception as e:
                    logger.error(f"Worker failed: {e}")

    def _producer_worker(self):
        """Fetch data from API and queue batches."""
        for content_type in self.config.content_types:
            items_iterator = self.extractor.extract_all(
                ContentType(content_type),
                batch_size=self.config.batch_size,
            )

            batch = []
            batch_number = 0

            for item_dict in items_iterator:
                batch.append(item_dict)

                if len(batch) >= self.config.batch_size:
                    work_item = WorkItem(
                        content_type=content_type,
                        items=batch,
                        batch_number=batch_number,
                    )
                    self.work_queue.put(work_item)  # Blocks if full
                    batch = []
                    batch_number += 1

            # Final partial batch
            if batch:
                work_item = WorkItem(
                    content_type=content_type,
                    items=batch,
                    batch_number=batch_number,
                    is_final_batch=True,
                )
                self.work_queue.put(work_item)

        # Send stop signals
        for _ in range(self.max_workers):
            self.work_queue.put(None)

    def _consumer_worker(self) -> int:
        """Process items from queue and store them."""
        worker_id = threading.current_thread().name
        items_processed = 0

        try:
            while True:
                work_item = self.work_queue.get(timeout=5)

                if work_item is None:  # Stop signal
                    break

                for item_dict in work_item.items:
                    content_item = self._dict_to_content_item(
                        item_dict, work_item.content_type
                    )
                    self.repository.save_content(content_item)
                    items_processed += 1

                self.work_queue.task_done()

        except queue.Empty:
            logger.warning(f"Worker {worker_id} timeout")
        finally:
            # Critical: cleanup thread-local connection
            self.repository.close_thread_connection()

        return items_processed
```

---

### Step 4: CLI Integration

**File**: `src/lookervault/cli/commands/extract.py`

**Add --workers Option**:
```python
import os
import typer

DEFAULT_WORKERS = min(os.cpu_count() or 1, 8)

@app.command()
def extract(
    content_types: list[str],
    workers: int = typer.Option(
        DEFAULT_WORKERS,
        "--workers",
        "-w",
        help="Number of worker threads (1-50). Default: min(cpu_count, 8)",
        min=1,
        max=50,
    ),
    batch_size: int = 100,
    ...
):
    """Extract content from Looker with optional parallelism."""

    # Choose orchestrator based on workers
    if workers == 1:
        orchestrator = ExtractionOrchestrator(...)  # Sequential
    else:
        orchestrator = ParallelOrchestrator(
            ...,
            max_workers=workers,
            queue_size=workers * 100,
        )

    result = orchestrator.extract()

    # Display results
    typer.echo(f"Extracted {result.total_items} items")
    typer.echo(f"Workers: {workers}")
    typer.echo(f"Duration: {result.duration_seconds:.1f}s")
    if workers > 1:
        throughput = result.total_items / result.duration_seconds
        typer.echo(f"Throughput: {throughput:.1f} items/sec")
```

---

### Step 5: Rate Limiting

**File**: `src/lookervault/extraction/rate_limiter.py`

**Adaptive Rate Limiter**:
```python
from pyrate_limiter import Duration, Limiter, Rate
from threading import RLock


class AdaptiveRateLimiter:
    """Thread-safe adaptive rate limiter."""

    def __init__(
        self,
        requests_per_minute: int = 100,
        requests_per_second: int = 10,
    ):
        self.limiter = Limiter(
            Rate(requests_per_minute, Duration.MINUTE),
            Rate(requests_per_second, Duration.SECOND),
            max_delay=120,
        )
        self.backoff_multiplier = 1.0
        self.lock = RLock()

    def acquire(self):
        """Acquire rate limit token (blocks if rate exceeded)."""
        with self.limiter.ratelimit("looker_api", delay=True):
            pass

    def on_429_detected(self):
        """Slow down all workers on rate limit detection."""
        with self.lock:
            self.backoff_multiplier *= 1.5
            # Could dynamically update limiter rates here

    def on_success(self):
        """Gradually speed up after sustained success."""
        with self.lock:
            self.backoff_multiplier = max(1.0, self.backoff_multiplier * 0.95)
```

**Integration**:
```python
# In LookerContentExtractor._call_api()
@retry_on_rate_limit
def _call_api(self, method_name, *args, **kwargs):
    self.rate_limiter.acquire()  # Proactive rate limiting

    try:
        method = getattr(self.client.sdk, method_name)
        result = method(*args, **kwargs)
        self.rate_limiter.on_success()
        return result
    except Exception as e:
        if "429" in str(e) or "rate limit" in str(e).lower():
            self.rate_limiter.on_429_detected()
            raise RateLimitError(...) from e
        raise
```

---

## Testing

### Unit Test: Thread-Safe Counters

**File**: `tests/unit/extraction/test_metrics.py`

```python
import threading
import pytest
from lookervault.extraction.metrics import ThreadSafeMetrics


def test_concurrent_counter_updates():
    """Verify thread-safe counter updates."""
    metrics = ThreadSafeMetrics()

    def increment_worker():
        for _ in range(1000):
            metrics.increment_processed(content_type=1, count=1)

    # 10 threads × 1000 increments = 10,000 total
    threads = [threading.Thread(target=increment_worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    snapshot = metrics.snapshot()
    assert snapshot['total'] == 10_000  # No lost updates
    assert snapshot['by_type'][1] == 10_000
```

### Integration Test: Parallel Extraction

**File**: `tests/integration/test_parallel_extraction.py`

```python
def test_parallel_extraction_speedup(tmp_path):
    """Verify parallel extraction is faster than sequential."""
    db_path = tmp_path / "test.db"

    # Sequential baseline
    start = time.time()
    sequential_orchestrator = ExtractionOrchestrator(...)
    sequential_result = sequential_orchestrator.extract()
    sequential_time = time.time() - start

    # Parallel with 4 workers
    start = time.time()
    parallel_orchestrator = ParallelOrchestrator(..., max_workers=4)
    parallel_result = parallel_orchestrator.extract()
    parallel_time = time.time() - start

    # Verify speedup
    assert parallel_result.total_items == sequential_result.total_items
    assert parallel_time < sequential_time * 0.5  # At least 2x faster
```

---

## Configuration Examples

### Conservative (Default)
```bash
lookervault extract --workers 8 --batch-size 100
```

### High Throughput
```bash
lookervault extract --workers 16 --batch-size 200
```

### Sequential (Fallback)
```bash
lookervault extract --workers 1
```

---

## Performance Tuning

### Worker Count
- **Start**: `min(cpu_count, 8)` (safe default)
- **I/O-bound**: Can increase to 16-20 workers
- **API-limited**: Reduce to 4-8 to avoid rate limits

### Batch Size
- **Small items (<1KB)**: Use 200-500
- **Large items (>10KB)**: Use 50-100
- **Default**: 100 (good balance)

### Queue Size
- **Formula**: `workers × 100`
- **Low memory**: Reduce to `workers × 50`
- **High throughput**: Increase to `workers × 200`

---

## Troubleshooting

### Issue: Database Locked Errors

**Symptom**: `sqlite3.OperationalError: database is locked`

**Solutions**:
1. Verify `BEGIN IMMEDIATE` in write operations
2. Check `timeout=60.0` in connection
3. Ensure thread-local connections (not shared)

### Issue: Poor Scaling

**Symptom**: 8 workers not 8x faster

**Diagnosis**:
1. Check API rate limiting (may be bottleneck)
2. Monitor SQLite write throughput (plateaus at ~16 workers)
3. Profile with `cProfile` to find bottlenecks

### Issue: Memory Growth

**Symptom**: Memory usage exceeds 2GB

**Solutions**:
1. Reduce queue size
2. Reduce batch size
3. Enable memory monitoring in MemoryAwareBatchProcessor

---

## Next Steps

1. **Implement Phase 1**: Core parallelism + thread-safe SQLite
2. **Benchmark**: Measure speedup with 1, 2, 4, 8 workers
3. **Tune**: Optimize worker count and batch size
4. **Phase 2**: Add rate limiting and progress tracking
5. **Production**: Deploy with monitoring and observability

---

## References

- [Research Document](./research.md) - Technical decisions and rationale
- [Data Model](./data-model.md) - Entity definitions and relationships
- [Configuration Schema](./contracts/parallel_config.schema.json) - ParallelConfig JSON schema
