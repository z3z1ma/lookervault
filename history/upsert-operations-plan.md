# Implementation Plan: Make All SQLite Operations Idempotent (Upsert)

**Issue ID**: lookervault-yos
**Priority**: 0 (Critical)
**Type**: Bug
**Created**: 2025-12-14

## Executive Summary

This plan addresses a critical issue where multiple extraction runs create duplicate/conflicting database records instead of updating existing ones. The solution is to convert all SQLite write operations from plain INSERT to INSERT ... ON CONFLICT DO UPDATE (upsert pattern).

**Impact**: Enables the core workflow of pull → partial extract → upload without data corruption or primary key violations.

---

## Problem Statement

### Current Behavior
Running `lookervault extract` multiple times with the same content creates duplicate or conflicting database entries:
- Checkpoint records duplicate on re-run
- Session creation fails with primary key violation
- DLQ items can be duplicated if retry logic re-saves failures
- Cannot safely update existing snapshots with partial extracts

### Expected Behavior
All write operations should be **idempotent**:
- Running operation twice with same data = same final state
- No errors on re-run
- Updates existing records instead of creating duplicates
- Safe for workflow: pull snapshot → run partial extract → upload updated snapshot

### Root Cause
5 out of 7 write methods use plain `INSERT` instead of `INSERT ... ON CONFLICT DO UPDATE`:
1. `save_checkpoint()` - Line 625
2. `create_session()` - Line 771
3. `save_dead_letter_item()` - Line 1182
4. `save_restoration_checkpoint()` - Line 1636
5. `create_restoration_session()` - Line 1790

---

## Current State Analysis

### Already Idempotent (✅)

#### 1. save_content() - Lines 374-408
```sql
INSERT INTO content_items (...)
VALUES (?, ?, ...)
ON CONFLICT(id) DO UPDATE SET
    content_type = excluded.content_type,
    name = excluded.name,
    -- ... all fields updated
```
**PK**: `id` (content_items.id PRIMARY KEY)
**Status**: ✅ Fully idempotent

#### 2. save_id_mapping() - Lines 1432-1441
```sql
INSERT INTO id_mappings (...)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(source_instance, content_type, source_id) DO UPDATE SET
    destination_id = excluded.destination_id,
    created_at = excluded.created_at,
    session_id = excluded.session_id
```
**PK**: `(source_instance, content_type, source_id)` (composite)
**Status**: ✅ Fully idempotent

---

### Needs Upsert (❌)

#### 3. save_checkpoint() - Lines 625-630
**Current Code**:
```sql
INSERT INTO sync_checkpoints (
    session_id, content_type, checkpoint_data, started_at,
    completed_at, item_count, error_message
) VALUES (?, ?, ?, ?, ?, ?, ?)
```

**Schema** (schema.py:98-109):
```sql
CREATE TABLE IF NOT EXISTS sync_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- PK
    session_id TEXT,
    content_type INTEGER NOT NULL,
    checkpoint_data TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT DEFAULT NULL,
    item_count INTEGER DEFAULT 0,
    error_message TEXT DEFAULT NULL
)
```

**Problem**:
- PK is `id INTEGER PRIMARY KEY AUTOINCREMENT` (surrogate key)
- No natural unique constraint on `(session_id, content_type)` combo
- Re-running creates new checkpoint with different `id`, duplicating data

**Solution**: Add ON CONFLICT handler for `id` field, but we need a **natural unique constraint** first. The natural key should be `(session_id, content_type, started_at)` since:
- Multiple checkpoints can exist per session (different content types)
- Multiple checkpoints can exist per content type (different sessions)
- But only ONE checkpoint should exist per (session, content_type) at a given start time

**Implementation**:
1. Add unique constraint: `UNIQUE(session_id, content_type, started_at)` (via migration)
2. Convert to upsert:
```sql
INSERT INTO sync_checkpoints (...)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(session_id, content_type, started_at) DO UPDATE SET
    checkpoint_data = excluded.checkpoint_data,
    completed_at = excluded.completed_at,
    item_count = excluded.item_count,
    error_message = excluded.error_message
```

**Alternative**: If we want to allow updating by `id` (for update_checkpoint logic), keep surrogate key and add UNIQUE constraint separately:
```sql
-- Schema change
ALTER TABLE sync_checkpoints ADD CONSTRAINT unique_checkpoint
    UNIQUE(session_id, content_type, started_at);

-- Then use ON CONFLICT on the unique constraint
ON CONFLICT(session_id, content_type, started_at) DO UPDATE SET ...
```

