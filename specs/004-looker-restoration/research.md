# Research: Looker Content Restoration

**Feature**: 004-looker-restoration
**Date**: 2025-12-13
**Status**: Complete

## Overview

This document captures research findings for implementing Looker content restoration from SQLite backups to Looker instances via API operations. Research focused on Looker SDK capabilities, dependency ordering strategies, and parallelization patterns.

---

## 1. Looker SDK Update/Create Methods

### Decision

Use Looker SDK's native PATCH methods for updates and POST methods for creates. All operations are single-item (no bulk API support exists).

### Rationale

- **PATCH for updates**: Looker SDK provides `update_<resource>` methods that use HTTP PATCH, allowing partial updates of existing resources while preserving IDs
- **POST for creates**: Looker SDK provides `create_<resource>` methods that generate new IDs when resources don't exist in destination
- **No bulk operations**: Looker API 4.0 lacks bulk update/create endpoints, requiring iteration for multiple items (justifies parallel worker architecture)
- **Flexible input types**: SDK accepts both model instances and plain dictionaries, simplifying deserialization

### Method Signatures (Summary)

| Content Type | Update Method | Create Method | Write Model Type |
|--------------|---------------|---------------|------------------|
| Dashboard | `update_dashboard(id, WriteDashboard)` | `create_dashboard(WriteDashboard)` | `WriteDashboard` |
| Look | `update_look(id, WriteLookWithQuery)` | `create_look(WriteLookWithQuery)` | `WriteLookWithQuery` |
| Folder | `update_folder(id, UpdateFolder)` | `create_folder(CreateFolder)` | `UpdateFolder/CreateFolder` |
| User | `update_user(id, WriteUser)` | `create_user(WriteUser)` | `WriteUser` |
| Group | `update_group(id, WriteGroup)` | `create_group(WriteGroup)` | `WriteGroup` |
| Role | `update_role(id, WriteRole)` | `create_role(WriteRole)` | `WriteRole` |
| Board | `update_board(id, WriteBoard)` | `create_board(WriteBoard)` | `WriteBoard` |
| Scheduled Plan | `update_scheduled_plan(id, WriteScheduledPlan)` | `create_scheduled_plan(WriteScheduledPlan)` | `WriteScheduledPlan` |
| LookML Model | `update_lookml_model(name, WriteLookmlModel)` | `create_lookml_model(WriteLookmlModel)` | `WriteLookmlModel` |

**Note**: LookML Models use `name` for routing instead of numeric ID. Permission Sets and Model Sets are typically managed through Role objects.

### Alternatives Considered

- **Option A: Use bulk JSON imports** - Rejected because Looker API lacks generic bulk import endpoints
- **Option B: Use LookML for all content** - Rejected because user-defined dashboards/looks are not LookML-based
- **Option C: Direct database writes** - Rejected because it bypasses Looker's validation and audit logging

### Implementation Notes

- Deserialization must convert SQLite binary blobs (msgspec-encoded JSON) back to Looker SDK Write* model instances or plain dictionaries
- Error handling must distinguish between 404 (not found → create), 422 (validation error → dead letter queue), and 429 (rate limit → retry)
- The `fields` parameter can be used to reduce response payload sizes (return only `id` on create to verify success)

---

## 2. Dependency Ordering Strategy

### Decision

Use predetermined static dependency order based on Looker's resource relationships:

```
Users → Groups → Roles → Permission Sets → Model Sets → Folders →
LookML Models → Explores → Looks → Dashboards → Boards → Scheduled Plans
```

### Rationale

- **Predictable**: Content types have stable hierarchical relationships (e.g., dashboards always depend on looks/explores, looks depend on models)
- **Simple implementation**: Topological sort of content types (not individual items) avoids complex graph analysis
- **Looker constraints**: API enforces FK constraints (e.g., cannot create dashboard referencing non-existent folder)
- **No circular dependencies at type level**: Content types form a DAG (directed acyclic graph)

### Detailed Dependency Analysis

