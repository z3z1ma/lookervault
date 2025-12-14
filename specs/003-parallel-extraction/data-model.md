# Data Model: Parallel Content Extraction

**Feature**: 003-parallel-extraction
**Date**: 2025-12-13
**Purpose**: Define entities and their relationships for parallel extraction feature

---

## Overview

The parallel extraction feature introduces new entities for managing worker threads, work distribution, and coordinated rate limiting. Existing entities (ContentItem, Checkpoint, ExtractionSession) are preserved with minor enhancements for thread safety.

---

## New Entities

### 1. WorkItem

**Purpose**: Represents a batch of items to be processed by worker threads

**Fields**:
- `content_type: int` - Content type identifier (ContentType enum value)
- `items: list[dict[str, Any]]` - Batch of raw API response dictionaries
- `batch_number: int` - Sequential batch identifier for tracking
- `is_final_batch: bool = False` - Indicates last batch for content type

**Relationships**:
- Produced by: Producer thread (API fetcher)
- Consumed by: Consumer threads (workers)
- Related to: ContentType (via content_type field)

**Validation Rules**:
- `content_type` must be valid ContentType enum value
- `items` must not be empty list
- `batch_number` must be >= 0
- `is_final_batch` used for checkpoint completion signal

**State Transitions**:
```
Created → Queued → Processing → Completed
                              ↘ Failed
```

**Usage**:
```python
work_item = WorkItem(
    content_type=ContentType.DASHBOARD.value,
    items=[{...}, {...}, ...],  # 100 dashboard dicts
    batch_number=42,
    is_final_batch=False,
)
```

---

### 2. ParallelConfig

**Purpose**: Configuration for parallel extraction execution

**Fields**:
- `workers: int` - Number of worker threads in pool
- `queue_size: int` - Maximum work queue depth (bounded queue)
- `batch_size: int` - Items per work batch (default: 100)
- `rate_limit_per_minute: int` - Max API requests per minute
- `rate_limit_per_second: int` - Max API requests per second (burst)
- `adaptive_rate_limiting: bool` - Enable adaptive backoff on 429

**Relationships**:
- Used by: ExtractionOrchestrator
- Configures: ThreadPoolExecutor, AdaptiveRateLimiter, WorkQueue

**Validation Rules**:
- `workers` must be in range [1, 50]
- `queue_size` must be >= workers × 10 (prevent starvation)
- `batch_size` must be in range [10, 1000]
- `rate_limit_per_minute` must be > 0
- `rate_limit_per_second` must be <= rate_limit_per_minute
- `adaptive_rate_limiting` defaults to True

**Defaults**:
```python
DEFAULT_WORKERS = min(os.cpu_count() or 1, 8)
DEFAULT_QUEUE_SIZE = DEFAULT_WORKERS * 100
DEFAULT_BATCH_SIZE = 100
DEFAULT_RATE_LIMIT_PER_MINUTE = 100
DEFAULT_RATE_LIMIT_PER_SECOND = 10
```

**Usage**:
```python
config = ParallelConfig(
    workers=8,
    queue_size=800,
    batch_size=100,
    rate_limit_per_minute=100,
    rate_limit_per_second=10,
    adaptive_rate_limiting=True,
)
```

---

### 3. WorkerMetrics

**Purpose**: Thread-safe metrics aggregation across worker threads

**Fields**:
- `items_processed: int` - Total items processed across all workers
- `items_by_type: dict[int, int]` - Items processed per content type
- `errors: int` - Total error count
- `worker_errors: dict[str, list[str]]` - Errors by worker thread ID
- `start_time: datetime` - Extraction start timestamp
- `_lock: threading.Lock` - Thread synchronization lock (private)

**Relationships**:
- Updated by: All worker threads
- Read by: Progress tracker, final result aggregation

**Validation Rules**:
- All counters must be >= 0
- `items_by_type` keys must be valid ContentType values
- Thread-safe increment operations (use context manager)

