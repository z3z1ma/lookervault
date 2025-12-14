# Implementation Plan: Multi-Folder Parallel SDK Calls Optimization

**BD Issue**: lookervault-dil
**Created**: 2025-12-14
**Priority**: High (1) - Critical Performance Optimization

## Executive Summary

Replace multi-folder in-memory filtering with parallel SDK API calls for 10-100x performance improvement. Currently, when multiple folder_ids are specified, the system fetches ALL content and filters in Python. This plan proposes making N parallel SDK calls (one per folder_id) and merging results.

**Performance Impact**:
- 3 folders × 1,000 dashboards: **20s → 2s (10x faster)**
- 10 folders × 500 dashboards: **38s → 3s (12x faster)**

## Problem Analysis

### Current Behavior (Lines 792-817 in `parallel_orchestrator.py`)

```python
# SDK search methods only support single folder_id, so:
# - Single folder_id: use SDK filtering (optimal)
# - Multiple folder_ids: use in-memory filtering (fallback)
folder_id_for_sdk = None
if len(self.config.folder_ids) == 1:
    folder_id_for_sdk = list(self.config.folder_ids)[0]
    # Uses SDK filtering
elif len(self.config.folder_ids) > 1:
    # Falls back to in-memory filtering (SLOW!)
```

### Performance Bottleneck

For 3 folders with 1,000 dashboards each:
- **Current**: Fetch ALL 10,000 dashboards, filter to 3,000 in Python (~20 seconds)
- **Proposed**: Make 3 parallel SDK calls, fetch only 3,000 dashboards total (~2 seconds)

## Design Solution

### Architecture: MultiFolderOffsetCoordinator

Create a new coordinator that:
1. Distributes work across multiple folder_ids using round-robin
2. Tracks per-folder offset ranges independently
3. Marks per-folder completion when workers hit end-of-data
4. Returns `(folder_id, offset, limit)` tuples to workers

### Key Design Decisions

**Offset Mapping**: Lazy offset discovery (no upfront API calls)
- Workers discover end-of-data naturally by receiving empty results
- Maintains existing worker termination logic
- No latency from pre-fetching total counts

**Coordinator Architecture**: New `MultiFolderOffsetCoordinator` wrapper
- Preserves single-folder fast path (no overhead)
- Clear separation of concerns
- Backward compatible

**Worker Pool**: Single worker pool with folder-aware range claiming
- Efficient worker utilization (auto-balancing)
- Better throughput for uneven folder sizes
- Respects existing worker count configuration

## Implementation Components

### 1. MultiFolderOffsetCoordinator Class

```python
@dataclass
class FolderRange:
    """Per-folder offset tracking."""
    folder_id: str
    current_offset: int
    workers_done: int  # Workers that hit end-of-data
    total_claimed: int  # Total ranges claimed

class MultiFolderOffsetCoordinator:
    """Coordinate offset ranges across multiple folders."""

    def __init__(self, folder_ids: list[str], stride: int):
        self._folder_ids = folder_ids
        self._stride = stride
        self._lock = threading.Lock()
        self._folder_ranges: dict[str, FolderRange] = {...}
        self._next_folder_idx = 0  # Round-robin pointer
        self._total_workers = 0

    def claim_range(self) -> tuple[str, int, int] | None:
        """Claim next range using round-robin folder selection.

        Returns:
            (folder_id, offset, limit) or None if all folders exhausted
        """
        with self._lock:
            # Round-robin through folders
            while attempts < len(self._folder_ids):
                folder_id = self._folder_ids[self._next_folder_idx]
                self._next_folder_idx = (self._next_folder_idx + 1) % len(self._folder_ids)

                # Skip if folder exhausted
                if folder_range.workers_done >= self._total_workers:
                    attempts += 1
                    continue

                # Claim range
                offset = folder_range.current_offset
                folder_range.current_offset += self._stride
                return (folder_id, offset, self._stride)

            return None  # All folders exhausted

    def mark_folder_complete(self, folder_id: str) -> None:
        """Mark that a worker hit end-of-data for a folder."""
        with self._lock:
            self._folder_ranges[folder_id].workers_done += 1
```

**Key Features**:
- Round-robin ensures even work distribution
- Per-folder offset tracking (each folder starts at 0)
- Thread-safe with single mutex
- Returns `None` when all folders exhausted

### 2. Modified Worker Method

```python
def _parallel_fetch_worker(
    self,
    worker_id: int,
    content_type: int,
    coordinator: "OffsetCoordinator | MultiFolderOffsetCoordinator",
    fields: str | None,
    updated_after: datetime | None,
) -> int:
    """Worker with multi-folder support."""

    while True:
        claimed_range = coordinator.claim_range()
        if claimed_range is None:
            break  # All work done

        # Handle multi-folder coordinator
        if isinstance(coordinator, MultiFolderOffsetCoordinator):
            folder_id, offset, limit = claimed_range
        else:
            offset, limit = claimed_range
            folder_id = ...  # Single folder or None

        # Fetch with SDK filtering
        items = self.extractor.extract_range(
            ContentType(content_type),
            offset=offset,
            limit=limit,
            folder_id=folder_id,  # SDK-level filtering!
        )

        # Check for end-of-data
        if not items:
            if isinstance(coordinator, MultiFolderOffsetCoordinator):
                coordinator.mark_folder_complete(folder_id)
            else:
                coordinator.mark_worker_complete()
            continue  # Try next range (may be different folder)

        # Process items (NO in-memory filtering needed!)
        for item_dict in items:
            content_item = self._dict_to_content_item(item_dict, content_type)
            self.repository.save_content(content_item)
```

