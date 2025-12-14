# Quickstart: Looker Content Restoration

**Feature**: 004-looker-restoration
**Date**: 2025-12-13
**Status**: Complete

## Overview

This quickstart guide walks through implementing and testing the Looker content restoration feature. Follow this guide to build the feature incrementally, testing each component as you go.

---

## Prerequisites

1. Existing lookervault codebase with extraction working
2. SQLite backup database with extracted Looker content
3. Looker instance credentials (destination)
4. Python 3.13+ environment with dependencies installed

---

## Phase 1: Core Infrastructure (P0 - Foundation)

### Step 1.1: Database Schema Extensions

**Objective**: Add restoration tables to SQLite schema

**Files to modify**:
- `src/lookervault/storage/schema.py`

**Tasks**:
1. Add `restoration_sessions` table SQL
2. Add `restoration_checkpoints` table SQL
3. Add `id_mappings` table SQL
4. Add `dead_letter_queue` table SQL
5. Add indexes for query performance
6. Test schema creation manually

**Testing**:
```bash
# Create test database with new schema
python -c "
from lookervault.storage.schema import create_schema
from lookervault.storage.repository import SQLiteContentRepository
repo = SQLiteContentRepository('test_restore.db')
print('Schema created successfully')
"

# Verify tables exist
sqlite3 test_restore.db ".tables"
# Should show: restoration_sessions, restoration_checkpoints, id_mappings, dead_letter_queue
```

**Success criteria**: All 4 new tables created with correct indexes

---

### Step 1.2: Data Models

**Objective**: Add Python dataclasses for restoration

**Files to modify**:
- `src/lookervault/storage/models.py`

**Tasks**:
1. Add `RestorationSession` dataclass
2. Add `RestorationCheckpoint` dataclass
3. Add `IDMapping` dataclass
4. Add `DeadLetterItem` dataclass
5. Add `DependencyOrder` enum

**Testing**:
```python
from lookervault.storage.models import RestorationSession, RestorationCheckpoint, IDMapping, DeadLetterItem

# Test instantiation
session = RestorationSession(destination_instance="https://looker.company.com")
assert session.status == "pending"
assert session.success_count == 0

checkpoint = RestorationCheckpoint(content_type=1, checkpoint_data={})
assert checkpoint.item_count == 0

print("✓ All models instantiate correctly")
```

**Success criteria**: All dataclasses instantiate with correct defaults

---

### Step 1.3: Repository Extensions

**Objective**: Add restoration-specific repository methods

**Files to modify**:
- `src/lookervault/storage/repository.py`

**Tasks**:
1. Add session CRUD methods (`create_restoration_session`, `update_restoration_session`, etc.)
2. Add checkpoint CRUD methods
3. Add ID mapping methods
4. Add DLQ methods
5. Write unit tests for each method

**Testing**:
```python
from lookervault.storage.repository import SQLiteContentRepository
from lookervault.storage.models import RestorationSession, IDMapping, DeadLetterItem

repo = SQLiteContentRepository('test_restore.db')

# Test session creation
session = RestorationSession(destination_instance="https://looker.test")
repo.create_restoration_session(session)

# Test ID mapping
mapping = IDMapping(
    source_instance="https://source.test",
    content_type=1,
    source_id="123",
    destination_id="456"
)
repo.save_id_mapping(mapping)
retrieved = repo.get_destination_id("https://source.test", 1, "123")
assert retrieved == "456"

# Test DLQ
dlq_item = DeadLetterItem(
    session_id=session.id,
    content_id="789",
    content_type=1,
    content_data=b"test",
    error_message="Test error",
    error_type="ValueError",
    retry_count=5
)
dlq_id = repo.save_dead_letter_item(dlq_item)
assert dlq_id > 0

print("✓ All repository methods work")
```

**Success criteria**: All repository methods create/read/update/delete correctly

---

## Phase 2: Deserialization & Validation (P1 - MVP Foundation)

### Step 2.1: Content Deserializer

**Objective**: Deserialize SQLite blobs to Looker SDK models

**Files to create**:
- `src/lookervault/restoration/deserializer.py`
- `tests/unit/test_deserializer.py`

**Tasks**:
1. Implement `ContentDeserializer.deserialize()` method
2. Add support for all content types
3. Add schema validation
4. Write unit tests with sample data