**Operations**:
```python
class WorkerMetrics:
    def increment_processed(self, content_type: int, count: int = 1):
        """Thread-safe increment of processed items."""
        with self._lock:
            self.items_processed += count
            self.items_by_type[content_type] = (
                self.items_by_type.get(content_type, 0) + count
            )

    def record_error(self, worker_id: str, error_msg: str):
        """Thread-safe error recording."""
        with self._lock:
            self.errors += 1
            if worker_id not in self.worker_errors:
                self.worker_errors[worker_id] = []
            self.worker_errors[worker_id].append(error_msg)

    def snapshot(self) -> dict:
        """Thread-safe atomic read of all metrics."""
        with self._lock:
            return {
                'total': self.items_processed,
                'by_type': dict(self.items_by_type),
                'errors': self.errors,
                'duration': (datetime.now() - self.start_time).total_seconds(),
            }
```

**Thread Safety**:
- All public methods use `self._lock` context manager
- `snapshot()` ensures atomic reads of multiple fields

---

### 4. RateLimiterState

**Purpose**: Tracks adaptive rate limiting state across workers

**Fields**:
- `backoff_multiplier: float` - Current rate reduction factor (1.0 = normal)
- `last_429_timestamp: datetime | None` - Last rate limit error time
- `consecutive_successes: int` - Success count since last 429
- `total_429_count: int` - Total rate limit errors encountered
- `_lock: threading.RLock` - Reentrant lock for state updates

**Relationships**:
- Used by: AdaptiveRateLimiter
- Updated on: HTTP 429 detection, successful API calls

**State Transitions**:
```
Normal (1.0) → BackedOff (1.5) → DeepBackoff (2.25) → ...
                ↓ (consecutive successes > threshold)
           Recovering (1.4) → Recovering (1.3) → ... → Normal (1.0)
```

**Validation Rules**:
- `backoff_multiplier` must be >= 1.0
- `consecutive_successes` must be >= 0
- `total_429_count` must be >= 0

**Operations**:
```python
class RateLimiterState:
    def on_rate_limit_detected(self):
        """Increase backoff multiplier on 429."""
        with self._lock:
            self.backoff_multiplier *= 1.5
            self.last_429_timestamp = datetime.now()
            self.consecutive_successes = 0
            self.total_429_count += 1

    def on_success(self):
        """Gradually reduce backoff on success."""
        with self._lock:
            self.consecutive_successes += 1
            if self.consecutive_successes >= 10:
                self.backoff_multiplier = max(1.0, self.backoff_multiplier * 0.9)
                self.consecutive_successes = 0
```

---

## Modified Existing Entities

### ExtractionSession (Enhanced)

**New Fields**:
- `worker_count: int | None` - Number of workers used (null for sequential)
- `throughput_items_per_second: float | None` - Average extraction rate

**Purpose**: Track parallel execution metadata

**Backward Compatibility**: New fields are nullable, existing sessions unaffected

---

### Checkpoint (Thread-Safe Enhanced)

**Considerations**:
- Existing checkpoint logic remains at **content-type level** (not page-level)
- Producer thread marks checkpoint complete after fetching all pages
- Consumers process items in any order (upserts handle duplicates)
- No schema changes needed - existing fields support parallel execution

**Thread Safety**:
- Checkpoint creation/updates use BEGIN IMMEDIATE transactions
- Thread-local connections prevent race conditions

---

## Entity Relationships Diagram

```
ExtractionOrchestrator
    │
    ├── ParallelConfig (1:1) - Configuration
    │
    ├── WorkQueue (1:1) - queue.Queue[WorkItem]
    │   └── WorkItem (1:N) - Batches of items
    │
    ├── ThreadPoolExecutor (1:1) - Worker management
    │   └── Worker Threads (1:N) - Consumer workers
    │
    ├── AdaptiveRateLimiter (1:1) - Shared rate limiter
    │   └── RateLimiterState (1:1) - Rate state
    │
    ├── WorkerMetrics (1:1) - Shared metrics
    │
    ├── ContentRepository (1:1) - Storage (thread-safe)
    │   └── Thread-Local Connections (1:N per thread)
    │
    └── ExtractionSession (1:1) - Session tracking
        └── Checkpoint (1:N per content type)
```

---

## Data Flow

