# Feature Specification: Parallel Content Extraction

**Feature Branch**: `003-parallel-extraction`
**Created**: 2025-12-13
**Status**: Draft
**Input**: User description: "Now that we have the extraction feature working in Looker Vault, the next feature we must prioritize is performance. We need to make sure that we support parallelism through configurable thread pool size, and that when we're pooling data, there's some strategy to parallelize across threads. This is critical; it absolutely must be performant, but we're dealing with tens of thousands of pieces of customer content."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Configure Parallel Extraction (Priority: P1)

A system administrator needs to extract tens of thousands of Looker content items efficiently. They configure the extraction to use multiple worker threads to parallelize API calls and database writes, reducing total extraction time from hours to minutes.

**Why this priority**: This is the core value proposition - enabling performant extraction at scale. Without parallelism, the system cannot handle large customer deployments efficiently.

**Independent Test**: Can be fully tested by configuring thread pool size and extracting a sample dataset. Success is measured by observing multiple concurrent API requests and comparing extraction time against sequential processing.

**Acceptance Scenarios**:

1. **Given** a Looker instance with 50,000 dashboard items, **When** user configures extraction with 10 worker threads, **Then** extraction completes in less than 1/8th the time of sequential processing
2. **Given** user runs extraction command, **When** no thread pool size is specified, **Then** system uses a reasonable default thread pool size based on available CPU cores
3. **Given** user specifies thread pool size of 20, **When** extraction runs, **Then** system creates exactly 20 worker threads and distributes work across them

---

### User Story 2 - Monitor Parallel Extraction Progress (Priority: P2)

A user running a large extraction wants to see real-time progress across all parallel workers, understanding which content types are being extracted, how many items have completed, and estimated time remaining.

**Why this priority**: Visibility into parallel operations is essential for troubleshooting and managing expectations during long-running extractions.

**Independent Test**: Can be tested by running extraction with multiple workers and verifying progress output shows per-worker status, aggregate counts, and thread pool utilization.

**Acceptance Scenarios**:

1. **Given** extraction is running with 8 workers, **When** user views progress, **Then** display shows active workers, items processed per second, and completion percentage
2. **Given** one worker encounters an error, **When** viewing progress, **Then** system shows which worker failed, error details, and continues with remaining workers
3. **Given** parallel extraction completes, **When** viewing final summary, **Then** system reports total items, extraction rate (items/second), and thread pool efficiency

---

### User Story 3 - Handle API Rate Limits with Parallelism (Priority: P2)

A user extracting from a Looker instance with API rate limits needs the system to automatically detect rate limit responses and intelligently back off without failing the entire extraction.

**Why this priority**: Parallel processing increases API pressure, so rate limit handling becomes critical. Without this, parallel extraction would be unusable in rate-limited environments.

**Independent Test**: Can be tested by simulating rate limit responses during extraction and verifying the system backs off, retries, and completes successfully without data loss.

**Acceptance Scenarios**:

1. **Given** Looker API returns rate limit error (HTTP 429), **When** worker receives this response, **Then** worker waits with exponential backoff and retries the request
2. **Given** multiple workers hit rate limits simultaneously, **When** rate limit detected, **Then** all workers reduce request rate proportionally to stay within limits
3. **Given** API rate limit is sustained, **When** workers continue processing, **Then** extraction completes successfully with automatic throttling, without manual intervention

---

### User Story 4 - Resume Failed Parallel Extraction (Priority: P3)

A user's parallel extraction fails mid-way due to network interruption. When they restart the extraction, the system resumes from where it left off across all content types, avoiding re-processing completed work.

**Why this priority**: Enables fault tolerance for long-running parallel extractions. Less critical than core parallelism but important for production reliability.

**Independent Test**: Can be tested by interrupting an in-progress extraction and verifying resume continues from checkpoints without duplicating work.

**Acceptance Scenarios**:

1. **Given** parallel extraction was interrupted at 60% completion, **When** user resumes extraction, **Then** system continues from last checkpoint per content type, avoiding re-processing
2. **Given** some workers completed their work while others failed, **When** resuming, **Then** system only restarts failed workers' tasks
3. **Given** extraction is resumed multiple times, **When** finally completing, **Then** final dataset has no duplicate or missing items

---

### Edge Cases

