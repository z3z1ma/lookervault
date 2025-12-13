# Data Model: Looker Content Extraction System

**Feature**: 001-looker-content-extraction
**Date**: 2025-12-13
**Status**: Design Complete

## Overview

This document defines the data model for storing extracted Looker content in SQLite. The design prioritizes **faithful preservation**, **efficient querying**, and **resume capability**.

---

## Entity Relationship Diagram

```
┌─────────────────────────┐
│  ExtractionSession      │
│  ─────────────────────  │
│  id (PK)                │
│  started_at             │
│  completed_at           │
│  status                 │
│  total_items            │
│  error_count            │
└────────┬────────────────┘
         │
         │ 1:N
         │
         ▼
┌─────────────────────────┐      ┌─────────────────────────┐
│  Checkpoint             │      │  ContentItem            │
│  ─────────────────────  │      │  ─────────────────────  │
│  id (PK)                │      │  id (PK)                │
│  session_id (FK)        │      │  content_type           │
│  content_type           │      │  name                   │
│  checkpoint_data (JSON) │      │  owner_id               │
│  started_at             │      │  created_at             │
│  completed_at           │      │  updated_at             │
│  item_count             │      │  synced_at              │
│  error_message          │      │  deleted_at             │
└─────────────────────────┘      │  content_size           │
                                 │  content_data (BLOB)    │
                                 └─────────────────────────┘
```

---

## Entity Definitions

### 1. ContentItem

**Purpose**: Stores individual Looker content with binary data and searchable metadata.

**Schema**:
```sql
CREATE TABLE content_items (
    -- Primary identifier
    id TEXT PRIMARY KEY NOT NULL,

    -- Content classification
    content_type INTEGER NOT NULL,

    -- Searchable metadata
    name TEXT NOT NULL,
    owner_id INTEGER,
    owner_email TEXT,

    -- Timestamps
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    synced_at TEXT NOT NULL,
    deleted_at TEXT DEFAULT NULL,

    -- Size tracking
    content_size INTEGER NOT NULL,

    -- Binary payload (MUST be last column for performance)
    content_data BLOB NOT NULL
);

-- Performance indexes (partial for active records only)
CREATE INDEX idx_content_type ON content_items(content_type)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_owner_id ON content_items(owner_id)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_updated_at ON content_items(updated_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_deleted_at ON content_items(deleted_at)
    WHERE deleted_at IS NOT NULL;
```

**Fields**:

| Field | Type | Required | Description | Validation |
|-------|------|----------|-------------|------------|
| id | TEXT | Yes | Composite Looker ID (e.g., "dashboard::123") | Unique, format: "{type}::{id}" |
| content_type | INTEGER | Yes | Content type enum | 1-11 (see enum below) |
| name | TEXT | Yes | Human-readable name/title | Max 255 chars |
| owner_id | INTEGER | No | Looker user ID of owner | Positive integer or NULL |
| owner_email | TEXT | No | Owner email address | Valid email or NULL |
| created_at | TEXT | Yes | When item was created in Looker | ISO 8601 format |
| updated_at | TEXT | Yes | Last modified in Looker | ISO 8601 format |
| synced_at | TEXT | Yes | When extracted to local DB | ISO 8601 format, auto-set |
| deleted_at | TEXT | No | Soft delete timestamp | ISO 8601 or NULL |
| content_size | INTEGER | Yes | Size of content_data in bytes | Positive integer |
| content_data | BLOB | Yes | Serialized content (msgpack) | Non-empty binary |

**Content Type Enum**:
```python
class ContentType(IntEnum):
    DASHBOARD = 1
    LOOK = 2
    LOOKML_MODEL = 3
    EXPLORE = 4
    FOLDER = 5
    BOARD = 6
    USER = 7
    GROUP = 8
    ROLE = 9
    PERMISSION_SET = 10
    MODEL_SET = 11
    SCHEDULED_PLAN = 12
```

**Validation Rules**:
- `id` must be unique across all content types
- `content_type` must be valid enum value (1-12)
- `name` cannot be empty string
- `created_at`, `updated_at`, `synced_at` must be valid ISO 8601 timestamps
- `content_size` must match actual `len(content_data)`
- `content_data` must be valid msgpack-encoded binary
- If `deleted_at` is set, item is considered soft-deleted