**Testing**:
```python
from lookervault.restoration.deserializer import ContentDeserializer
from lookervault.storage.models import ContentType
import msgspec

# Create sample dashboard data
dashboard_data = {
    "title": "Test Dashboard",
    "folder_id": "5",
    "description": "Test"
}
blob = msgspec.json.encode(dashboard_data)

# Test deserialization
deserializer = ContentDeserializer()
result = deserializer.deserialize(blob, ContentType.DASHBOARD, as_dict=True)
assert result["title"] == "Test Dashboard"

# Test validation
errors = deserializer.validate_schema(result, ContentType.DASHBOARD)
assert len(errors) == 0

print("✓ Deserialization works")
```

**Success criteria**: Deserializes all content types correctly, validates schema

---

### Step 2.2: Validation

**Objective**: Implement pre-flight and per-item validation

**Files to create**:
- `src/lookervault/restoration/validation.py`
- `tests/unit/test_validation.py`

**Tasks**:
1. Implement `RestorationValidator.validate_pre_flight()`
2. Implement `RestorationValidator.validate_content()`
3. Implement `RestorationValidator.validate_dependencies()`
4. Write unit tests

**Testing**:
```python
from lookervault.restoration.validation import RestorationValidator
from lookervault.looker.client import LookerClient
from pathlib import Path

client = LookerClient(/* test credentials */)
validator = RestorationValidator()

# Test pre-flight validation
errors = validator.validate_pre_flight(Path("test_restore.db"), client)
if errors:
    print(f"Pre-flight errors: {errors}")
else:
    print("✓ Pre-flight validation passed")

# Test content validation
content = {"title": "Dashboard", "folder_id": "5"}
errors = validator.validate_content(content, ContentType.DASHBOARD)
assert len(errors) == 0

print("✓ Validation works")
```

**Success criteria**: Validation catches schema errors, missing dependencies

---

## Phase 3: Core Restoration Logic (P1 - MVP)

### Step 3.1: Single Item Restorer

**Objective**: Implement single-item restoration (P1 foundation)

**Files to create**:
- `src/lookervault/restoration/restorer.py`
- `tests/unit/test_restorer.py`

**Tasks**:
1. Implement `LookerContentRestorer.restore_single()`
2. Implement `check_exists()` method
3. Implement `_call_api_update()` and `_call_api_create()` with retry logic
4. Add error handling for 404, 422, 429
5. Write unit tests with mocked API calls

**Testing**:
```python
from lookervault.restoration.restorer import LookerContentRestorer
from lookervault.looker.client import LookerClient
from lookervault.storage.repository import SQLiteContentRepository
from lookervault.storage.models import ContentType

client = LookerClient(/* test credentials */)
repo = SQLiteContentRepository('test_restore.db')
restorer = LookerContentRestorer(client, repo)

# Test single dashboard restore (dry run)
result = restorer.restore_single("42", ContentType.DASHBOARD, dry_run=True)
print(f"Dry run result: {result.status}")
assert result.status in ["success", "failed", "skipped"]

# Test actual restore (if you have a test dashboard)
result = restorer.restore_single("42", ContentType.DASHBOARD, dry_run=False)
print(f"Restoration result: {result}")

print("✓ Single-item restoration works")
```

**Success criteria**: Can restore/update single dashboard successfully

---

### Step 3.2: CLI Command - Single Restore

**Objective**: Add `lookervault restore single` command

**Files to create**:
- `src/lookervault/cli/commands/restore.py`

**Files to modify**:
- `src/lookervault/cli/main.py` (register restore command)

**Tasks**:
1. Implement `restore_single()` CLI command with typer
2. Add rich output formatting
3. Add `--dry-run`, `--json`, `--force` flags
4. Wire up to `LookerContentRestorer`

**Testing**:
```bash
# Test dry run
lookervault restore single dashboard 42 --dry-run

# Test actual restore
lookervault restore single dashboard 42

# Test JSON output
lookervault restore single dashboard 42 --json

# Expected output:
# ✓ Found in backup: "Sales Dashboard"
# ✓ Checking destination...
#   → Dashboard exists (ID: 42)
#   → Will UPDATE existing dashboard
# ✓ Restoration successful!
```

**Success criteria**: CLI command works end-to-end, formats output nicely

---

### Step 3.3: Integration Test - P1 Complete

**Objective**: Test P1 user story (single-item restoration)

**Files to create**:
- `tests/integration/test_single_restore.py`

**Tasks**:
1. Set up test Looker instance (or use mocks)
2. Create test dashboard in SQLite
3. Run `restore single` command
4. Verify dashboard updated in Looker
5. Verify no data loss or corruption

**Testing**:
```bash
# Run P1 integration test
pytest tests/integration/test_single_restore.py -v

# Expected:
# test_single_dashboard_restore ... PASSED
# test_single_look_restore ... PASSED
# test_single_restore_creates_if_not_exists ... PASSED
# test_single_restore_dry_run ... PASSED
```