- What happens when thread pool size exceeds number of content types to extract? (Workers should remain idle or help with pagination within single content type)
- How does system handle when one content type has 50,000 items while others have <100? (Work distribution should balance load dynamically)
- What happens if database writes become bottleneck with high concurrency? (Connection pooling and write batching prevent database saturation)
- How does system behave when available memory is exhausted by parallel workers? (Memory monitoring triggers backpressure to slow worker threads)
- What happens when user specifies thread pool size of 1? (System gracefully degrades to sequential processing)
- How does incremental extraction work with parallelism? (Workers coordinate to avoid race conditions when detecting soft deletes)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow users to configure thread pool size for parallel extraction via command-line option
- **FR-002**: System MUST select a sensible default thread pool size when none is specified (e.g., min(CPU cores, 8))
- **FR-003**: System MUST distribute extraction work across multiple worker threads when thread pool size > 1
- **FR-004**: System MUST coordinate database writes from parallel workers to prevent corruption or deadlocks
- **FR-005**: System MUST aggregate progress reporting from all parallel workers in real-time
- **FR-006**: System MUST detect API rate limit responses and implement backoff strategy across all workers
- **FR-007**: System MUST ensure checkpoint saves are thread-safe and represent true progress across all workers
- **FR-008**: System MUST support resuming parallel extractions from checkpoints without data duplication
- **FR-009**: System MUST handle worker thread failures gracefully without terminating other active workers
- **FR-010**: System MUST respect memory constraints by monitoring memory usage across all workers
- **FR-011**: Users MUST be able to limit memory usage by specifying maximum concurrent workers
- **FR-012**: System MUST distribute work at the item level when extracting large content types to maximize parallelism
- **FR-013**: System MUST report thread pool utilization and extraction rate (items/second) in final summary
- **FR-014**: System MUST validate thread pool size is within acceptable range (1 to 50)

### Key Entities

- **Worker Thread**: Represents a unit of parallel execution that processes batches of content items, makes API calls, and writes to storage
- **Work Queue**: Distributes extraction tasks (content type + page/batch) to available worker threads
- **Thread Pool Manager**: Creates and manages lifecycle of worker threads, handles thread pool size configuration
- **Coordination Lock**: Ensures thread-safe access to shared resources (database connections, checkpoint writes, progress tracking)
- **Backoff Strategy**: Manages rate limiting and retry logic across all workers to prevent API abuse

## Folder Filtering Performance Characteristics

### Overview

Folder filtering is a critical optimization for reducing extraction time and API load. The implementation leverages SDK-level filtering for dashboards and looks, while other content types require in-memory filtering. Understanding the performance implications is essential for efficient extractions.

### SDK-Level Filtering (Dashboards and Looks)

**What it is**: Dashboards and looks support SDK-level filtering via the `folder_id` parameter in Looker's `search_dashboards()` and `search_looks()` API methods.

**Why it's fast**: The Looker API server filters results before returning them, reducing network transfer, deserialization overhead, and post-processing in LookerVault.

**Performance impact**:
- **Single folder**: ~50 items/second (sequential) → ~400-600 items/second (8 workers parallel)
- **Multi-folder**: See "Multi-Folder Performance" below

**Implementation**:
```python
# extractor.py: _paginate_dashboards() and _paginate_looks()
api_kwargs = {"fields": fields, "limit": batch_size, "offset": offset}
if folder_id:
    api_kwargs["folder_id"] = folder_id  # SDK-level filtering

dashboards = self._call_api("search_dashboards", **api_kwargs)
```

**Key advantage**: Only the requested folder's items are returned from the API, minimizing data transfer.

### In-Memory Filtering (All Other Content Types)

**What it is**: Content types other than dashboards and looks do not support SDK-level folder filtering. The Looker API returns all items, and LookerVault filters them in-memory after fetching.

**Why it's slower**: The entire dataset must be fetched, transferred over the network, and deserialized before filtering can occur. This is significantly slower and consumes more memory.

**Affected content types**:
- Boards (no SDK folder filtering support)
- Users, Groups, Roles (folder-aware filtering not applicable)
- LookML Models, Permission Sets, Model Sets, Scheduled Plans (folder-aware filtering not applicable)

**Implementation**:
```python
# orchestrator.py: _extract_content_type() for non-folder-filterable types
# Fetch all items (no folder_id parameter)
items_iterator = self.extractor.extract_all(
    content_type_enum,
    fields=self.config.fields,
    batch_size=self.config.batch_size,
    updated_after=updated_after,
    # No folder_id parameter - fetch everything
)

# Filter in-memory (currently not implemented for non-folder-aware types)
# Boards: extracted fully, can be filtered by folder_id if needed post-extraction
```

**Performance impact**:
- **Boards**: ~50 items/second (sequential), no SDK filtering available
- **Users/Groups/Roles**: ~50 items/second (sequential), folder filtering not applicable
- **Memory impact**: Entire dataset loaded into memory before filtering