**State Transitions**:
```
[New Item]
    ↓ synced_at set
[Active Item] (deleted_at = NULL)
    ↓ deleted_at set
[Soft Deleted] (deleted_at != NULL)
    ↓ retention period expires
[Hard Deleted] (removed from DB)
```

---

### 2. Checkpoint

**Purpose**: Enables resuming interrupted extractions from last successful point.

**Schema**:
```sql
CREATE TABLE sync_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    content_type INTEGER NOT NULL,
    checkpoint_data TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT DEFAULT NULL,
    item_count INTEGER DEFAULT 0,
    error_message TEXT DEFAULT NULL
);

CREATE INDEX idx_checkpoint_type_completed
    ON sync_checkpoints(content_type, completed_at);

CREATE INDEX idx_checkpoint_session
    ON sync_checkpoints(session_id);
```

**Fields**:

| Field | Type | Required | Description | Validation |
|-------|------|----------|-------------|------------|
| id | INTEGER | Yes (auto) | Unique checkpoint ID | Auto-increment |
| session_id | TEXT | No | Reference to extraction session | UUID format or NULL |
| content_type | INTEGER | Yes | Type being extracted | Valid ContentType enum |
| checkpoint_data | TEXT | Yes | JSON resume state | Valid JSON object |
| started_at | TEXT | Yes | When checkpoint started | ISO 8601 format |
| completed_at | TEXT | No | When checkpoint completed | ISO 8601 or NULL |
| item_count | INTEGER | Yes | Items processed | Non-negative |
| error_message | TEXT | No | Error if failed | Text or NULL |

**Checkpoint Data JSON Schema**:
```json
{
    "content_type": "dashboards",
    "last_processed_id": "dashboard::123",
    "last_offset": 500,
    "total_processed": 500,
    "batch_size": 100,
    "fields": "id,title,description,folder",
    "extraction_config": {
        "include_deleted": false,
        "fields_requested": ["id", "title", "description"]
    }
}
```

**Validation Rules**:
- `checkpoint_data` must be valid JSON
- `completed_at` must be >= `started_at` if set
- `item_count` must be >= 0
- If `completed_at` is NULL, checkpoint is considered incomplete
- If `error_message` is set, checkpoint failed

**State Transitions**:
```
[Created]
    ↓ started_at set
[In Progress] (completed_at = NULL, error_message = NULL)
    ↓ completed_at set
[Completed] (completed_at != NULL, error_message = NULL)

[In Progress]
    ↓ error_message set
[Failed] (error_message != NULL)
```

---

### 3. ExtractionSession

**Purpose**: Tracks overall extraction operations for auditing and monitoring.

**Schema**:
```sql
CREATE TABLE extraction_sessions (
    id TEXT PRIMARY KEY NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT DEFAULT NULL,
    status TEXT NOT NULL,
    total_items INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    config TEXT,
    metadata TEXT
);

CREATE INDEX idx_session_started ON extraction_sessions(started_at DESC);
CREATE INDEX idx_session_status ON extraction_sessions(status);
```

**Fields**:

| Field | Type | Required | Description | Validation |
|-------|------|----------|-------------|------------|
| id | TEXT | Yes | Unique session ID | UUID format |
| started_at | TEXT | Yes | Session start time | ISO 8601 format |
| completed_at | TEXT | No | Session end time | ISO 8601 or NULL |
| status | TEXT | Yes | Current status | Enum: pending, running, completed, failed |
| total_items | INTEGER | Yes | Total items extracted | Non-negative |
| error_count | INTEGER | Yes | Number of errors | Non-negative |
| config | TEXT | No | Extraction configuration (JSON) | Valid JSON or NULL |
| metadata | TEXT | No | Additional metadata (JSON) | Valid JSON or NULL |

**Status Enum**:
```python
class SessionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

**Validation Rules**:
- `id` must be unique UUID
- `status` must be valid enum value
- `completed_at` must be >= `started_at` if set
- If `status` = "completed", `completed_at` must be set
- `config` and `metadata` must be valid JSON if not NULL

**State Transitions**:
```
[Created]
    ↓ status = pending
[Pending]
    ↓ status = running
[Running]
    ↓ status = completed (success)
    ↓ status = failed (error)
    ↓ status = cancelled (user abort)
