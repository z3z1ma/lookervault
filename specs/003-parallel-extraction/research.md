# Research: Parallel Content Extraction

**Feature**: 003-parallel-extraction
**Date**: 2025-12-13
**Purpose**: Resolve technical decisions for implementing parallel extraction with 1-50 worker threads

---

## 1. Threading Model Selection

### Decision: ThreadPoolExecutor (stdlib concurrent.futures)

**Rationale**:
- Perfect fit for I/O-bound workloads (HTTP API calls + SQLite writes)
- Python GIL is released during I/O operations, enabling true concurrency
- Native compatibility with synchronous looker-sdk (no refactoring needed)
- Low memory overhead (~50KB per thread vs ~10-20MB per process)
- Simple integration with existing codebase

**Alternatives Considered**:

1. **ProcessPoolExecutor**: Rejected due to:
   - Overkill for I/O-bound tasks (designed for CPU parallelism)
   - SQLite connection sharing issues across processes
   - High memory overhead (200-500MB for 10 workers)
   - Pickling overhead for inter-process communication

2. **AsyncIO + aiohttp**: Rejected due to:
   - Major refactoring required (looker-sdk is synchronous)
   - Must rewrite all extraction logic with async/await
   - Marginal benefit at target scale (10 workers, not 1000s)
   - High implementation complexity

**Python 3.13 Specific Consideration**:
- Must set `cached_statements=0` in `sqlite3.connect()` to avoid threading cache bugs

**Expected Performance**:
- Linear scaling up to 8 workers for I/O-bound operations
- 50,000 items @ 10 workers should complete in <15 minutes

---

## 2. Work Distribution Strategy

### Decision: Producer-Consumer Pattern with Work Queue

**Rationale**:
- Best load balancing for unbalanced content types (100 to 50,000+ items)
- Maintains existing checkpoint semantics (content-type level granularity)
- API-friendly: Single producer respects pagination order and rate limits
- Moderate complexity: Uses only `queue.Queue` and `ThreadPoolExecutor`
- Memory-safe: Bounded queue prevents exhaustion

**Architecture**:
```
Producer Thread (API Fetcher)
    ↓
Bounded Queue (maxsize=1000)
    ↓
Consumer Thread Pool (4-8 workers)
    ↓
SQLite Storage (thread-safe writes)
```

**Alternatives Considered**:

1. **Content-Type Level Distribution**: Rejected due to:
   - Poor load balancing (threads idle when content types vary 100x in size)
   - Underutilized workers (most threads finish early, wait for largest type)

2. **Page/Batch Level Distribution**: Rejected due to:
   - Complex checkpoint tracking (must track which pages completed)
   - API pagination constraints (many APIs require sequential fetching)
   - State management complexity

3. **Hybrid (Content-Type + Page)**: Rejected due to:
   - Most complex implementation (nested parallelism)
   - Over-parallelization risk (may hit API rate limits)
   - Diminishing returns vs simpler approaches

**Configuration**:
- Worker count: `4-8` (tune based on CPU cores and API rate limits)
- Queue size: `1000` work items (prevents memory exhaustion)
- Batch size: `100` items (existing default, works well)

**Expected Speedup**:
- 4x throughput improvement with 4 workers
- Near-linear scaling up to 8 workers

---

## 3. SQLite Concurrency Strategy

### Decision: Connection-Per-Thread + WAL Mode + BEGIN IMMEDIATE

**Rationale**:
- Eliminates connection lock contention
- WAL mode already enabled in codebase (line 157 of schema.py)
- BEGIN IMMEDIATE prevents write-after-read deadlocks
- High busy timeout (60 seconds) handles transient locks
- Batch writes achieve 500+ items/second target

**Critical Implementation Requirements**:

1. **Thread-Local Connections** (not shared connection):
```python
import threading

class ThreadSafeRepository:
    def __init__(self, db_path):
        self.db_path = db_path
        self._local = threading.local()

    def _get_connection(self):
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=60.0,  # 60 second busy timeout
                isolation_level=None,  # Manual transaction control
                check_same_thread=True,
                cached_statements=0,  # Python 3.13 thread-safety fix
            )
            conn.row_factory = sqlite3.Row
            # WAL mode already set globally in schema.py
            self._local.conn = conn
        return self._local.conn
```

2. **BEGIN IMMEDIATE for All Writes** (prevents deadlocks):
```python
def save_content_batch(self, items):
    conn = self._get_connection()
    conn.execute("BEGIN IMMEDIATE")  # Acquire write lock immediately
    try:
        for item in items:
            conn.execute("INSERT ... ON CONFLICT DO UPDATE ...")
        conn.commit()
    except:
        conn.rollback()
        raise
```

3. **Worker Thread Cleanup**:
```python
def close_thread_connection(self):
    if hasattr(self._local, 'conn') and self._local.conn:
        self._local.conn.close()
        self._local.conn = None
```

**Alternatives Considered**:

1. **Shared Connection**: Rejected due to:
   - High lock contention with 10+ writers
   - Risk of corruption despite check_same_thread=False

2. **Connection Pooling**: Rejected due to:
   - Unnecessary complexity (threads are long-lived)
   - Each thread benefits from dedicated connection

**Performance Expectations**:
- Single-item transactions: 50-100/sec
- Batched (100 items/txn): 500-1000+/sec
- 8-16 workers: 2000-4000 items/sec
- Throughput plateaus beyond 16 workers (SQLite single-writer limit)

**Current Code Gap**:
- `/Users/alexanderbutler/code_projects/work_ccm/lookervault/src/lookervault/storage/repository.py` uses singleton connection (`self._conn`)
- Must refactor to thread-local pattern

---

## 4. Rate Limiting Coordination

### Decision: Token Bucket Algorithm with pyrate-limiter Library

**Rationale**:
- Token bucket allows burst traffic (better for variable API load)
- pyrate-limiter is thread-safe (RLock-based), battle-tested
- Supports adaptive rate adjustment on HTTP 429 detection
- Integrates cleanly with existing tenacity retry logic
- Production-ready (800+ GitHub stars)

**Implementation Strategy**:

**Layer 1: Proactive Rate Limiting** (prevents 429s):
```python
from pyrate_limiter import Duration, Limiter, Rate

class AdaptiveRateLimiter:
    def __init__(self):
        self.limiter = Limiter(
            Rate(100, Duration.MINUTE),  # 100 req/min
            Rate(10, Duration.SECOND),   # 10 req/sec (burst)
            max_delay=120,
        )
        self.backoff_multiplier = 1.0
        self.lock = RLock()

    def acquire(self):
        with self.limiter.ratelimit("looker_api", delay=True):
            pass

    def on_429_detected(self):
        with self.lock:
            self.backoff_multiplier *= 1.5  # Slow down 50%

    def on_success(self):
        with self.lock:
            self.backoff_multiplier = max(1.0, self.backoff_multiplier * 0.95)
```

**Layer 2: Reactive Retry** (existing tenacity logic):
- Keep existing `@retry_on_rate_limit` decorator
- Handles unexpected 429s (if proactive limiting misconfigured)
- Uses exponential backoff with jitter

**Integration**:
```python
@retry_on_rate_limit  # Layer 2
def _call_api(self, method_name, *args, **kwargs):
    self.rate_limiter.acquire()  # Layer 1

    try:
        method = getattr(self.client.sdk, method_name)
        return method(*args, **kwargs)
    except Exception as e:
        if "429" in str(e) or "rate limit" in str(e).lower():
            self.rate_limiter.on_429_detected()
            raise RateLimitError(...) from e
        raise
```

**Alternatives Considered**:

1. **Leaky Bucket**: Rejected due to:
   - Smooths bursts (bad for variable API load patterns)
   - Less efficient bandwidth utilization

2. **Semaphore-Only**: Rejected due to:
   - No rate smoothing or burst handling
   - Too simplistic for API rate limiting

