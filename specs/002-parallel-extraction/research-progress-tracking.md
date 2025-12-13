# Research: Thread-Safe Progress Tracking and Aggregation for Multi-Worker Python CLI

**Date**: 2025-12-13
**Context**: Parallel content extraction feature for LookerVault
**Requirements**: Track progress across 1-50 worker threads, aggregate metrics, display real-time progress, handle worker failures gracefully

## Executive Summary

For the parallel extraction feature, the recommended approach is:

1. **Thread-Safe Counters**: Use `threading.Lock` for simple atomic counters (not queue-based)
2. **Progress Aggregation**: Use Rich's built-in thread-safe `Progress` class with per-worker tasks
3. **Metrics Collection**: Implement a `ThreadSafeMetrics` class using locks for aggregation
4. **Error Tracking**: Use `concurrent.futures.Future.exception()` to detect worker failures without stopping other workers
5. **Display Pattern**: Single Rich `Progress` instance with multiple tasks (one per content type or worker group)

## 1. Thread-Safe Counter Implementation

### Option A: threading.Lock (RECOMMENDED)

**Pros**:
- Minimal overhead for simple counters
- Native Python stdlib, no dependencies
- Explicit control over critical sections
- Best performance for simple increment operations

**Cons**:
- Requires manual acquire/release (use context manager)
- Potential for deadlock if not carefully managed

**Implementation Pattern**:

```python
import threading
from dataclasses import dataclass, field
from typing import Dict

@dataclass
class ThreadSafeMetrics:
    """Thread-safe metrics aggregator for parallel workers."""

    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _items_processed: int = field(default=0, init=False, repr=False)
    _items_failed: int = field(default=0, init=False, repr=False)
    _items_by_type: Dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _worker_errors: Dict[int, str] = field(default_factory=dict, init=False, repr=False)

    def increment_processed(self, count: int = 1, content_type: str | None = None) -> None:
        """Thread-safe increment of processed items counter."""
        with self._lock:
            self._items_processed += count
            if content_type:
                self._items_by_type[content_type] = self._items_by_type.get(content_type, 0) + count

    def increment_failed(self, count: int = 1) -> None:
        """Thread-safe increment of failed items counter."""
        with self._lock:
            self._items_failed += count

    def record_worker_error(self, worker_id: int, error: str) -> None:
        """Thread-safe recording of worker error."""
        with self._lock:
            self._worker_errors[worker_id] = error

    @property
    def items_processed(self) -> int:
        """Thread-safe read of processed items count."""
        with self._lock:
            return self._items_processed

    @property
    def items_failed(self) -> int:
        """Thread-safe read of failed items count."""
        with self._lock:
            return self._items_failed

    def snapshot(self) -> Dict:
        """Thread-safe snapshot of all metrics."""
        with self._lock:
            return {
                "items_processed": self._items_processed,
                "items_failed": self._items_failed,
                "items_by_type": self._items_by_type.copy(),
                "worker_errors": self._worker_errors.copy(),
            }
```