[Terminal State]
```

---

## Data Access Patterns

### 1. Insert New Content

```python
import msgspec
from datetime import datetime

# Serialize content
content_blob = msgspec.msgpack.encode(looker_dashboard_dict)

# Insert
cursor.execute("""
    INSERT INTO content_items (
        id, content_type, name, owner_id, owner_email,
        created_at, updated_at, synced_at, content_size, content_data
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (
    "dashboard::123",
    ContentType.DASHBOARD,
    "Sales Overview",
    456,
    "owner@example.com",
    "2025-01-15T10:30:00Z",
    "2025-12-13T11:00:00Z",
    datetime.now().isoformat(),
    len(content_blob),
    content_blob
))
```

### 2. Query Active Items by Type

```python
# Query metadata only (efficient - doesn't load BLOB)
cursor.execute("""
    SELECT id, name, owner_email, updated_at
    FROM content_items
    WHERE content_type = ? AND deleted_at IS NULL
    ORDER BY updated_at DESC
""", (ContentType.DASHBOARD,))
```

### 3. Retrieve Full Content

```python
# Fetch specific item with binary data
cursor.execute("""
    SELECT content_data FROM content_items WHERE id = ?
""", ("dashboard::123",))

blob = cursor.fetchone()[0]
dashboard = msgspec.msgpack.decode(blob)
```

### 4. Soft Delete

```python
from datetime import datetime

cursor.execute("""
    UPDATE content_items
    SET deleted_at = ?
    WHERE id = ?
""", (datetime.now().isoformat(), "dashboard::123"))
```

### 5. Create Checkpoint

```python
import json

checkpoint_data = {
    "content_type": "dashboards",
    "last_offset": 500,
    "total_processed": 500,
    "batch_size": 100
}

cursor.execute("""
    INSERT INTO sync_checkpoints (
        session_id, content_type, checkpoint_data, started_at, item_count
    ) VALUES (?, ?, ?, ?, ?)
""", (
    session_id,
    ContentType.DASHBOARD,
    json.dumps(checkpoint_data),
    datetime.now().isoformat(),
    500
))
```

### 6. Resume from Checkpoint

```python
# Find incomplete checkpoint
cursor.execute("""
    SELECT checkpoint_data
    FROM sync_checkpoints
    WHERE content_type = ? AND completed_at IS NULL
    ORDER BY started_at DESC
    LIMIT 1
""", (ContentType.DASHBOARD,))

row = cursor.fetchone()
if row:
    resume_data = json.loads(row[0])
    offset = resume_data["last_offset"]
    # Continue extraction from offset
```

---

## Data Integrity Constraints

### 1. Referential Integrity

- No foreign keys between tables (for simplicity and performance)
- `session_id` in checkpoints is optional reference (soft link)
- Application-level consistency enforcement

### 2. Data Validation

**At Insert/Update:**
- Validate enum values before insert
- Validate ISO 8601 timestamp format
- Validate JSON format for checkpoint_data
- Verify content_size matches actual BLOB size
- Ensure non-empty required text fields

**Example Validation:**
```python
from datetime import datetime

def validate_content_item(item: dict) -> None:
    """Validate content item before insert."""

    # Required fields
    assert item["id"], "ID required"
    assert item["name"], "Name required"

    # Valid enum
    assert 1 <= item["content_type"] <= 12, "Invalid content type"

    # Valid timestamps
    for field in ["created_at", "updated_at", "synced_at"]:
        datetime.fromisoformat(item[field])  # Raises if invalid

    # Size matches
    assert item["content_size"] == len(item["content_data"]), "Size mismatch"

    # Valid msgpack
    msgspec.msgpack.decode(item["content_data"])  # Raises if invalid
```

### 3. Atomicity

- Use transactions for multi-row operations
- Checkpoint + content items inserted in single transaction
- Rollback on error to maintain consistency

```python
with conn:  # Auto-commit on success, rollback on exception
    # Insert session
    conn.execute("INSERT INTO extraction_sessions (...) VALUES (...)")

    # Insert checkpoint
    conn.execute("INSERT INTO sync_checkpoints (...) VALUES (...)")

    # Insert content items
    for item in batch:
        conn.execute("INSERT INTO content_items (...) VALUES (...)")
```

---

## Performance Optimizations

### 1. Index Strategy

**Partial Indexes** (50-70% size reduction):
```sql
-- Only index active records
CREATE INDEX idx_content_type ON content_items(content_type)
    WHERE deleted_at IS NULL;
```

**Covering Indexes** (avoid BLOB access):
```sql
-- Metadata queries never touch content_data column
SELECT id, name, owner_email FROM content_items WHERE ...
```

### 2. Query Optimization

**Always filter deleted items:**
```python
# Good - uses partial index
cursor.execute("""
    SELECT id, name FROM content_items
    WHERE content_type = ? AND deleted_at IS NULL
""", (1,))

# Bad - full table scan
cursor.execute("""
    SELECT id, name FROM content_items WHERE content_type = ?
""", (1,))
```

**Fetch BLOB only when needed:**
```python
# Separate queries for metadata vs content
# First: Get IDs (fast)
ids = cursor.execute("SELECT id FROM content_items WHERE ...").fetchall()

# Then: Fetch BLOBs individually as needed
for (id,) in ids:
    if needs_content(id):
        blob = cursor.execute(
            "SELECT content_data FROM content_items WHERE id = ?", (id,)
        ).fetchone()[0]
```

### 3. Batch Operations

**Bulk Insert:**
```python
# Use executemany for batches
items = [(id1, type1, name1, ...), (id2, type2, name2, ...)]
cursor.executemany("""
    INSERT INTO content_items (...) VALUES (?, ?, ?, ...)
""", items)
```

### 4. SQLite Configuration

```python
# Optimized for 10MB BLOBs
conn.execute("PRAGMA page_size = 16384")  # 16KB pages
conn.execute("PRAGMA cache_size = -64000")  # 64MB cache
conn.execute("PRAGMA journal_mode = WAL")  # Write-Ahead Logging
conn.execute("PRAGMA synchronous = NORMAL")  # Balance safety/speed
conn.execute("PRAGMA temp_store = MEMORY")  # Temp tables in RAM
```

---

## Retention Policy Implementation

### Soft Delete with Retention

```python
from datetime import datetime, timedelta

def apply_retention_policy(conn, retention_days: int = 30):
    """Delete soft-deleted items older than retention period."""

    cutoff_date = (datetime.now() - timedelta(days=retention_days)).isoformat()

    # Hard delete old soft-deleted items
    cursor = conn.execute("""
        DELETE FROM content_items
        WHERE deleted_at IS NOT NULL
        AND deleted_at < ?
    """, (cutoff_date,))

    deleted_count = cursor.rowcount
    logger.info(f"Purged {deleted_count} items past retention period")

    return deleted_count
```

---

## Migration Strategy

### Schema Versioning

**Version Table:**
```sql
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL,
    description TEXT
);

INSERT INTO schema_version VALUES (1, '2025-12-13T12:00:00Z', 'Initial schema');
```

**Future Migrations:**
```python
def migrate_to_v2(conn):
    """Example migration."""
    current = conn.execute(
        "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
    ).fetchone()[0]

    if current < 2:
        # Apply migration
        conn.execute("ALTER TABLE content_items ADD COLUMN new_field TEXT")
        conn.execute(
            "INSERT INTO schema_version VALUES (2, ?, 'Add new_field')",
            (datetime.now().isoformat(),)
        )
```

---

## Data Model Summary

| Entity | Purpose | Key Fields | Relationships |
|--------|---------|------------|---------------|
| ContentItem | Store Looker content | id, content_type, content_data | Standalone |
| Checkpoint | Enable resume | content_type, checkpoint_data | Links to session (optional) |
| ExtractionSession | Track operations | id, status, total_items | 1:N with checkpoints |

**Total Tables**: 3
**Total Indexes**: 7 (4 partial, 3 regular)
**Storage Model**: Single SQLite file with WAL journal
**Serialization**: msgpack via msgspec library
**Max Item Size**: 10MB (tested, performant)

---

## Next Steps

1. ✅ Data model defined
2. ⏭️ Define API contracts (internal Python interfaces)
3. ⏭️ Create quickstart guide
4. ⏭️ Implement schema creation in code
5. ⏭️ Add migrations framework
6. ⏭️ Write comprehensive tests