3. **requests-ratelimiter**: Rejected due to:
   - Less flexible than pyrate-limiter
   - HTTP-specific, harder to customize

**Configuration**:
- Default: 100 requests/minute, 10 requests/second burst
- Adaptive backoff on 429 detection
- Gradual recovery after successful requests

**Dependencies to Add**:
```bash
uv add pyrate-limiter
```

---

## 5. Progress Tracking Mechanism

### Decision: threading.Lock + Rich Progress (Multi-Task)

**Rationale**:
- `threading.Lock` is low-overhead, explicit, safe for compound operations
- Rich `Progress` class is thread-safe by design
- Per-content-type progress bars (clear, manageable UI)
- Built-in throughput calculation (items/second)

**Implementation Pattern**:

**Thread-Safe Metrics**:
```python
@dataclass
class ThreadSafeMetrics:
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _items_processed: int = 0
    _items_by_type: dict[int, int] = field(default_factory=dict)
    _errors: int = 0

    def increment_processed(self, content_type: int, count: int = 1):
        with self._lock:
            self._items_processed += count
            self._items_by_type[content_type] = (
                self._items_by_type.get(content_type, 0) + count
            )

    def snapshot(self):
        with self._lock:
            return {
                'total': self._items_processed,
                'by_type': dict(self._items_by_type),
                'errors': self._errors,
            }
```

**Rich Progress Integration**:
```python
class ParallelProgressTracker:
    def __init__(self, workers: int):
        self.workers = workers
        self.progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            MofNCompleteColumn(),
            ItemsPerSecondColumn(),  # Custom column
        )
        self.metrics = ThreadSafeMetrics()
        self.tasks = {}

    def add_content_type(self, content_type_name: str, total: int):
        task_id = self.progress.add_task(
            f"Extracting {content_type_name}",
            total=total,
        )
        self.tasks[content_type_name] = task_id

    def update(self, content_type_name: str, advance: int = 1):
        task_id = self.tasks[content_type_name]
        self.progress.update(task_id, advance=advance)
        self.metrics.increment_processed(content_type_name, advance)
```

**Worker Failure Isolation**:
```python
with ThreadPoolExecutor(max_workers=workers) as executor:
    futures = [executor.submit(worker, batch) for batch in batches]

    for future in as_completed(futures):
        try:
            if future.exception() is not None:
                # Worker failed - log and continue
                metrics.record_error(str(future.exception()))
            else:
                # Worker succeeded
                result = future.result()
        except Exception:
            # Unexpected error - log and continue
            continue
```

**Alternatives Considered**:

1. **queue.Queue for Counters**: Rejected due to:
   - Overkill for simple counter updates
   - Higher overhead than lock-based approach

2. **GIL-Based Atomicity**: Rejected due to:
   - Unsafe for compound operations like `count += 1`
   - Not guaranteed to be atomic in future Python versions

3. **Per-Worker Progress Bars**: Rejected due to:
   - Clutters UI with 10+ workers
   - Harder to understand overall progress

**Display Granularity**:
- Show per-content-type bars (e.g., "Extracting dashboards", "Extracting looks")
- NOT per-worker bars (avoids clutter with 50 workers)
- Final summary shows: total items, rate (items/sec), thread pool utilization

---

## Summary of Technical Decisions

| Component | Decision | Key Rationale |
|-----------|----------|---------------|
| **Threading Model** | ThreadPoolExecutor | I/O-bound tasks, low overhead, native looker-sdk support |
| **Work Distribution** | Producer-Consumer Queue | Best load balancing, checkpoint-compatible, moderate complexity |
| **SQLite Concurrency** | Thread-local connections + WAL + BEGIN IMMEDIATE | Eliminates contention, prevents deadlocks, 500+ items/sec |
| **Rate Limiting** | Token Bucket (pyrate-limiter) | Burst handling, thread-safe, adaptive backoff |
| **Progress Tracking** | Lock-based metrics + Rich multi-task | Low overhead, clear UI, thread-safe by design |