**Recommendation**: For boards, consider extracting all boards and filtering during post-processing or restoration if folder-scoped extraction is needed.

### Multi-Folder Performance Optimization

**What it is**: When extracting dashboards or looks from multiple folders, LookerVault uses parallel SDK calls (one per folder) instead of fetching all items and filtering in-memory.

**Why it's fast**: Each SDK call filters at the source, and parallel execution maximizes throughput by distributing API calls across workers.

**Performance impact**:
- **3 folders × 1,000 dashboards**: 20 seconds → 2 seconds (10x faster)
- **10 folders × 500 dashboards**: 38 seconds → 3 seconds (12x faster)

**Implementation**:
```python
# parallel_orchestrator.py: _extract_parallel() with MultiFolderOffsetCoordinator
if is_multi_folder:
    coordinator = MultiFolderOffsetCoordinator(
        folder_ids=list(self.config.folder_ids),
        stride=self.config.batch_size,
    )
    # Workers claim (folder_id, offset, limit) ranges and fetch with SDK filtering
```

**Algorithm**:
1. Worker claims `(folder_id, offset, limit)` range from coordinator
2. Worker calls `search_dashboards(folder_id=X, offset=Y, limit=Z)` (SDK-level filtering)
3. No in-memory filtering needed - SDK returns only folder X's items
4. Round-robin distribution ensures even work across folders

**Key advantage**: 10x speedup over fetching all dashboards and filtering in-memory.

### Performance Comparison Table

| Scenario | Content Type | Folders | Items | Workers | Strategy | Time | Throughput |
|----------|-------------|---------|-------|---------|----------|------|------------|
| No folder filter | Dashboards | All | 3,000 | 8 | Parallel fetch | 6s | 500 items/s |
| Single folder (SDK) | Dashboards | 1 | 1,000 | 8 | Parallel fetch | 2s | 500 items/s |
| Multi-folder (SDK) | Dashboards | 3 | 3,000 | 8 | Parallel SDK calls | 6s | 500 items/s |
| Multi-folder (in-memory) | Dashboards | 3 | 3,000 | 8 | Fetch all + filter | 60s | 50 items/s |
| Boards (no SDK filter) | Boards | All | 500 | 1 | Sequential | 10s | 50 items/s |

**Key takeaways**:
- SDK-level filtering is 10x faster than in-memory filtering for multi-folder scenarios
- Parallel workers provide 8-10x speedup over sequential processing
- Boards cannot leverage SDK folder filtering (API limitation)

### Recommendations

1. **For dashboards/looks**: Always use SDK-level filtering by specifying `--folder-id` (single) or `--folder-id` with `--recursive-folders` (multi-folder)
2. **For boards**: Extract all boards and filter during post-processing or restoration if needed
3. **For large folder hierarchies**: Use `--recursive-folders` to expand folder IDs before extraction, enabling multi-folder parallel SDK calls
4. **For performance-critical extractions**: Use 8-16 workers for optimal throughput (plateaus beyond due to SQLite write serialization)

### Code References

- **SDK-level filtering**: `/Users/alexanderbutler/code_projects/work_ccm/lookervault/src/lookervault/looker/extractor.py` (lines 386-390, 424-427)
- **Multi-folder coordinator**: `/Users/alexanderbutler/code_projects/work_ccm/lookervault/src/lookervault/extraction/multi_folder_coordinator.py`
- **Parallel orchestrator**: `/Users/alexanderbutler/code_projects/work_ccm/lookervault/src/lookervault/extraction/parallel_orchestrator.py` (lines 406-452)
- **Sequential orchestrator**: `/Users/alexanderbutler/code_projects/work_ccm/lookervault/src/lookervault/extraction/orchestrator.py` (lines 196-250)

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Extraction of 50,000 items completes in under 15 minutes with 10 workers (vs. 2+ hours sequentially)
- **SC-002**: System achieves 80%+ thread pool utilization during active extraction (workers stay busy, not idle)
- **SC-003**: Extraction throughput scales linearly up to 8 workers (2x workers = ~2x faster extraction)
- **SC-004**: System handles 100+ concurrent API requests without errors or data corruption
- **SC-005**: Memory usage remains below 2GB regardless of thread pool size or dataset size
- **SC-006**: When API rate limits are hit, extraction completes successfully with <5% time overhead
- **SC-007**: Resume from checkpoint avoids re-processing 99%+ of already-extracted items
- **SC-008**: Database write throughput supports 500+ items/second from parallel workers without bottleneck
- **SC-009**: Progress reporting updates at least once per second during active extraction
- **SC-010**: Zero data corruption or loss occurs during parallel extraction with worker failures