| Content Type | Depends On | Reasoning |
|--------------|------------|-----------|
| Users | (none) | Base entity, no dependencies |
| Groups | (none) | Can exist independently |
| Roles | Groups, Permission Sets, Model Sets | Roles assign permissions/models to groups |
| Permission Sets | (none) | Define what actions are allowed |
| Model Sets | LookML Models | Define which models are accessible |
| Folders | Users (owner), Folders (parent) | Hierarchical structure with ownership |
| LookML Models | (none) | Defined in LookML code, minimal API dependencies |
| Explores | LookML Models | Explores belong to models |
| Looks | Explores, Folders | Saved queries referencing explores |
| Dashboards | Looks, Folders, Users (owner) | Dashboards embed looks and reside in folders |
| Boards | Dashboards, Looks | Collections of dashboards/looks |
| Scheduled Plans | Dashboards, Looks, Users | Scheduled delivery of content |

### Handling Forward References

For content with forward references within the same type (e.g., Folder parent_id referencing another folder):

1. **First pass**: Create all items with forward references null-ed or using temporary placeholders
2. **Second pass**: Update items to restore forward references once all IDs are known

### Alternatives Considered

- **Option A: Dynamic dependency graph per restore session** - Rejected due to complexity; would require parsing all content_data blobs to extract FK references
- **Option B: Restore in arbitrary order and retry failures** - Rejected because excessive retries would be inefficient and unpredictable
- **Option C: User-specified ordering** - Rejected because users shouldn't need deep Looker schema knowledge

### Implementation Notes

- Use Python Enum for dependency order to ensure type safety
- Parallel workers should process content types sequentially but parallelize within each type
- Cross-instance migration (P3) may require ID translation during dependency resolution

---

## 3. Deserialization Strategy

### Decision

Use existing `storage/serializer.py` patterns to deserialize binary blobs into Looker SDK model instances or plain dictionaries.

### Rationale

- **Consistency**: Extraction uses msgspec (or similar) to serialize SDK objects to binary blobs; deserialization reverses this process
- **Type safety**: Looker SDK provides typed Write* models for all content types, enabling validation before API calls
- **Flexible input**: SDK accepts both typed models and plain dicts, allowing optimization (dicts are lighter-weight)

### Deserialization Flow

```
SQLite binary blob (content_data)
  → msgspec.json.decode()
  → Python dict
  → Optional: Convert to SDK Write* model for validation
  → Pass to sdk.create_* or sdk.update_*
```

### Alternatives Considered

- **Option A: Store as JSON strings instead of binary** - Rejected because extraction already uses binary blobs; changing storage format is out of scope
- **Option B: Always convert to SDK models** - Rejected because it adds overhead; plain dicts are sufficient for most cases
- **Option C: Custom deserialization per content type** - Rejected because it duplicates SDK logic; leverage SDK's existing deserialization

### Implementation Notes

- Examine `storage/serializer.py` to understand current serialization format
- Add error handling for corrupted blobs (log error, skip item, move to dead letter queue)
- Consider caching deserialized objects if the same content is referenced multiple times (e.g., folder ID used by many dashboards)

---

## 4. ID Mapping for Cross-Instance Migration

### Decision

Maintain a persistent `id_mappings` SQLite table with schema:

```sql
CREATE TABLE id_mappings (
    source_instance TEXT NOT NULL,     -- Source Looker instance URL
    content_type INTEGER NOT NULL,     -- ContentType enum value
    source_id TEXT NOT NULL,           -- Original ID from source instance
    destination_id TEXT NOT NULL,      -- New ID in destination instance
    created_at TEXT NOT NULL,          -- Timestamp of mapping creation
    PRIMARY KEY (source_instance, content_type, source_id)
);
```

### Rationale

- **Persistent mappings**: Enables incremental restore and future reference lookups
- **Instance-aware**: Supports multiple source instances (e.g., dev → prod, backup → new instance)
- **Simple queries**: Primary key on (instance, type, source_id) provides O(1) lookups
- **Bidirectional optional**: Can query destination → source if needed for reverse mappings

### Mapping Workflow

1. **On create**: After successful `create_*` call, record `source_id → new_id` mapping
2. **On reference resolution**: When restoring content with FK references (e.g., dashboard.folder_id), check if mapping exists and substitute destination ID
3. **On same-instance restore**: Skip ID mapping entirely (source_id == destination_id)

### Alternatives Considered

- **Option A: In-memory mapping only** - Rejected because mappings are lost on process restart; incremental restore would fail
- **Option B: Separate mapping file (JSON/CSV)** - Rejected because SQLite provides better query performance and atomicity
- **Option C: Store mappings in Looker metadata** - Rejected because Looker lacks custom metadata fields for this purpose