### Producer Thread Flow
```
1. For each content_type:
   2. Create Checkpoint(content_type, session_id)
   3. Fetch items from Looker API (paginated)
   4. Group items into batches (batch_size=100)
   5. Create WorkItem(content_type, items, batch_number)
   6. Put WorkItem into WorkQueue (blocks if queue full)
   7. Mark Checkpoint.completed_at when done
8. Send stop signals (None) to all workers
```

### Consumer Thread Flow
```
1. Get WorkItem from WorkQueue (blocks if empty)
2. If WorkItem is None: exit (stop signal)
3. For each item_dict in WorkItem.items:
   4. Convert to ContentItem
   5. repository.save_content(item) - uses thread-local connection
   6. metrics.increment_processed(content_type)
7. Go to step 1
```

### Rate Limiter Flow
```
1. Worker calls: rate_limiter.acquire()
2. Token bucket checks available tokens
3. If tokens available: proceed
4. If no tokens: sleep until tokens refill
5. On API success: rate_limiter.on_success()
6. On HTTP 429: rate_limiter.on_429_detected()
   → Increase backoff_multiplier
   → All future workers slow down proportionally
```

---

## Validation Summary

| Entity | Primary Validations |
|--------|---------------------|
| **WorkItem** | content_type valid, items non-empty, batch_number >= 0 |
| **ParallelConfig** | workers ∈ [1,50], queue_size >= workers×10, batch_size ∈ [10,1000] |
| **WorkerMetrics** | All counters >= 0, thread-safe operations via lock |
| **RateLimiterState** | backoff_multiplier >= 1.0, thread-safe via RLock |
| **ExtractionSession** | worker_count >= 1 if parallel, throughput > 0 |

---

## Performance Considerations

### Memory Footprint

**Per-Worker Overhead**:
- Thread stack: ~50KB
- Thread-local SQLite connection: ~200KB
- Total per worker: ~250KB

**Work Queue**:
- Queue size: 1000 items
- Items per batch: 100
- Average item size: ~10KB (JSON)
- Total queue memory: ~1GB max (bounded)

**Total Memory (10 workers)**:
- Workers: 10 × 250KB = 2.5MB
- Queue: ~1GB (worst case)
- Python overhead: ~100MB
- **Total: ~1.1GB** (well under 2GB constraint)

### Throughput Targets

**Sequential Baseline**:
- ~50-100 items/second

**Parallel with 4 Workers**:
- Target: 200-400 items/second (4x improvement)

**Parallel with 10 Workers**:
- Target: 500-1000 items/second (10x improvement)
- Constraint: SQLite write contention limits scaling beyond ~16 workers

---

## Migration Notes

**No Database Schema Changes Required**:
- Existing tables (content_items, checkpoints, extraction_sessions) support parallel execution
- New entities (WorkItem, ParallelConfig, WorkerMetrics, RateLimiterState) are runtime-only (not persisted)

**Backward Compatibility**:
- Sequential extraction remains default (workers=1)
- Parallel execution opt-in via `--workers N` flag
- Existing checkpoints compatible with parallel resume

---

## Error Handling

### Worker Thread Failures

**Scenario**: One worker crashes due to exception

**Handling**:
1. ThreadPoolExecutor continues with remaining workers
2. Failed worker's exception captured via `Future.exception()`
3. Error recorded in WorkerMetrics.worker_errors
4. Extraction continues with N-1 workers
5. Final result includes error count

**Code Pattern**:
```python
for future in as_completed(futures):
    if future.exception() is not None:
        metrics.record_error(worker_id, str(future.exception()))
        continue  # Don't crash entire extraction
    result = future.result()
```

### Queue Overflow Prevention

**Scenario**: Producer too fast, queue fills up

**Handling**:
- Bounded queue blocks producer via `queue.put(item, block=True)`
- Producer naturally throttles to consumer speed
- No memory exhaustion

### Rate Limit Errors

**Scenario**: API returns HTTP 429 despite proactive limiting

**Handling**:
1. Worker catches RateLimitError
2. Calls `rate_limiter.on_429_detected()`
3. All workers slow down (shared backoff_multiplier)
4. Tenacity retry logic retries request
5. Gradual recovery via `on_success()` after sustained success