**Success criteria**: All P1 acceptance scenarios pass

---

## Phase 4: Dependency Ordering & Bulk Restore (P2)

### Step 4.1: Dependency Graph

**Objective**: Implement dependency ordering

**Files to create**:
- `src/lookervault/restoration/dependency_graph.py`
- `tests/unit/test_dependency_graph.py`

**Tasks**:
1. Implement `DependencyGraph.get_restoration_order()`
2. Add hardcoded dependency relationships
3. Add cycle detection validation
4. Write unit tests

**Testing**:
```python
from lookervault.restoration.dependency_graph import DependencyGraph
from lookervault.storage.models import ContentType

graph = DependencyGraph()

# Test full restoration order
order = graph.get_restoration_order()
assert order[0] == ContentType.USER  # Users first
assert order[-1] == ContentType.SCHEDULED_PLAN  # Scheduled plans last

# Test subset ordering
order = graph.get_restoration_order([ContentType.DASHBOARD, ContentType.FOLDER])
assert order[0] == ContentType.FOLDER  # Folders before dashboards

# Test no cycles
assert graph.validate_no_cycles() == True

print("✓ Dependency ordering works")
```

**Success criteria**: Dependency order correct, no cycles detected

---

### Step 4.2: Bulk Restorer (Sequential)

**Objective**: Restore all items of a type sequentially

**Files to modify**:
- `src/lookervault/restoration/restorer.py`

**Tasks**:
1. Implement `LookerContentRestorer.restore_bulk()` method
2. Query all content IDs from SQLite
3. Loop through IDs, call `restore_single()` for each
4. Aggregate results into `RestorationSummary`
5. Add progress tracking

**Testing**:
```python
from lookervault.restoration.restorer import LookerContentRestorer
from lookervault.config.models import RestorationConfig

config = RestorationConfig(workers=1, dry_run=True)  # Sequential
summary = restorer.restore_bulk(ContentType.FOLDER, config)

print(f"Total: {summary.total_items}")
print(f"Success: {summary.success_count}")
print(f"Errors: {summary.error_count}")
assert summary.total_items > 0

print("✓ Sequential bulk restoration works")
```

**Success criteria**: Restores all folders sequentially with progress tracking

---

### Step 4.3: CLI Command - Bulk Restore

**Objective**: Add `lookervault restore bulk` command

**Files to modify**:
- `src/lookervault/cli/commands/restore.py`

**Tasks**:
1. Implement `restore_bulk()` CLI command
2. Add worker count, rate limit flags
3. Add rich progress bar
4. Wire up to dependency graph

**Testing**:
```bash
# Test bulk folder restore
lookervault restore bulk folder --workers 1

# Expected output:
# Restoring all folders...
# ✓ Found 200 folders in backup
# Progress: ████████████████████ 100% (200/200)
#   Success: 200 • Errors: 0 • Throughput: 25 items/sec
# ✓ Restoration complete!
```

**Success criteria**: Bulk restore works with progress bar

---

### Step 4.4: CLI Command - All Types Restore

**Objective**: Add `lookervault restore all` command

**Files to modify**:
- `src/lookervault/cli/commands/restore.py`

**Tasks**:
1. Implement `restore_all()` CLI command
2. Use dependency graph to order types
3. Call `restore_bulk()` for each type sequentially
4. Aggregate results across types

**Testing**:
```bash
# Test full restoration (sequential)
lookervault restore all --workers 1 --dry-run

# Expected output:
# Restoring all content types in dependency order...
# [1/9] Users...
#   ✓ 150 users restored
# [2/9] Groups...
#   ✓ 45 groups restored
# ...
# ✓ Full restoration complete!
```

**Success criteria**: All types restored in dependency order

---

## Phase 5: Parallel Restoration (P2 Performance)

### Step 5.1: Parallel Orchestrator

**Objective**: Parallelize restoration with worker threads

**Files to create**:
- `src/lookervault/restoration/parallel_orchestrator.py`
- `tests/unit/test_parallel_orchestrator.py`

**Tasks**:
1. Implement `ParallelRestorationOrchestrator.restore()` method
2. Create worker thread pool (`ThreadPoolExecutor`)
3. Distribute content IDs to workers via queue
4. Workers call `restorer.restore_single()` concurrently
5. Aggregate results thread-safely
6. Reuse existing `AdaptiveRateLimiter` and `ThreadSafeMetrics`