---

## Implementation Phases

### Phase 1: Core Parallelism (Minimal Viable Parallel Extraction)
1. Refactor `SQLiteContentRepository` to use thread-local connections
2. Add BEGIN IMMEDIATE to write transactions
3. Implement basic `ParallelOrchestrator` with producer-consumer pattern
4. Add `--workers` CLI option with validation (1-50)
5. Unit tests for thread safety

### Phase 2: Rate Limiting & Progress
1. Add `pyrate-limiter` dependency
2. Implement `AdaptiveRateLimiter` with 429 detection
3. Integrate `ParallelProgressTracker` with Rich
4. Add worker failure isolation
5. Integration tests for parallel extraction

### Phase 3: Optimization & Observability
1. Tune batch size and worker count for performance
2. Add metrics collection (items/sec, worker utilization)
3. Add logging for debugging (worker states, queue depths)
4. Performance benchmarking (target: 50k items in <15 min)
5. Documentation and examples

---

## Dependencies to Add

```bash
uv add pyrate-limiter  # Rate limiting with token bucket
```

**Note**: All other dependencies are standard library:
- `concurrent.futures.ThreadPoolExecutor` (stdlib)
- `threading` (stdlib)
- `queue.Queue` (stdlib)
- `rich.progress` (already in project via typer[all])

---

## Configuration Recommendations

```python
# Default values for parallel extraction
DEFAULT_WORKERS = min(os.cpu_count() or 1, 8)  # Safe default
MAX_WORKERS = 50  # Upper bound
MIN_WORKERS = 1   # Sequential fallback

# Work queue sizing
QUEUE_SIZE = DEFAULT_WORKERS * 100  # Bounded queue for backpressure

# Database configuration
DB_BUSY_TIMEOUT = 60.0  # 60 seconds
BATCH_SIZE = 100  # Items per transaction

# Rate limiting
API_REQUESTS_PER_MINUTE = 100
API_REQUESTS_PER_SECOND = 10  # Burst allowance
```

---

## Risk Mitigation

### Risk 1: Over-parallelization hitting API rate limits
**Mitigation**:
- Default to 8 workers (conservative)
- Adaptive rate limiter reduces all workers on 429
- User can tune `--workers` based on instance capacity

### Risk 2: SQLite write contention with 50 workers
**Mitigation**:
- Thread-local connections eliminate connection-level contention
- WAL mode supports concurrent reads + single writer
- Batched writes (100 items/txn) reduce transaction overhead
- Expected plateau at 16 workers (SQLite limitation)

### Risk 3: Memory exhaustion with large datasets
**Mitigation**:
- Bounded work queue (1000 items) prevents runaway buffering
- Existing `MemoryAwareBatchProcessor` monitors memory usage
- Streaming producer-consumer pattern (no full dataset in memory)

### Risk 4: Worker thread failures crash extraction
**Mitigation**:
- `as_completed()` pattern isolates failures
- ThreadPoolExecutor continues with remaining workers
- Error tracking with `ThreadSafeMetrics`
- Existing checkpoint system supports resume

---

## Testing Strategy

### Unit Tests
- Thread-safe counter updates (10 threads × 1000 increments)
- SQLite concurrency (50 threads writing simultaneously)
- Rate limiter coordination (workers respect shared limits)
- Progress tracker accuracy (concurrent updates)

### Integration Tests
- End-to-end parallel extraction (4 workers, mixed content types)
- Worker failure isolation (1 worker fails, others continue)
- Resume from checkpoint (interrupt mid-extraction, verify resume)
- API rate limit handling (simulate 429, verify backoff)

### Performance Benchmarks
- Throughput scaling (1, 2, 4, 8 workers)
- Memory usage under load (monitor with `MemoryAwareBatchProcessor`)
- Database write throughput (measure items/sec)
- Target: 50,000 items in <15 minutes with 10 workers