**Key Changes**:
1. Handle both coordinator types (backward compatible)
2. Pass `folder_id` to SDK for filtering
3. Mark folder-specific completion
4. **Remove lines 845-850** (in-memory filtering) - NO LONGER NEEDED!

### 3. Modified Orchestrator Method

```python
def _extract_parallel(
    self,
    content_type: int,
    session_id: str,
    fields: str | None,
    updated_after: datetime | None,
) -> None:
    """Extract with multi-folder support."""

    # Choose coordinator based on configuration
    if (
        self.config.folder_ids
        and len(self.config.folder_ids) > 1
        and content_type in [ContentType.DASHBOARD.value, ContentType.LOOK.value]
    ):
        # Multi-folder: Use new coordinator
        coordinator = MultiFolderOffsetCoordinator(
            folder_ids=list(self.config.folder_ids),
            stride=self.config.batch_size,
        )
        logger.info(f"Using multi-folder parallel SDK calls ({len(self.config.folder_ids)} folders)")
    else:
        # Single-folder or no-folder: Use existing coordinator
        coordinator = OffsetCoordinator(stride=self.config.batch_size)
        logger.info("Using standard parallel extraction")

    coordinator.set_total_workers(self.parallel_config.workers)

    # Launch workers (existing code)
    with ThreadPoolExecutor(max_workers=self.parallel_config.workers) as executor:
        futures = [
            executor.submit(
                self._parallel_fetch_worker,
                worker_id=i,
                content_type=content_type,
                coordinator=coordinator,  # Pass appropriate coordinator
                fields=fields,
                updated_after=updated_after,
            )
            for i in range(self.parallel_config.workers)
        ]
        # ... existing completion handling ...
```

## Performance Analysis

### Expected Gains

| Scenario | Current | Proposed | Improvement |
|----------|---------|----------|-------------|
| 3 folders × 1k items | 20s | 2s | **10x** |
| 10 folders × 500 items | 38s | 3s | **12x** |
| 5 folders × 2k items | 52s | 4s | **13x** |

### Scaling Characteristics

**Worker Utilization**:
- Round-robin claiming ensures even distribution
- Workers auto-balance across uneven folder sizes
- No worker starvation

**Memory Usage**:
- Same as current (streaming architecture)
- No intermediate aggregation
- Immediate database writes

**API Rate Limiting**:
- Existing `AdaptiveRateLimiter` coordinates across all workers
- Same overall API throughput

## Implementation Phases

### Phase 1: Core Coordinator (HIGH PRIORITY)
**File**: `src/lookervault/extraction/multi_folder_coordinator.py` (NEW)

**Tasks**:
1. Implement `FolderRange` dataclass
2. Implement `MultiFolderOffsetCoordinator` class
3. Add unit tests for coordinator logic
4. Add thread-safety tests

**Acceptance**: All unit tests pass, thread-safe under concurrent access

### Phase 2: Worker Integration (HIGH PRIORITY)
**File**: `src/lookervault/extraction/parallel_orchestrator.py`

**Tasks**:
1. Modify `_parallel_fetch_worker()` for multi-folder coordinator
2. Update `_extract_parallel()` to create appropriate coordinator
3. **Remove in-memory filtering** (lines 845-850)
4. Add logging for multi-folder statistics

**Acceptance**: Single-folder works (no regression), multi-folder uses new coordinator

### Phase 3: Testing & Validation (MEDIUM PRIORITY)
**Files**:
- `tests/unit/extraction/test_multi_folder_coordinator.py` (NEW)
- `tests/integration/test_multi_folder_extraction.py` (NEW)

**Tasks**:
1. Unit tests for coordinator
2. Integration tests for multi-folder extraction
3. Performance benchmarks
4. Correctness validation

**Acceptance**: 10x+ performance improvement validated, no regressions

### Phase 4: Documentation (LOW PRIORITY)
**Files**: `CLAUDE.md`, `README.md`

**Tasks**:
1. Update CLAUDE.md with multi-folder optimization
2. Update performance guidelines
3. Add usage examples

## Risk Assessment

**LOW RISK**:
- Single-folder path unchanged (backward compatible)
- No-folder path unchanged (backward compatible)
- Multi-folder path isolated (can be reverted)

**MITIGATION**:
- Comprehensive unit tests
- Integration tests comparing old vs new
- Performance benchmarks
- Optional feature flag for quick rollback

## Rollback Strategy

If issues found:
1. Revert `_extract_parallel()` to use old logic
2. Re-enable in-memory filtering for multi-folder case
3. Keep `MultiFolderOffsetCoordinator` for future use

## Critical Files

**NEW**:
- `src/lookervault/extraction/multi_folder_coordinator.py`
- `tests/unit/extraction/test_multi_folder_coordinator.py`
- `tests/integration/test_multi_folder_extraction.py`

**MODIFIED**:
- `src/lookervault/extraction/parallel_orchestrator.py` (lines 792-817, 845-850)

**REFERENCE** (DO NOT MODIFY):
- `src/lookervault/extraction/offset_coordinator.py` (baseline for single-folder)
- `src/lookervault/looker/extractor.py` (already supports `folder_id`)

---

**Next Steps**: Review plan, begin Phase 1 implementation