#### 4. create_session() - Lines 771-787
**Current Code**:
```sql
INSERT INTO extraction_sessions (
    id, started_at, completed_at, status,
    total_items, error_count, config, metadata
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
```

**Schema** (schema.py:122-133):
```sql
CREATE TABLE IF NOT EXISTS extraction_sessions (
    id TEXT PRIMARY KEY NOT NULL,  -- PK (UUID)
    started_at TEXT NOT NULL,
    completed_at TEXT DEFAULT NULL,
    status TEXT NOT NULL,
    total_items INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    config TEXT,
    metadata TEXT
)
```

**Problem**:
- PK is `id TEXT PRIMARY KEY` (UUID generated by caller)
- Re-running with same session `id` causes: `UNIQUE constraint failed: extraction_sessions.id`

**Solution**:
Simple upsert on `id`:
```sql
INSERT INTO extraction_sessions (...)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(id) DO UPDATE SET
    completed_at = excluded.completed_at,
    status = excluded.status,
    total_items = excluded.total_items,
    error_count = excluded.error_count,
    config = excluded.config,
    metadata = excluded.metadata
```

**Note**: `started_at` should NOT be updated (preserve original start time).

#### 5. save_dead_letter_item() - Lines 1182-1201
**Current Code**:
```sql
INSERT INTO dead_letter_queue (
    session_id, content_id, content_type, content_data,
    error_message, error_type, stack_trace, retry_count,
    failed_at, metadata
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

**Schema** (schema.py:222-237):
```sql
CREATE TABLE IF NOT EXISTS dead_letter_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- PK (surrogate)
    session_id TEXT NOT NULL,
    content_id TEXT NOT NULL,
    content_type INTEGER NOT NULL,
    content_data BLOB NOT NULL,
    error_message TEXT NOT NULL,
    error_type TEXT NOT NULL,
    stack_trace TEXT,
    retry_count INTEGER NOT NULL,
    failed_at TEXT NOT NULL,
    metadata TEXT,
    FOREIGN KEY (session_id) REFERENCES restoration_sessions(id) ON DELETE CASCADE
)
```

**Problem**:
- PK is `id INTEGER PRIMARY KEY AUTOINCREMENT` (surrogate key)
- No unique constraint on `(session_id, content_id, content_type)` combo
- Same content item can fail multiple times in same session (e.g., transient errors)
- Re-saving creates duplicate DLQ entries

**Design Decision**:
Should we allow multiple DLQ entries for same content in same session? **YES**, because:
- Content might fail multiple times with different errors
- We want to track retry history
- DLQ is append-only for audit trail

**Solution**:
For DLQ, we actually want to track failure history, so plain INSERT might be correct. However, if retry logic tries to re-save the SAME failure (same retry_count), we should deduplicate.

**Natural Key**: `(session_id, content_id, content_type, retry_count, failed_at)`
- Same content can fail multiple times (different retry_count)
- But same retry_count + failed_at = duplicate (should upsert)

**Implementation**:
1. Add unique constraint: `UNIQUE(session_id, content_id, content_type, retry_count)` (via migration)
   - Note: We drop `failed_at` from unique key because retry logic might re-save same retry_count
2. Convert to upsert:
```sql
INSERT INTO dead_letter_queue (...)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(session_id, content_id, content_type, retry_count) DO UPDATE SET
    error_message = excluded.error_message,
    error_type = excluded.error_type,
    stack_trace = excluded.stack_trace,
    failed_at = excluded.failed_at,
    metadata = excluded.metadata,
    content_data = excluded.content_data
```

**Alternative**: Keep DLQ as append-only, but add logic to check for existing DLQ entry before insert:
```python
existing = self.get_dead_letter_item_by_content(session_id, content_id, retry_count)
if existing:
    # Update existing instead of insert
    self.update_dead_letter_item(existing.id, item)
else:
    # Insert new
    self._insert_dead_letter_item(item)
```

**Recommendation**: Use unique constraint + ON CONFLICT for simplicity and atomicity.

#### 6. save_restoration_checkpoint() - Lines 1636-1654
**Current Code**:
```sql
INSERT INTO restoration_checkpoints (
    session_id, content_type, checkpoint_data, started_at,
    completed_at, item_count, error_count
) VALUES (?, ?, ?, ?, ?, ?, ?)
```

**Schema** (schema.py:173-185):
```sql
CREATE TABLE IF NOT EXISTS restoration_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- PK (surrogate)
    session_id TEXT NOT NULL,
    content_type INTEGER NOT NULL,
    checkpoint_data TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    item_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES restoration_sessions(id) ON DELETE CASCADE
)
```

**Problem**: Same as sync_checkpoints (surrogate key, no natural unique constraint)

**Solution**: Same as sync_checkpoints
1. Add unique constraint: `UNIQUE(session_id, content_type, started_at)` (via migration)
2. Convert to upsert:
```sql
INSERT INTO restoration_checkpoints (...)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(session_id, content_type, started_at) DO UPDATE SET
    checkpoint_data = excluded.checkpoint_data,
    completed_at = excluded.completed_at,
    item_count = excluded.item_count,
    error_count = excluded.error_count