### Implementation Notes

- Add `--skip-id-mapping` flag for same-instance restores to optimize performance
- ID mapper should handle missing mappings gracefully (log warning if reference cannot be resolved)
- Consider adding `get_mapping()`, `set_mapping()`, `clear_mappings()` methods to repository

---

## 5. Dead Letter Queue Design

### Decision

Store failed restoration attempts in a `dead_letter_queue` SQLite table:

```sql
CREATE TABLE dead_letter_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,          -- RestorationSession ID
    content_id TEXT NOT NULL,          -- Original content ID
    content_type INTEGER NOT NULL,     -- ContentType enum value
    content_data BLOB NOT NULL,        -- Original content blob
    error_message TEXT NOT NULL,       -- Error details
    error_type TEXT NOT NULL,          -- Exception class name
    stack_trace TEXT,                  -- Full traceback
    retry_count INTEGER NOT NULL,      -- Number of retries attempted
    failed_at TEXT NOT NULL,           -- Timestamp of final failure
    INDEX idx_dlq_session (session_id),
    INDEX idx_dlq_content (content_type, content_id)
);
```

### Rationale

- **Detailed context**: Captures full error details (message, type, stack trace) for debugging
- **Retry tracking**: Records how many retries were attempted before moving to DLQ
- **Session association**: Links failures to specific restoration sessions for auditing
- **Content preservation**: Stores original content_data blob for manual retry/inspection

### DLQ Workflow

1. **Attempt restoration**: Try API call with retry logic (tenacity)
2. **On max retries exhausted**: Serialize failure details to DLQ table
3. **Continue processing**: Log DLQ entry, increment error count, move to next item
4. **Post-restore review**: Admin queries DLQ to inspect failures and decide on manual intervention

### Alternatives Considered

- **Option A: Log failures to file** - Rejected because structured database queries are more powerful than log parsing
- **Option B: Separate DLQ per content type** - Rejected because single table simplifies queries and reduces schema complexity
- **Option C: No DLQ, just fail fast** - Rejected because it prevents bulk restoration from completing when individual items fail

### Implementation Notes

- Add `lookervault restore dlq list` command to view DLQ entries
- Add `lookervault restore dlq retry` command to re-attempt failed items
- Consider adding `--max-dlq-size` limit to prevent DLQ from growing unbounded

---

## 6. Parallel Restoration Architecture

### Decision

Reuse existing parallel extraction infrastructure with modifications:

- **OffsetCoordinator**: Adapt for restoration to distribute content items across workers
- **AdaptiveRateLimiter**: Reuse as-is for coordinated API rate limiting
- **Metrics**: Reuse thread-safe metrics aggregation
- **Thread pool**: Use `concurrent.futures.ThreadPoolExecutor` with configurable worker count

### Rationale

- **Proven patterns**: Extraction already achieves 400-600 items/second with 8-16 workers; same patterns apply to restoration
- **Thread-safe SQLite**: Existing thread-local connection pattern prevents write contention
- **Rate limit coordination**: All workers share rate limiter to respect API limits
- **Code reuse**: Minimizes new code by leveraging existing parallelization infrastructure

### Restoration-Specific Adaptations

1. **Work distribution**: Instead of offset ranges (extraction), use content IDs from SQLite queries
2. **Dependency batching**: Process one content type at a time (sequential type processing, parallel item processing within type)
3. **Checkpointing**: Track completed content IDs instead of offset ranges

### Workflow

```
Main thread:
  1. Query SQLite for content IDs of current type
  2. Distribute IDs to worker queue

Worker threads:
  1. Claim content ID from queue
  2. Fetch content_data from SQLite (thread-local connection)
  3. Deserialize content_data
  4. Check if destination ID exists (API call)
  5. Call update_* or create_* (API call with rate limiting)
  6. Record ID mapping if created
  7. Report success/failure to metrics
  8. On failure: retry or move to DLQ
```

### Alternatives Considered

- **Option A: Asyncio instead of threading** - Rejected because Looker SDK uses requests (synchronous), requiring thread pool anyway
- **Option B: Multiprocessing** - Rejected because SQLite connections cannot be shared across processes; thread-local pattern works for threads
- **Option C: Sequential restoration only** - Rejected because 50K items would take hours instead of minutes

### Implementation Notes