**Testing**:
```python
from lookervault.restoration.parallel_orchestrator import ParallelRestorationOrchestrator
from lookervault.config.models import RestorationConfig

config = RestorationConfig(workers=8)
orchestrator = ParallelRestorationOrchestrator(
    restorer=restorer,
    repository=repo,
    config=config,
    rate_limiter=rate_limiter,
    metrics=metrics,
    dlq=dlq
)

summary = orchestrator.restore(ContentType.DASHBOARD, session_id="test-session")
print(f"Throughput: {summary.average_throughput:.1f} items/sec")
assert summary.average_throughput > 50  # Should be faster than sequential

print("✓ Parallel restoration works")
```

**Success criteria**: Achieves >50 items/sec with 8 workers

---

### Step 5.2: Integration Test - Parallel Performance

**Objective**: Verify parallel throughput meets targets

**Files to create**:
- `tests/integration/test_parallel_restore.py`

**Tasks**:
1. Create 1000 test dashboards in SQLite
2. Run parallel restore with 8 workers
3. Verify throughput >100 items/sec (target: SC-002)
4. Verify no race conditions or data corruption

**Testing**:
```bash
pytest tests/integration/test_parallel_restore.py -v

# Expected:
# test_parallel_restoration_throughput ... PASSED (10.2s)
#   Restored 1000 dashboards in 8.5s (117.6 items/sec)
```

**Success criteria**: Parallel restore meets throughput targets (SC-002)

---

## Phase 6: Error Handling & Checkpointing (P2 Reliability)

### Step 6.1: Dead Letter Queue

**Objective**: Capture failed items gracefully

**Files to create**:
- `src/lookervault/restoration/dead_letter_queue.py`
- `tests/unit/test_dead_letter_queue.py`

**Tasks**:
1. Implement `DeadLetterQueue.add()` method
2. Implement `DeadLetterQueue.list()` method
3. Implement `DeadLetterQueue.retry()` method
4. Wire into `ParallelOrchestrator` error handling

**Testing**:
```python
from lookervault.restoration.dead_letter_queue import DeadLetterQueue

dlq = DeadLetterQueue(repo)

# Simulate failed restoration
dlq.add(
    session_id="test",
    content_id="42",
    content_type=ContentType.DASHBOARD,
    content_data=b"test",
    error=ValueError("Test error"),
    retry_count=5
)

# List DLQ entries
entries = dlq.list()
assert len(entries) == 1
assert entries[0].error_type == "ValueError"

print("✓ DLQ works")
```

**Success criteria**: Failed items captured with full error context

---

### Step 6.2: Checkpointing & Resume

**Objective**: Enable resume after interruptions

**Files to modify**:
- `src/lookervault/restoration/parallel_orchestrator.py`

**Tasks**:
1. Save checkpoints every 100 items (configurable)
2. Implement `ParallelOrchestrator.resume()` method
3. Load checkpoint, filter out completed IDs, continue restoration
4. Test interruption and resume

**Testing**:
```python
# Start restoration
orchestrator.restore(ContentType.DASHBOARD, "session-1")

# Simulate interruption after 500/1000 items
# (manually stop or inject exception)

# Resume restoration
summary = orchestrator.resume("session-1")
assert summary.total_items == 1000
assert summary.success_count >= 500  # Resumed from checkpoint

print("✓ Checkpoint and resume works")
```

**Success criteria**: Resume skips completed items, continues from checkpoint

---

### Step 6.3: CLI Command - Resume & DLQ

**Objective**: Add `restore resume` and `restore dlq` commands

**Files to modify**:
- `src/lookervault/cli/commands/restore.py`

**Tasks**:
1. Implement `restore_resume()` CLI command
2. Implement `restore_dlq_list()`, `restore_dlq_show()`, `restore_dlq_retry()` CLI commands
3. Add rich formatting for DLQ output

**Testing**:
```bash
# Test resume
lookervault restore all --workers 8
# <interrupt with Ctrl+C after 50%>
lookervault restore resume

# Test DLQ management
lookervault restore dlq list
lookervault restore dlq show 1
lookervault restore dlq retry 1

# Expected: Resume continues from checkpoint, DLQ shows failed items
```

**Success criteria**: Resume and DLQ commands work end-to-end

---

## Phase 7: ID Mapping (P3 - Cross-Instance Migration)

### Step 7.1: ID Mapper

**Objective**: Map source IDs to destination IDs

**Files to create**:
- `src/lookervault/restoration/id_mapper.py`
- `tests/unit/test_id_mapper.py`

**Tasks**:
1. Implement `IDMapper.save_mapping()` method
2. Implement `IDMapper.get_destination_id()` method
3. Implement `IDMapper.translate_references()` method
4. Wire into restorer for cross-instance scenarios