```

#### 7. create_restoration_session() - Lines 1790-1812
**Current Code**:
```sql
INSERT INTO restoration_sessions (
    id, started_at, completed_at, status,
    total_items, success_count, error_count,
    source_instance, destination_instance,
    config, metadata
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

**Schema** (schema.py:146-160):
```sql
CREATE TABLE IF NOT EXISTS restoration_sessions (
    id TEXT PRIMARY KEY,  -- PK (UUID)
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    total_items INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    source_instance TEXT,
    destination_instance TEXT NOT NULL,
    config TEXT,
    metadata TEXT
)
```

**Problem**: Same as extraction_sessions (UUID PK, re-run causes constraint violation)

**Solution**: Same as extraction_sessions
```sql
INSERT INTO restoration_sessions (...)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(id) DO UPDATE SET
    completed_at = excluded.completed_at,
    status = excluded.status,
    total_items = excluded.total_items,
    success_count = excluded.success_count,
    error_count = excluded.error_count,
    source_instance = excluded.source_instance,
    destination_instance = excluded.destination_instance,
    config = excluded.config,
    metadata = excluded.metadata
```

**Note**: `started_at` should NOT be updated (preserve original start time).

---

## Implementation Plan

### Phase 1: Schema Migrations (Add Unique Constraints)

**File**: `src/lookervault/storage/schema.py`

#### Migration to Version 3

Add unique constraints to checkpoint and DLQ tables:

```python
def _migrate_to_version_3(conn: sqlite3.Connection) -> None:
    """Migrate existing databases from version 2 to version 3.

    Adds unique constraints to enable idempotent upsert operations:
    1. sync_checkpoints: UNIQUE(session_id, content_type, started_at)
    2. restoration_checkpoints: UNIQUE(session_id, content_type, started_at)
    3. dead_letter_queue: UNIQUE(session_id, content_id, content_type, retry_count)

    Args:
        conn: SQLite connection
    """
    cursor = conn.cursor()

    # Check current schema version
    cursor.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
    current_version = cursor.fetchone()
    current_version = current_version[0] if current_version else 0

    if current_version >= 3:
        return  # Already migrated

    # SQLite doesn't support ALTER TABLE ADD CONSTRAINT directly
    # We need to recreate tables with new constraints

    # 1. Migrate sync_checkpoints
    cursor.execute("""
        CREATE TABLE sync_checkpoints_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            content_type INTEGER NOT NULL,
            checkpoint_data TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT DEFAULT NULL,
            item_count INTEGER DEFAULT 0,
            error_message TEXT DEFAULT NULL,
            UNIQUE(session_id, content_type, started_at)
        )
    """)

    cursor.execute("""
        INSERT INTO sync_checkpoints_new
        SELECT * FROM sync_checkpoints
    """)

    cursor.execute("DROP TABLE sync_checkpoints")
    cursor.execute("ALTER TABLE sync_checkpoints_new RENAME TO sync_checkpoints")

    # Recreate indexes
    cursor.execute("""
        CREATE INDEX idx_checkpoint_type_completed
        ON sync_checkpoints(content_type, completed_at)
    """)
    cursor.execute("""
        CREATE INDEX idx_checkpoint_session
        ON sync_checkpoints(session_id)
    """)

    # 2. Migrate restoration_checkpoints
    cursor.execute("""
        CREATE TABLE restoration_checkpoints_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            content_type INTEGER NOT NULL,
            checkpoint_data TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            item_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            UNIQUE(session_id, content_type, started_at),
            FOREIGN KEY (session_id) REFERENCES restoration_sessions(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        INSERT INTO restoration_checkpoints_new
        SELECT * FROM restoration_checkpoints
    """)

    cursor.execute("DROP TABLE restoration_checkpoints")
    cursor.execute("ALTER TABLE restoration_checkpoints_new RENAME TO restoration_checkpoints")

    # Recreate indexes
    cursor.execute("""
        CREATE INDEX idx_restoration_checkpoint_session
        ON restoration_checkpoints(session_id)
    """)
    cursor.execute("""
        CREATE INDEX idx_restoration_checkpoint_type
        ON restoration_checkpoints(content_type)
    """)

    # 3. Migrate dead_letter_queue
    cursor.execute("""
        CREATE TABLE dead_letter_queue_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            content_id TEXT NOT NULL,
            content_type INTEGER NOT NULL,
            content_data BLOB NOT NULL,
            error_message TEXT NOT NULL,
            error_type TEXT NOT NULL,
            stack_trace TEXT,
            retry_count INTEGER NOT NULL,
            failed_at TEXT NOT NULL,
            metadata TEXT,
            UNIQUE(session_id, content_id, content_type, retry_count),
            FOREIGN KEY (session_id) REFERENCES restoration_sessions(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        INSERT INTO dead_letter_queue_new
        SELECT * FROM dead_letter_queue
    """)

    cursor.execute("DROP TABLE dead_letter_queue")
    cursor.execute("ALTER TABLE dead_letter_queue_new RENAME TO dead_letter_queue")

    # Recreate indexes
    cursor.execute("""
        CREATE INDEX idx_dlq_session
        ON dead_letter_queue(session_id)
    """)
    cursor.execute("""
        CREATE INDEX idx_dlq_content
        ON dead_letter_queue(content_type, content_id)
    """)
    cursor.execute("""
        CREATE INDEX idx_dlq_failed_at
        ON dead_letter_queue(failed_at DESC)
    """)

    # Record migration
    cursor.execute(
        """
        INSERT INTO schema_version (version, applied_at, description)
        VALUES (?, ?, ?)
        """,
        (
            3,
            datetime.now().isoformat(),
            "Added unique constraints for idempotent upsert operations",
        ),
    )

    conn.commit()
```

**Update create_schema()** to call migration:
```python
def create_schema(conn: sqlite3.Connection) -> None:
    # ... existing table creation ...

    # Run migrations
    _migrate_to_version_2(conn)
    _migrate_to_version_3(conn)  # NEW

    # ... rest of schema creation ...
```

### Phase 2: Convert Write Operations to Upsert

**File**: `src/lookervault/storage/repository.py`

#### 1. save_checkpoint() - Lines 625-630

**Before**:
```python
cursor.execute(
    """
    INSERT INTO sync_checkpoints (
        session_id, content_type, checkpoint_data, started_at,
        completed_at, item_count, error_message
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
    (
        checkpoint.session_id,
        checkpoint.content_type,
        json.dumps(checkpoint.checkpoint_data),
        checkpoint.started_at.isoformat(),
        checkpoint.completed_at.isoformat()
        if checkpoint.completed_at
        else None,
        checkpoint.item_count,
        checkpoint.error_message,
    ),
)
```

**After**:
```python
cursor.execute(
    """
    INSERT INTO sync_checkpoints (
        session_id, content_type, checkpoint_data, started_at,
        completed_at, item_count, error_message
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(session_id, content_type, started_at) DO UPDATE SET
        checkpoint_data = excluded.checkpoint_data,
        completed_at = excluded.completed_at,
        item_count = excluded.item_count,
        error_message = excluded.error_message
    """,
    (
        checkpoint.session_id,
        checkpoint.content_type,
        json.dumps(checkpoint.checkpoint_data),
        checkpoint.started_at.isoformat(),
        checkpoint.completed_at.isoformat()
        if checkpoint.completed_at
        else None,
        checkpoint.item_count,
        checkpoint.error_message,
    ),
)
```

**Notes**:
- `session_id`, `content_type`, `started_at` are part of unique constraint (not updated)
- All other fields are updated on conflict
- Idempotent: running twice with same data produces same final state

#### 2. create_session() - Lines 771-787

**Before**:
```python
cursor.execute(
    """
    INSERT INTO extraction_sessions (
        id, started_at, completed_at, status,
        total_items, error_count, config, metadata
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
    (
        session.id,
        session.started_at.isoformat(),
        session.completed_at.isoformat() if session.completed_at else None,
        session.status,
        session.total_items,
        session.error_count,
        json.dumps(session.config) if session.config else None,
        json.dumps(session.metadata) if session.metadata else None,
    ),
)
```

**After**:
```python
cursor.execute(
    """
    INSERT INTO extraction_sessions (
        id, started_at, completed_at, status,
        total_items, error_count, config, metadata
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        completed_at = excluded.completed_at,
        status = excluded.status,
        total_items = excluded.total_items,
        error_count = excluded.error_count,
        config = excluded.config,
        metadata = excluded.metadata
    """,
    (
        session.id,
        session.started_at.isoformat(),
        session.completed_at.isoformat() if session.completed_at else None,
        session.status,
        session.total_items,
        session.error_count,
        json.dumps(session.config) if session.config else None,
        json.dumps(session.metadata) if session.metadata else None,
    ),
)
```

**Notes**:
- `id` is PK (not updated)
- `started_at` is NOT updated (preserve original session start time)
- All other fields are updated on conflict
- Rename method from `create_session()` to `save_session()` for clarity (or keep name for backward compat)

#### 3. save_dead_letter_item() - Lines 1182-1201

**Before**:
```python
cursor.execute(
    """
    INSERT INTO dead_letter_queue (
        session_id, content_id, content_type, content_data,
        error_message, error_type, stack_trace, retry_count,
        failed_at, metadata
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    (
        item.session_id,
        item.content_id,
        item.content_type,
        item.content_data,
        item.error_message,
        item.error_type,
        item.stack_trace,
        item.retry_count,
        item.failed_at.isoformat(),
        json.dumps(item.metadata) if item.metadata else None,
    ),
)
```

**After**:
```python
cursor.execute(
    """
    INSERT INTO dead_letter_queue (
        session_id, content_id, content_type, content_data,
        error_message, error_type, stack_trace, retry_count,
        failed_at, metadata
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(session_id, content_id, content_type, retry_count) DO UPDATE SET
        error_message = excluded.error_message,
        error_type = excluded.error_type,
        stack_trace = excluded.stack_trace,
        failed_at = excluded.failed_at,
        metadata = excluded.metadata,
        content_data = excluded.content_data
    """,
    (
        item.session_id,
        item.content_id,
        item.content_type,
        item.content_data,
        item.error_message,
        item.error_type,
        item.stack_trace,
        item.retry_count,
        item.failed_at.isoformat(),
        json.dumps(item.metadata) if item.metadata else None,
    ),
)
```

**Notes**:
- `session_id`, `content_id`, `content_type`, `retry_count` are part of unique constraint (not updated)
- All other fields are updated on conflict
- Allows same content to fail multiple times (different retry_count)
- But same retry_count = deduplication (upsert)

#### 4. save_restoration_checkpoint() - Lines 1636-1654

**Before**:
```python
cursor.execute(
    """
    INSERT INTO restoration_checkpoints (
        session_id, content_type, checkpoint_data, started_at,
        completed_at, item_count, error_count
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
    (
        checkpoint.session_id,
        checkpoint.content_type,
        json.dumps(checkpoint.checkpoint_data),
        checkpoint.started_at.isoformat(),
        checkpoint.completed_at.isoformat()
        if checkpoint.completed_at
        else None,
        checkpoint.item_count,
        checkpoint.error_count,
    ),
)
```

**After**:
```python
cursor.execute(
    """
    INSERT INTO restoration_checkpoints (
        session_id, content_type, checkpoint_data, started_at,
        completed_at, item_count, error_count
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(session_id, content_type, started_at) DO UPDATE SET
        checkpoint_data = excluded.checkpoint_data,
        completed_at = excluded.completed_at,
        item_count = excluded.item_count,
        error_count = excluded.error_count
    """,
    (
        checkpoint.session_id,
        checkpoint.content_type,
        json.dumps(checkpoint.checkpoint_data),
        checkpoint.started_at.isoformat(),
        checkpoint.completed_at.isoformat()
        if checkpoint.completed_at
        else None,
        checkpoint.item_count,
        checkpoint.error_count,
    ),
)
```

**Notes**: Same pattern as sync_checkpoints

#### 5. create_restoration_session() - Lines 1790-1812

**Before**:
```python
cursor.execute(
    """
    INSERT INTO restoration_sessions (
        id, started_at, completed_at, status,
        total_items, success_count, error_count,
        source_instance, destination_instance,
        config, metadata
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    (
        session.id,
        session.started_at.isoformat(),
        session.completed_at.isoformat() if session.completed_at else None,
        session.status,
        session.total_items,
        session.success_count,
        session.error_count,
        session.source_instance,
        session.destination_instance,
        json.dumps(session.config) if session.config else None,
        json.dumps(session.metadata) if session.metadata else None,
    ),
)
```

**After**:
```python
cursor.execute(
    """
    INSERT INTO restoration_sessions (
        id, started_at, completed_at, status,
        total_items, success_count, error_count,
        source_instance, destination_instance,
        config, metadata
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        completed_at = excluded.completed_at,
        status = excluded.status,
        total_items = excluded.total_items,
        success_count = excluded.success_count,
        error_count = excluded.error_count,
        source_instance = excluded.source_instance,
        destination_instance = excluded.destination_instance,
        config = excluded.config,
        metadata = excluded.metadata
    """,
    (
        session.id,
        session.started_at.isoformat(),
        session.completed_at.isoformat() if session.completed_at else None,
        session.status,
        session.total_items,
        session.success_count,
        session.error_count,
        session.source_instance,
        session.destination_instance,
        json.dumps(session.config) if session.config else None,
        json.dumps(session.metadata) if session.metadata else None,
    ),
)
```

**Notes**: Same pattern as extraction_sessions

### Phase 3: Update SCHEMA_VERSION Constant

**File**: `src/lookervault/storage/schema.py`

```python
SCHEMA_VERSION = 3  # Updated from 2
```

### Phase 4: Update Docstrings

Update method docstrings to reflect upsert behavior:

```python
def save_checkpoint(self, checkpoint: Checkpoint) -> int:
    """Save or update extraction checkpoint with thread-safe transaction control.

    Uses INSERT ... ON CONFLICT DO UPDATE for idempotent upsert behavior.
    If checkpoint with same (session_id, content_type, started_at) exists,
    updates it instead of creating duplicate.

    Includes retry logic for SQLITE_BUSY errors that can occur in parallel execution.

    Args:
        checkpoint: Checkpoint object

    Returns:
        Checkpoint ID

    Raises:
        StorageError: If save fails after retries
    """
```

Apply similar updates to:
- `create_session()` → rename to `save_session()` or update docstring
- `save_dead_letter_item()`
- `save_restoration_checkpoint()`
- `create_restoration_session()` → rename to `save_restoration_session()` or update docstring

---

## Testing Strategy

### Unit Tests

**File**: `tests/test_repository_upsert.py` (new file)

```python
"""Tests for idempotent upsert operations in SQLiteContentRepository."""

import pytest
from datetime import datetime
from lookervault.storage.repository import SQLiteContentRepository
from lookervault.storage.models import (
    Checkpoint,
    ExtractionSession,
    DeadLetterItem,
    RestorationCheckpoint,
    RestorationSession,
    ContentType,
)

@pytest.fixture
def repo(tmp_path):
    """Create temporary repository for testing."""
    db_path = tmp_path / "test.db"
    return SQLiteContentRepository(db_path)

class TestCheckpointUpsert:
    def test_save_checkpoint_twice_upserts(self, repo):
        """Saving same checkpoint twice should update, not duplicate."""
        checkpoint = Checkpoint(
            session_id="test-session",
            content_type=ContentType.DASHBOARD.value,
            checkpoint_data={"offset": 0},
            started_at=datetime.now(),
            item_count=100,
        )

        # First save
        id1 = repo.save_checkpoint(checkpoint)

        # Second save with updated data
        checkpoint.item_count = 200
        checkpoint.checkpoint_data = {"offset": 200}
        id2 = repo.save_checkpoint(checkpoint)

        # Should return same ID (update, not insert)
        assert id1 == id2

        # Verify only one checkpoint exists
        latest = repo.get_latest_checkpoint(ContentType.DASHBOARD.value, "test-session")
        assert latest.id == id1
        assert latest.item_count == 200
        assert latest.checkpoint_data == {"offset": 200}

    def test_save_checkpoint_different_content_type_creates_new(self, repo):
        """Different content types should create separate checkpoints."""
        checkpoint1 = Checkpoint(
            session_id="test-session",
            content_type=ContentType.DASHBOARD.value,
            checkpoint_data={"offset": 0},
            started_at=datetime.now(),
            item_count=100,
        )

        checkpoint2 = Checkpoint(
            session_id="test-session",
            content_type=ContentType.LOOK.value,  # Different type
            checkpoint_data={"offset": 0},
            started_at=datetime.now(),
            item_count=50,
        )

        id1 = repo.save_checkpoint(checkpoint1)
        id2 = repo.save_checkpoint(checkpoint2)

        # Should create two separate checkpoints
        assert id1 != id2

class TestSessionUpsert:
    def test_create_session_twice_upserts(self, repo):
        """Creating same session twice should update, not fail."""
        session = ExtractionSession(
            id="test-session-id",
            started_at=datetime.now(),
            status="running",
            total_items=0,
            error_count=0,
        )

        # First create
        repo.create_session(session)

        # Second create with updated data
        session.total_items = 1000
        session.status = "completed"
        repo.create_session(session)  # Should not raise

        # Verify session was updated
        loaded = repo.get_extraction_session("test-session-id")
        assert loaded.total_items == 1000
        assert loaded.status == "completed"
        assert loaded.started_at == session.started_at  # Preserved

class TestDLQUpsert:
    def test_save_dlq_same_retry_count_upserts(self, repo):
        """Saving same content+retry_count should update, not duplicate."""
        session = RestorationSession(
            id="test-restore-session",
            started_at=datetime.now(),
            status="running",
            destination_instance="https://example.looker.com",
        )
        repo.create_restoration_session(session)

        dlq_item = DeadLetterItem(
            session_id="test-restore-session",
            content_id="dashboard-123",
            content_type=ContentType.DASHBOARD.value,
            content_data=b"serialized data",
            error_message="Network timeout",
            error_type="NetworkError",
            retry_count=1,
            failed_at=datetime.now(),
        )

        # First save
        id1 = repo.save_dead_letter_item(dlq_item)

        # Second save with updated error message (same retry_count)
        dlq_item.error_message = "Network timeout (retry 1)"
        id2 = repo.save_dead_letter_item(dlq_item)

        # Should update existing (same ID)
        assert id1 == id2

        # Verify error message was updated
        loaded = repo.get_dead_letter_item(id1)
        assert loaded.error_message == "Network timeout (retry 1)"

    def test_save_dlq_different_retry_count_creates_new(self, repo):
        """Different retry_count should create separate DLQ entries."""
        session = RestorationSession(
            id="test-restore-session",
            started_at=datetime.now(),
            status="running",
            destination_instance="https://example.looker.com",
        )
        repo.create_restoration_session(session)

        dlq_item1 = DeadLetterItem(
            session_id="test-restore-session",
            content_id="dashboard-123",
            content_type=ContentType.DASHBOARD.value,
            content_data=b"serialized data",
            error_message="Network timeout",
            error_type="NetworkError",
            retry_count=1,
            failed_at=datetime.now(),
        )

        dlq_item2 = DeadLetterItem(
            session_id="test-restore-session",
            content_id="dashboard-123",
            content_type=ContentType.DASHBOARD.value,
            content_data=b"serialized data",
            error_message="Network timeout again",
            error_type="NetworkError",
            retry_count=2,  # Different retry count
            failed_at=datetime.now(),
        )

        id1 = repo.save_dead_letter_item(dlq_item1)
        id2 = repo.save_dead_letter_item(dlq_item2)

        # Should create two separate entries
        assert id1 != id2

        # Verify both exist
        items = repo.list_dead_letter_items(session_id="test-restore-session")
        assert len(items) == 2

class TestRestorationCheckpointUpsert:
    def test_save_restoration_checkpoint_twice_upserts(self, repo):
        """Saving same restoration checkpoint twice should update."""
        checkpoint = RestorationCheckpoint(
            session_id="test-restore-session",
            content_type=ContentType.DASHBOARD.value,
            checkpoint_data={"processed_ids": ["id1", "id2"]},
            started_at=datetime.now(),
            item_count=2,
            error_count=0,
        )

        # First save
        id1 = repo.save_restoration_checkpoint(checkpoint)

        # Second save with updated data
        checkpoint.item_count = 5
        checkpoint.checkpoint_data = {"processed_ids": ["id1", "id2", "id3", "id4", "id5"]}
        id2 = repo.save_restoration_checkpoint(checkpoint)

        # Should return same ID (update, not insert)
        assert id1 == id2

        # Verify checkpoint was updated
        latest = repo.get_latest_restoration_checkpoint(
            ContentType.DASHBOARD.value,
            "test-restore-session"
        )
        assert latest.id == id1
        assert latest.item_count == 5

class TestRestorationSessionUpsert:
    def test_create_restoration_session_twice_upserts(self, repo):
        """Creating same restoration session twice should update."""
        session = RestorationSession(
            id="test-restore-id",
            started_at=datetime.now(),
            status="running",
            total_items=0,
            success_count=0,
            error_count=0,
            destination_instance="https://example.looker.com",
        )

        # First create
        repo.create_restoration_session(session)

        # Second create with updated data
        session.total_items = 500
        session.success_count = 450
        session.error_count = 50
        session.status = "completed"
        repo.create_restoration_session(session)

        # Verify session was updated
        loaded = repo.get_restoration_session("test-restore-id")
        assert loaded.total_items == 500
        assert loaded.success_count == 450
        assert loaded.error_count == 50
        assert loaded.status == "completed"
        assert loaded.started_at == session.started_at  # Preserved
```

### Integration Tests

**File**: `tests/integration/test_extraction_workflow.py` (update existing)

Add test case for re-running extraction:

```python
def test_rerun_extraction_upserts_data(tmp_path, looker_client):
    """Re-running extraction should update existing data, not duplicate."""
    repo = SQLiteContentRepository(tmp_path / "test.db")
    orchestrator = ParallelExtractionOrchestrator(
        repository=repo,
        extractor=looker_client,
        config=ParallelConfig(workers=1),
    )

    # First extraction
    session_id = "test-session"
    orchestrator.extract_content_type(
        content_type=ContentType.DASHBOARD,
        session_id=session_id,
    )

    count_after_first = repo.count_content(ContentType.DASHBOARD.value)

    # Re-run extraction with SAME session ID
    orchestrator.extract_content_type(
        content_type=ContentType.DASHBOARD,
        session_id=session_id,  # Same ID
    )

    count_after_second = repo.count_content(ContentType.DASHBOARD.value)

    # Should have same count (upsert, not duplicate)
    assert count_after_first == count_after_second

    # Verify session was updated, not duplicated
    session = repo.get_extraction_session(session_id)
    assert session is not None

    # Verify only one checkpoint per content type
    checkpoints = repo.list_checkpoints(session_id=session_id)
    dashboard_checkpoints = [c for c in checkpoints if c.content_type == ContentType.DASHBOARD.value]
    assert len(dashboard_checkpoints) == 1  # Only one checkpoint
```

---

## Risk Analysis

### Low Risk ✅

1. **save_content()**: Already upsert, no changes needed
2. **save_id_mapping()**: Already upsert, no changes needed
3. **Schema migration**: SQLite supports table recreation pattern safely

### Medium Risk ⚠️

1. **Checkpoint natural key selection**: Using `(session_id, content_type, started_at)` assumes no two checkpoints start at exact same millisecond for same session+type
   - **Mitigation**: This is extremely unlikely in practice (checkpoints are per-content-type, sequential)
   - **Alternative**: Use `(session_id, content_type)` and allow only ONE active checkpoint per session+type

2. **DLQ unique constraint**: Using `(session_id, content_id, content_type, retry_count)` changes DLQ semantics
   - **Current**: Append-only failure history
   - **New**: One entry per retry_count (deduplication)
   - **Mitigation**: This is actually desired behavior (no duplicate failures at same retry level)

### High Risk 🔴

1. **Session ID reuse**: If callers reuse session IDs across different extractions, upsert will update existing session instead of creating new one
   - **Impact**: Session stats become incorrect (mixing data from different runs)
   - **Mitigation**:
     - Document that session IDs must be unique per run
     - Generate UUID session IDs by default (already done in orchestrators)
     - Add validation in CLI to prevent manual ID reuse

2. **Migration failure on existing databases**: Table recreation during migration could fail if:
   - Foreign key constraints prevent dropping tables
   - Concurrent access during migration
   - Disk space issues
   - **Mitigation**:
     - Use SQLite PRAGMA foreign_keys = OFF during migration
     - Add migration transaction rollback on error
     - Test migration on production-like database dumps

---

## Rollback Plan

If migration fails or upsert causes issues:

1. **Schema rollback**: Keep backup of original database before migration
   ```bash
   cp looker.db looker.db.backup_pre_v3
   ```

2. **Code rollback**: Git revert commits from this feature
   ```bash
   git revert <commit-range>
   ```

3. **Database recovery**: Restore from backup
   ```bash
   cp looker.db.backup_pre_v3 looker.db
   ```

4. **Partial rollback**: If only specific operations cause issues, comment out ON CONFLICT clause for that operation (revert to plain INSERT temporarily)

---

## Success Criteria

1. ✅ All 5 write operations use INSERT ... ON CONFLICT DO UPDATE
2. ✅ Schema version upgraded to 3 with unique constraints
3. ✅ All unit tests pass (new + existing)
4. ✅ Integration test demonstrates re-run safety: `test_rerun_extraction_upserts_data`
5. ✅ Manual testing confirms workflow: pull → extract → pull → extract → no duplicates
6. ✅ No regressions in existing functionality (all existing tests pass)
7. ✅ Documentation updated (CLAUDE.md, method docstrings)

---

## Timeline Estimate

- **Phase 1** (Schema migration): 2-3 hours
- **Phase 2** (Convert operations): 1-2 hours
- **Phase 3** (Testing): 3-4 hours
- **Phase 4** (Documentation): 1 hour
- **Total**: ~8-10 hours (1-2 days)

---

## References

- SQLite ON CONFLICT: https://www.sqlite.org/lang_conflict.html
- SQLite UPSERT: https://www.sqlite.org/lang_upsert.html
- SQLite ALTER TABLE limitations: https://www.sqlite.org/lang_altertable.html
- Issue: lookervault-yos