- Add `--workers` CLI flag (default: 8) matching extraction pattern
- Add progress bar showing: current type, items processed, success/failure counts, throughput
- Reuse existing `retry_on_rate_limit` decorator from `extraction/retry.py`

---

## 7. Validation Strategy

### Decision

Implement three validation stages:

1. **Pre-flight validation**: Check SQLite data integrity, Looker API connectivity
2. **Per-item validation**: Validate deserialized content against SDK model schemas
3. **API validation**: Let Looker API reject invalid content (capture 422 errors)

### Rationale

- **Early detection**: Pre-flight checks fail fast if fundamental issues exist (corrupted DB, auth failure)
- **Type safety**: SDK model validation catches schema mismatches before API calls
- **Leverage API**: Looker's validation is authoritative; SDK client-side validation is advisory

### Validation Checks

#### Pre-flight Validation
- SQLite file exists and is readable
- SQLite schema matches expected version
- Looker API is reachable (test connection)
- Looker API credentials are valid (test authentication)
- Destination instance version compatible with content types

#### Per-Item Validation
- Content blob deserialization succeeds (not corrupted)
- Deserialized data conforms to SDK Write* model schema (if using typed models)
- Required fields are present (e.g., `name` for folders)

#### API Validation (Error Handling)
- 422 Unprocessable Entity → Validation error → Move to DLQ
- 404 Not Found (on update) → Switch to create
- 409 Conflict (e.g., duplicate name) → Log warning, skip or move to DLQ
- 429 Rate Limit → Retry with backoff

### Alternatives Considered

- **Option A: Strict client-side validation only** - Rejected because API validation is more accurate and evolves with Looker versions
- **Option B: No validation, rely on API** - Rejected because deserialization errors would crash workers
- **Option C: Schema validation against OpenAPI spec** - Rejected as over-engineering; SDK models provide sufficient validation

### Implementation Notes

- Add `--dry-run` flag that validates all content without making API calls
- Add `--skip-validation` flag for advanced users who want to bypass client-side checks
- Log validation errors with full context (content ID, type, error message)

---

## 8. Error Handling Patterns

### Decision

Use layered error handling:

1. **Retry layer**: tenacity retry with exponential backoff for transient errors (429, 5xx, network timeouts)
2. **Dead letter queue**: Capture unrecoverable errors after max retries (422, 4xx, deserialization failures)
3. **Graceful degradation**: Continue processing remaining items after individual failures

### Rationale

- **Transient errors common**: Network issues, rate limits, temporary Looker unavailability are expected in large-scale operations
- **Unrecoverable errors exist**: Validation errors (422) won't resolve with retries
- **Bulk operations resilient**: One bad item shouldn't block 49,999 other items

### Error Classification

| Error Type | HTTP Code | Strategy |
|------------|-----------|----------|
| Rate limit | 429 | Retry with exponential backoff (tenacity + adaptive rate limiter) |
| Validation error | 422 | Move to DLQ immediately (no retries) |
| Not found (on update) | 404 | Switch to create operation |
| Server error | 500-599 | Retry up to max attempts |
| Network timeout | N/A | Retry up to max attempts |
| Deserialization error | N/A | Move to DLQ immediately |
| Authentication error | 401 | Fail entire session (not retryable) |

### Retry Configuration

```python
@retry(
    retry=retry_if_exception_type((RateLimitError, NetworkError)),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(5),
    reraise=True
)
```

### Alternatives Considered

- **Option A: Fail fast on first error** - Rejected because transient errors would unnecessarily stop bulk operations
- **Option B: Infinite retries** - Rejected because permanent errors (422) would loop forever
- **Option C: Retry all error types** - Rejected because validation errors won't improve with retries

### Implementation Notes

- Reuse existing `retry_on_rate_limit` decorator from `extraction/retry.py`
- Add restoration-specific exceptions: `RestorationError`, `ValidationError`, `DependencyError`
- Log all errors with structured context (session ID, content ID, error type, retry count)

---

## 9. Checkpointing & Resume Strategy

### Decision

Use `restoration_checkpoints` table to track progress:

```sql
CREATE TABLE restoration_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    content_type INTEGER NOT NULL,
    checkpoint_data TEXT NOT NULL,       -- JSON: {"completed_ids": [...], "last_updated": "..."}
    started_at TEXT NOT NULL,
    completed_at TEXT,
    item_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    INDEX idx_checkpoint_session (session_id)
);
```