**Testing**:
```python
from lookervault.restoration.id_mapper import IDMapper

mapper = IDMapper(
    repository=repo,
    source_instance="https://source.test",
    destination_instance="https://dest.test"
)

# Save mapping
mapper.save_mapping(ContentType.FOLDER, "123", "456")

# Retrieve mapping
dest_id = mapper.get_destination_id(ContentType.FOLDER, "123")
assert dest_id == "456"

# Translate references
content = {"folder_id": "123", "title": "Dashboard"}
translated = mapper.translate_references(content, ContentType.DASHBOARD)
assert translated["folder_id"] == "456"

print("✓ ID mapper works")
```

**Success criteria**: ID mapping and reference translation works

---

### Step 7.2: Integration Test - Cross-Instance Migration

**Objective**: Test P3 user story (cross-instance restore)

**Files to create**:
- `tests/integration/test_id_mapping.py`

**Tasks**:
1. Set up two test Looker instances (or use mocks)
2. Extract content from Instance A to SQLite
3. Restore content to Instance B
4. Verify ID mappings created
5. Verify FK references translated correctly

**Testing**:
```bash
pytest tests/integration/test_id_mapping.py -v

# Expected:
# test_cross_instance_dashboard_restore ... PASSED
# test_id_mapping_persistence ... PASSED
# test_reference_translation ... PASSED
```

**Success criteria**: Cross-instance migration works with ID translation

---

## Phase 8: Production Testing & Hardening

### Step 8.1: Integration Tests - All User Stories

**Objective**: Verify all P1-P3 acceptance scenarios pass

**Tasks**:
1. Run all integration tests
2. Verify SC-001 through SC-008 (success criteria)
3. Test with production-like data volumes (10K+ items)

**Testing**:
```bash
# Run full integration test suite
pytest tests/integration/ -v

# Verify all acceptance scenarios:
# P1: test_single_dashboard_restore, test_single_create_if_not_exists
# P2: test_bulk_dependency_ordering, test_parallel_throughput, test_resume_interrupted
# P3: test_cross_instance_migration, test_id_mapping
```

**Success criteria**: All integration tests pass

---

### Step 8.2: Performance Benchmarking

**Objective**: Verify performance targets met

**Tasks**:
1. Test with 50,000 items (SC-008)
2. Verify throughput >100 items/sec (SC-002)
3. Verify single-item restore <10 seconds (SC-001)
4. Measure memory usage with 16 workers

**Testing**:
```bash
# Benchmark single-item restore
time lookervault restore single dashboard 42
# Target: <10 seconds

# Benchmark bulk restore (50K items)
time lookervault restore all --workers 8
# Target: <10 minutes (83+ items/sec)

# Check memory usage
/usr/bin/time -v lookervault restore all --workers 16
# Verify memory scales linearly with workers
```

**Success criteria**: All performance targets met

---

### Step 8.3: Production Safety Checklist

**Objective**: Ensure production readiness

**Checklist**:
- [ ] All integration tests pass
- [ ] Performance benchmarks meet targets
- [ ] DLQ captures 100% of failures (SC-007)
- [ ] Resume capability tested with interruptions (SC-005)
- [ ] Rate limiting coordinates across workers (SC-003)
- [ ] No SQLite write contention with ≤16 workers
- [ ] Dry-run mode works for all commands
- [ ] JSON output format stable for automation
- [ ] Documentation complete (README, API docs)
- [ ] Error messages clear and actionable

**Success criteria**: All checklist items ✓

---

## Summary

This quickstart provides a step-by-step path to implementing the Looker content restoration feature:

1. **Phase 1**: Database schema and data models
2. **Phase 2**: Deserialization and validation
3. **Phase 3**: Single-item restoration (P1 MVP)
4. **Phase 4**: Dependency ordering and bulk restore
5. **Phase 5**: Parallel restoration for performance (P2)
6. **Phase 6**: Error handling and checkpointing (P2)
7. **Phase 7**: ID mapping for cross-instance migration (P3)
8. **Phase 8**: Production testing and hardening

Each phase builds on the previous, with clear testing milestones to ensure correctness before moving forward.

**Estimated Timeline**:
- Phase 1: 1 day
- Phase 2: 1 day
- Phase 3: 2 days (P1 MVP complete)
- Phase 4: 2 days
- Phase 5: 2 days
- Phase 6: 2 days (P2 complete)
- Phase 7: 2 days (P3 complete)
- Phase 8: 1 day

**Total**: ~2 weeks for full implementation and testing