**References**:
- [Thread-Safe Counter in Python - Super Fast Python](https://superfastpython.com/thread-safe-counter-in-python/)
- [Python Thread Safety: Using a Lock - Real Python](https://realpython.com/python-thread-lock/)
- [An atomic, thread-safe incrementing counter for Python](https://gist.github.com/benhoyt/8c8a8d62debe8e5aa5340373f9c509c7)

### Option B: queue.Queue (NOT RECOMMENDED for counters)

**Why not Queue**:
- Overkill for simple shared state
- Designed for producer-consumer scenarios, not shared counters
- Higher overhead due to internal locking + queue management
- Would require separate consumer thread to aggregate metrics

**When to use Queue**: Producer-consumer patterns where workers produce items that need ordered processing.

**References**:
- [Thread-Safe Queue in Python - Super Fast Python](https://superfastpython.com/thread-queue/)
- [Queue – A thread-safe FIFO implementation - Python Module of the Week](https://pymotw.com/2/Queue/)

### Option C: Atomic Operations (LIMITED USE)

**Note**: Some operations in Python are atomic due to GIL (Global Interpreter Lock):
- Reading/assigning simple variables (single bytecode instruction)
- Appending to lists
- dict operations are NOT atomic

**Why not rely on GIL atomicity**:
- `count += 1` is NOT atomic (LOAD, ADD, STORE = 3 operations)
- GIL behavior may change (Python 3.13+ has optional free-threaded builds)
- Explicit locking is safer and more maintainable

**References**:
- [Atomic and thread safe in Python World - Python Discussions](https://discuss.python.org/t/atomic-and-thread-safe-in-python-world/51575)
- [Thread Safety - Python Concurrency for Senior Engineering](https://www.educative.io/courses/python-concurrency-for-senior-engineering-interviews/xlm6QznGGNE)

## 2. Progress Aggregation with Rich Library

### Recommended Pattern: Multiple Tasks in Single Progress Instance

Rich's `Progress` class is thread-safe and supports multiple concurrent tasks, making it ideal for parallel worker tracking.

**Implementation Pattern**:

```python
from rich.progress import (
    Progress,
    BarColumn,
    MofNCompleteColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    SpinnerColumn,
)
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

class ParallelProgressTracker:
    """Progress tracker for parallel extraction with per-content-type tracking."""

    def __init__(self, max_workers: int):
        self.max_workers = max_workers
        self._progress: Progress | None = None
        self._tasks: dict[str, int] = {}  # content_type -> task_id
        self._lock = threading.Lock()

    def __enter__(self):
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        )
        self._progress.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._progress:
            self._progress.__exit__(exc_type, exc_val, exc_tb)
        return False

    def add_content_type(self, content_type: str, total: int) -> None:
        """Add a new content type to track."""
        if self._progress:
            with self._lock:
                task_id = self._progress.add_task(
                    f"[cyan]Extracting {content_type}...",
                    total=total
                )
                self._tasks[content_type] = task_id

    def update(self, content_type: str, advance: int = 1) -> None:
        """Thread-safe update of content type progress."""
        if self._progress and content_type in self._tasks:
            # Rich Progress.update() is thread-safe
            self._progress.update(self._tasks[content_type], advance=advance)

    def mark_complete(self, content_type: str) -> None:
        """Mark content type extraction as complete."""
        if self._progress and content_type in self._tasks:
            self._progress.update(self._tasks[content_type], completed=True)
```

**Key Points**:
- Rich's `Progress.update()` is thread-safe - can be called from multiple threads
- Each content type gets its own progress bar (task)
- Workers can update progress concurrently without additional locking
- Progress display auto-refreshes (default 10 Hz)

**Example Usage with ThreadPoolExecutor**:

```python
def extract_content_batch(content_type: str, items: list, progress_tracker, metrics):
    """Worker function to extract a batch of content."""
    for item in items:
        try:
            # Extract item...
            result = extract_item(item)

            # Update progress (thread-safe)
            progress_tracker.update(content_type, advance=1)
            metrics.increment_processed(1, content_type)
        except Exception as e:
            metrics.increment_failed(1)
            # Continue processing other items

    return len(items)

def parallel_extract(content_types: dict, max_workers: int = 8):
    """Extract content in parallel across multiple workers."""

    metrics = ThreadSafeMetrics()

    with ParallelProgressTracker(max_workers) as progress:
        # Add tasks for each content type
        for content_type, items in content_types.items():
            progress.add_content_type(content_type, total=len(items))

        # Submit work to thread pool
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for content_type, items in content_types.items():
                # Split items into batches for better distribution
                batch_size = max(1, len(items) // max_workers)
                for i in range(0, len(items), batch_size):
                    batch = items[i:i+batch_size]
                    future = executor.submit(
                        extract_content_batch,
                        content_type,
                        batch,
                        progress,
                        metrics
                    )
                    futures.append((future, content_type))

            # Process results as they complete
            for future, content_type in futures:
                try:
                    result = future.result()
                except Exception as e:
                    # Worker failed, but others continue
                    metrics.record_worker_error(id(future), str(e))
                    print(f"[red]Worker failed for {content_type}: {e}[/red]")

    return metrics.snapshot()
```

**References**:
- [Progress Display — Rich Documentation](https://rich.readthedocs.io/en/stable/progress.html)
- [Multi-threading and Multi-processing Progress Visualization with Python's rich Library](https://liumaoli.me/notes/notes-about-rich/)
- [How to Show Progress for Tasks With the ThreadPoolExecutor in Python](https://superfastpython.com/threadpoolexecutor-progress/)

### Alternative: Per-Worker Progress Bars

For more granular visibility, you can create a progress bar per worker:

```python
def add_worker_tasks(self, num_workers: int) -> None:
    """Add individual worker progress bars."""
    for i in range(num_workers):
        task_id = self._progress.add_task(
            f"[yellow]Worker {i+1}...",
            total=None,  # Indeterminate until work assigned
            start=False
        )
        self._worker_tasks[i] = task_id

def assign_work_to_worker(self, worker_id: int, total: int) -> None:
    """Assign work to a specific worker."""
    if worker_id in self._worker_tasks:
        self._progress.update(
            self._worker_tasks[worker_id],
            total=total
        )
        self._progress.start_task(self._worker_tasks[worker_id])
```

**When to use**:
- Debugging worker utilization
- Uneven work distribution requiring visibility
- Small number of workers (<10)

**When NOT to use**:
- Many workers (>20) - clutters display
- Even work distribution - aggregate by content type is clearer

## 3. Throughput Calculation (Items/Second)

### Implementation Pattern

```python
import time
from dataclasses import dataclass, field

@dataclass
class ThroughputTracker:
    """Track extraction throughput over time."""

    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _start_time: float = field(default_factory=time.time, init=False, repr=False)
    _last_update: float = field(default_factory=time.time, init=False, repr=False)
    _items_at_last_update: int = field(default=0, init=False, repr=False)

    def calculate_rate(self, total_items: int) -> tuple[float, float]:
        """Calculate current and average items/second.

        Returns:
            (average_rate, instantaneous_rate) in items/second
        """
        with self._lock:
            now = time.time()
            elapsed = now - self._start_time

            # Average rate since start
            avg_rate = total_items / elapsed if elapsed > 0 else 0.0

            # Instantaneous rate since last update
            time_delta = now - self._last_update
            items_delta = total_items - self._items_at_last_update
            inst_rate = items_delta / time_delta if time_delta > 0 else 0.0

            # Update tracking
            self._last_update = now
            self._items_at_last_update = total_items

            return (avg_rate, inst_rate)
```

**Display in Rich Progress**:

```python
from rich.progress import ProgressColumn, Task
from rich.text import Text

class ItemsPerSecondColumn(ProgressColumn):
    """Custom column to display items/second."""

    def __init__(self, throughput_tracker: ThroughputTracker, metrics: ThreadSafeMetrics):
        super().__init__()
        self.throughput_tracker = throughput_tracker
        self.metrics = metrics

    def render(self, task: Task) -> Text:
        """Render the items/second rate."""
        total_items = self.metrics.items_processed
        avg_rate, inst_rate = self.throughput_tracker.calculate_rate(total_items)
        return Text(f"{inst_rate:.1f} items/s (avg: {avg_rate:.1f})")

# Usage in Progress
progress = Progress(
    TextColumn("[bold blue]{task.description}"),
    BarColumn(),
    MofNCompleteColumn(),
    ItemsPerSecondColumn(throughput_tracker, metrics),
    TimeRemainingColumn(),
)
```

## 4. Worker Failure Handling

### Pattern: Continue on Failure with Error Tracking

ThreadPoolExecutor is resilient by design - worker failures don't crash other workers.

**Implementation**:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Any

def execute_with_error_tracking(
    tasks: list[tuple[Callable, tuple, dict]],
    max_workers: int,
    metrics: ThreadSafeMetrics,
    progress_tracker: ParallelProgressTracker
) -> dict[str, Any]:
    """Execute tasks with comprehensive error tracking.

    Args:
        tasks: List of (function, args, kwargs) tuples
        max_workers: Thread pool size
        metrics: Thread-safe metrics aggregator
        progress_tracker: Progress display

    Returns:
        Dictionary with results and error summary
    """
    results = []
    failed_tasks = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks and track futures
        future_to_task = {}
        for i, (func, args, kwargs) in enumerate(tasks):
            future = executor.submit(func, *args, **kwargs)
            future_to_task[future] = (i, func.__name__)

        # Process results as they complete
        for future in as_completed(future_to_task):
            task_id, task_name = future_to_task[future]

            try:
                # Check if task raised an exception
                if future.exception() is not None:
                    # Task failed
                    error = future.exception()
                    metrics.record_worker_error(task_id, str(error))
                    failed_tasks.append({
                        "task_id": task_id,
                        "task_name": task_name,
                        "error": str(error),
                    })
                    # Continue processing other tasks
                else:
                    # Task succeeded
                    result = future.result()
                    results.append(result)

            except Exception as e:
                # Unexpected error retrieving result
                metrics.record_worker_error(task_id, f"Unexpected error: {e}")
                failed_tasks.append({
                    "task_id": task_id,
                    "task_name": task_name,
                    "error": f"Unexpected: {e}",
                })

    return {
        "successful_results": results,
        "failed_tasks": failed_tasks,
        "success_count": len(results),
        "failure_count": len(failed_tasks),
    }
```

**Key Points**:
- `future.exception()` returns `None` if task succeeded, otherwise returns the exception
- `future.result()` re-raises any exception from the task
- Worker thread remains available after exception (pool is robust)
- Use `as_completed()` to process results as they finish (better for progress display)

**References**:
- [How to Handle Exceptions With the ThreadPoolExecutor in Python](https://superfastpython.com/threadpoolexecutor-exception-handling/)
- [Catching exceptions in Threadpool executors](https://stefanstanciulescu.com/blog/blog/programming/python-threadpool-exceptions/)

### Pattern: Retry Failed Tasks

For transient failures (network errors, rate limits), implement retry logic:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

def create_retryable_task(func: Callable, max_retries: int = 3) -> Callable:
    """Wrap a function with retry logic."""

    @retry(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    def retryable_func(*args, **kwargs):
        return func(*args, **kwargs)

    return retryable_func

# Usage
def extract_item_with_retry(item_id: str, client: LookerClient):
    """Extract single item with automatic retry."""
    retryable_extract = create_retryable_task(client.extract_item, max_retries=3)
    return retryable_extract(item_id)
```

**References**:
- [How to Retry Failed Tasks in the ThreadPoolExecutor in Python](https://superfastpython.com/threadpoolexecutor-retry-tasks/)

## 5. Worker Pool Configuration

### Recommended Default: min(cpu_count(), 8)

```python
import os

def get_default_worker_count() -> int:
    """Calculate sensible default worker count.

    Returns:
        Default worker count based on CPU cores and safety limits
    """
    cpu_count = os.cpu_count() or 1
    # Python 3.13 default: min(32, cpu_count + 4)
    # For I/O-bound API calls, use min(cpu_count, 8) as safer default
    return min(cpu_count, 8)
```

**Rationale**:
- I/O-bound tasks (API calls) benefit from more threads than CPU cores
- Limit to 8 prevents overwhelming Looker API with too many concurrent requests
- Users can override with `--workers` flag (1-50 range)

**Python 3.13 Note**: Default for ThreadPoolExecutor changed to `min(32, (os.cpu_count() or 1) + 4)` - more aggressive than our recommendation.

**References**:
- [ThreadPoolExecutor Best Practices in Python](https://superfastpython.com/threadpoolexecutor-best-practices/)
- [Understanding ThreadPoolExecutor](https://medium.com/@anupchakole/understanding-threadpoolexecutor-2eed095d21aa)

## 6. Integration Strategy for LookerVault

### Architecture Changes

```
extraction/
├── orchestrator.py      [MODIFY] Add parallel execution mode
├── progress.py          [MODIFY] Add ParallelProgressTracker
├── parallel.py          [NEW] ThreadSafeMetrics, ThroughputTracker
└── worker.py            [NEW] Worker task functions
```

### Orchestrator Integration

```python
# orchestrator.py modifications

class ExtractionOrchestrator:
    def __init__(
        self,
        extractor: ContentExtractor,
        repository: ContentRepository,
        serializer: ContentSerializer,
        progress: ProgressTracker,
        config: ExtractionConfig,
        max_workers: int = 1,  # NEW parameter
    ):
        self.extractor = extractor
        self.repository = repository
        self.serializer = serializer
        self.progress = progress
        self.config = config
        self.max_workers = max_workers

        # NEW: Parallel execution components
        if max_workers > 1:
            self.metrics = ThreadSafeMetrics()
            self.throughput = ThroughputTracker()

    def extract(self) -> ExtractionResult:
        """Run extraction (sequential or parallel based on config)."""
        if self.max_workers == 1:
            return self._extract_sequential()
        else:
            return self._extract_parallel()

    def _extract_parallel(self) -> ExtractionResult:
        """Parallel extraction implementation."""
        # Build list of extraction tasks
        tasks = []
        for content_type in self.config.content_types:
            # Get total count for progress tracking
            total = self._get_content_count(content_type)
            self.progress.add_content_type(content_type.name, total)

            # Split work into batches
            batch_size = self.config.batch_size
            for offset in range(0, total, batch_size):
                tasks.append((
                    self._extract_batch,
                    (content_type, offset, batch_size),
                    {}
                ))

        # Execute in parallel
        result = execute_with_error_tracking(
            tasks,
            self.max_workers,
            self.metrics,
            self.progress
        )

        # Build extraction result
        return self._build_result(result, self.metrics.snapshot())
```

### CLI Integration

```python
# cli/commands/extract.py modifications

@app.command()
def extract(
    config: Optional[Path] = None,
    output: str = "table",
    db: str = "looker.db",
    types: Optional[str] = None,
    batch_size: int = 100,
    workers: int = None,  # NEW parameter
    resume: bool = True,
    incremental: bool = False,
    verbose: bool = False,
    debug: bool = False,
) -> None:
    """Extract content from Looker instance.

    Args:
        workers: Number of parallel workers (default: auto-detect, max: 50)
    """
    # Determine worker count
    if workers is None:
        workers = get_default_worker_count()
    elif workers < 1 or workers > 50:
        raise typer.BadParameter("Workers must be between 1 and 50")

    # Create appropriate progress tracker
    if output == "json":
        progress_tracker = JsonProgressTracker()
    else:
        if workers > 1:
            progress_tracker = ParallelProgressTracker(workers)
        else:
            progress_tracker = RichProgressTracker()

    # Create orchestrator with parallelism
    orchestrator = ExtractionOrchestrator(
        extractor=extractor,
        repository=repository,
        serializer=serializer,
        progress=progress_tracker,
        config=extraction_config,
        max_workers=workers,
    )

    # Run extraction
    with progress_tracker:
        result = orchestrator.extract()

    # Display results including parallel metrics
    if output != "json" and workers > 1:
        console.print(f"\n[green]✓ Parallel extraction complete![/green]")
        console.print(f"Workers: {workers}")
        console.print(f"Throughput: {result.avg_items_per_second:.1f} items/s")
        if result.worker_errors:
            console.print(f"\n[yellow]⚠ Worker errors: {len(result.worker_errors)}[/yellow]")
```

## 7. Testing Strategy

### Unit Tests for Thread Safety

```python
# tests/unit/extraction/test_parallel.py

import threading
import pytest
from lookervault.extraction.parallel import ThreadSafeMetrics

def test_thread_safe_metrics_concurrent_updates():
    """Test that concurrent updates don't lose counts."""
    metrics = ThreadSafeMetrics()
    num_threads = 10
    increments_per_thread = 1000

    def worker():
        for _ in range(increments_per_thread):
            metrics.increment_processed(1)

    threads = [threading.Thread(target=worker) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Should have exact count despite concurrent updates
    assert metrics.items_processed == num_threads * increments_per_thread

def test_progress_tracker_concurrent_updates():
    """Test that Rich progress can handle concurrent updates."""
    from lookervault.extraction.progress import ParallelProgressTracker

    tracker = ParallelProgressTracker(max_workers=5)
    with tracker:
        tracker.add_content_type("dashboards", total=100)

        def worker():
            for _ in range(10):
                tracker.update("dashboards", advance=1)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify all updates were applied
        assert tracker._progress.tasks[tracker._tasks["dashboards"]].completed == 100
```

### Integration Tests for Worker Failure Handling

```python
# tests/integration/test_parallel_extraction.py

def test_extraction_continues_after_worker_failure():
    """Test that failed workers don't stop other workers."""

    def failing_task():
        raise ValueError("Simulated worker failure")

    def successful_task():
        return "success"

    tasks = [
        (failing_task, (), {}),
        (successful_task, (), {}),
        (successful_task, (), {}),
    ]

    metrics = ThreadSafeMetrics()
    result = execute_with_error_tracking(tasks, max_workers=3, metrics=metrics, progress_tracker=None)

    assert result["success_count"] == 2
    assert result["failure_count"] == 1
    assert len(result["successful_results"]) == 2
```

## 8. Performance Considerations

### Memory Management

- **Batch Processing**: Maintain existing batch processor to limit memory usage
- **Connection Pooling**: SQLite doesn't support true connection pooling, but thread-local connections work
- **Result Streaming**: Use `as_completed()` to process results as they arrive (don't accumulate all in memory)

### Database Concurrency (SQLite)

SQLite has limitations with concurrent writes:

**Recommended Approach**:
1. Workers read from API concurrently (I/O-bound, no contention)
2. Use a separate write queue for database operations (single-threaded writes)
3. Or: Use SQLite WAL mode for better concurrent write performance

```python
# Repository initialization with WAL mode
def __init__(self, db_path: str):
    self.db_path = db_path
    self.conn = sqlite3.connect(db_path, check_same_thread=False)
    # Enable WAL mode for better concurrency
    self.conn.execute("PRAGMA journal_mode=WAL")
```

**References**:
- [SQLite Write-Ahead Logging](https://www.sqlite.org/wal.html)

### Rate Limiting Coordination

For coordinated rate limiting across workers, implement a shared rate limiter:

```python
import threading
import time
from collections import deque

class SharedRateLimiter:
    """Shared rate limiter for multiple workers."""

    def __init__(self, max_requests_per_second: int = 10):
        self.max_requests = max_requests_per_second
        self.requests = deque(maxlen=max_requests_per_second)
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Wait until a request slot is available (blocks if necessary)."""
        with self._lock:
            now = time.time()

            # Remove requests older than 1 second
            while self.requests and self.requests[0] < now - 1.0:
                self.requests.popleft()

            # If at capacity, wait
            if len(self.requests) >= self.max_requests:
                sleep_time = 1.0 - (now - self.requests[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    # Try again after sleep
                    self.acquire()
                    return

            # Record this request
            self.requests.append(now)
```

## 9. Recommended Implementation Order

1. **Phase 1: Core Thread Safety**
   - Implement `ThreadSafeMetrics` class with lock-based counters
   - Add unit tests for concurrent updates

2. **Phase 2: Progress Tracking**
   - Extend `RichProgressTracker` to `ParallelProgressTracker`
   - Support multiple content-type tasks
   - Add throughput calculation

3. **Phase 3: Worker Pool Integration**
   - Modify `ExtractionOrchestrator` to support parallel mode
   - Implement work distribution (batch-based)
   - Add error tracking with `as_completed()`

4. **Phase 4: CLI Integration**
   - Add `--workers` parameter
   - Implement auto-detection of default worker count
   - Update progress display for parallel mode

5. **Phase 5: Advanced Features**
   - Shared rate limiter (if needed)
   - SQLite WAL mode for better write concurrency
   - Per-worker progress bars (optional)

## 10. Key Takeaways

### DO:
✅ Use `threading.Lock` for simple thread-safe counters
✅ Use Rich's built-in thread-safe `Progress` class
✅ Use `ThreadPoolExecutor` for I/O-bound API calls
✅ Use `as_completed()` for real-time result processing
✅ Track worker errors with `future.exception()`
✅ Calculate throughput with time-windowed averages
✅ Enable SQLite WAL mode for better write concurrency
✅ Validate worker count is in reasonable range (1-50)

### DON'T:
❌ Don't use `queue.Queue` for simple shared counters (overkill)
❌ Don't rely on GIL for atomicity (use explicit locks)
❌ Don't use `ProcessPoolExecutor` unless CPU-bound (serialization overhead)
❌ Don't create per-worker progress bars if >10 workers (clutters display)
❌ Don't accumulate all results in memory (use streaming with `as_completed()`)
❌ Don't stop all workers when one fails (isolate failures)
❌ Don't exceed reasonable thread pool size (max 50 workers)

## References

### Documentation
- [Rich Progress Display](https://rich.readthedocs.io/en/stable/progress.html)
- [concurrent.futures — Python 3.14 docs](https://docs.python.org/3/library/concurrent.futures.html)
- [threading — Python 3.14 docs](https://docs.python.org/3/library/threading.html)

### Tutorials & Examples
- [Multi-threading Progress Visualization with Rich - Maoli Liu](https://liumaoli.me/notes/notes-about-rich/)
- [Thread-Safe Counter in Python - Super Fast Python](https://superfastpython.com/thread-safe-counter-in-python/)
- [Python Thread Safety: Using a Lock - Real Python](https://realpython.com/python-thread-lock/)
- [ThreadPoolExecutor Exception Handling - Super Fast Python](https://superfastpython.com/threadpoolexecutor-exception-handling/)
- [ThreadPoolExecutor Best Practices - Super Fast Python](https://superfastpython.com/threadpoolexecutor-best-practices/)

### Advanced Topics
- [Understanding ThreadPoolExecutor - Medium](https://medium.com/@anupchakole/understanding-threadpoolexecutor-2eed095d21aa)
- [Atomic and thread safe in Python - Python Discussions](https://discuss.python.org/t/atomic-and-thread-safe-in-python-world/51575)
- [Thread-Safe Queue in Python - Super Fast Python](https://superfastpython.com/thread-queue/)