### Rationale

- **Resume capability**: After interruption (Ctrl+C, crash, network failure), restore can continue from last checkpoint
- **Progress tracking**: Shows which content types are complete vs. in-progress
- **Granular checkpoints**: Every 100 items (configurable) to minimize repeat work

### Checkpoint Workflow

1. **Session start**: Create checkpoint record for current content type
2. **During processing**: Update `checkpoint_data` JSON with completed IDs every 100 items
3. **On completion**: Set `completed_at` timestamp
4. **On resume**: Query for incomplete checkpoints, extract `completed_ids`, filter them out of restoration query

### Alternatives Considered

- **Option A: File-based checkpoints** - Rejected because SQLite provides atomicity and easier querying
- **Option B: No checkpoints, restart from beginning** - Rejected because 10-minute restoration would restart from 0% on any interruption
- **Option C: Checkpoint every item** - Rejected because SQLite write overhead would reduce throughput

### Implementation Notes

- Add `--resume` flag to continue from last checkpoint
- Add `lookervault restore status` command to show checkpoint progress
- Add `--checkpoint-interval` flag (default: 100) for tuning checkpoint frequency

---

## 10. CLI Interface Design

### Decision

```bash
# Single-item restoration (P1 - MVP)
lookervault restore single <content-type> <content-id> [options]

# Bulk restoration by type (P2)
lookervault restore bulk <content-type> [options]

# Bulk restoration all types (P2)
lookervault restore all [options]

# Resume interrupted restoration (P2)
lookervault restore resume [options]

# Dead letter queue management
lookervault restore dlq list [options]
lookervault restore dlq retry <dlq-id> [options]

# Common options:
  --db-path PATH              # SQLite backup database path
  --dry-run                   # Validate without making changes
  --workers N                 # Parallel workers (default: 8)
  --rate-limit-per-minute N   # API rate limit
  --rate-limit-per-second N   # Burst rate limit
  --skip-if-modified          # Skip content modified in destination since backup
  --json                      # Machine-readable output
```

### Rationale

- **Granular testing**: `single` command enables P1 production testing on one item
- **Flexible bulk**: `bulk` per-type and `all` for full restoration
- **Resume support**: `resume` command leverages checkpoint infrastructure
- **DLQ management**: Built-in commands for reviewing/retrying failures
- **Consistent with extraction**: Mirrors existing `lookervault extract` patterns

### Alternatives Considered

- **Option A: Single `restore` command with filters** - Rejected because it's less intuitive than separate subcommands
- **Option B: Interactive mode for confirmations** - Rejected because it breaks automation; use `--confirm` flags instead
- **Option C: GUI tool** - Rejected because CLI-first is constitutional requirement

### Implementation Notes

- Use typer for CLI framework (existing dependency)
- Add rich progress bars for real-time feedback
- Return exit code 0 only if all items succeeded (or moved to DLQ gracefully)

---

## Summary of Key Decisions

| Decision Area | Chosen Approach | Key Rationale |
|---------------|-----------------|---------------|
| **SDK Operations** | PATCH for updates, POST for creates | Native SDK methods, no bulk API available |
| **Dependency Order** | Static predetermined order (Users → ... → Scheduled Plans) | Simple, predictable, avoids graph analysis |
| **Deserialization** | Reuse existing serializer, convert to SDK models or dicts | Consistency with extraction, type safety |
| **ID Mapping** | Persistent SQLite table (source_instance, type, source_id → dest_id) | Cross-instance migration support |
| **Dead Letter Queue** | SQLite table with full error context | Graceful degradation, post-restore review |
| **Parallelization** | Reuse extraction infrastructure (thread pool, rate limiter, metrics) | Proven performance, code reuse |
| **Validation** | Pre-flight + per-item + API validation | Early failure detection, leverage authoritative API |
| **Error Handling** | Retry transient, DLQ permanent, graceful degradation | Resilience without infinite loops |
| **Checkpointing** | SQLite table with completed IDs, every 100 items | Resume capability, progress tracking |
| **CLI Interface** | Subcommands for single/bulk/resume/dlq | Granular testing, intuitive, consistent |

---

## Open Questions (None)

All technical unknowns resolved through research. Ready to proceed to Phase 1 design (data model, contracts).
