# Data Model: Looker Content Restoration

**Feature**: 004-looker-restoration
**Date**: 2025-12-13
**Status**: Complete

## Overview

This document defines the data models for Looker content restoration, including SQLite schema additions, Python dataclasses, and Looker SDK model mappings.

---

## 1. Database Schema Extensions

### 1.1 Restoration Sessions Table

Tracks individual restoration operations for auditing and progress monitoring.

```sql
CREATE TABLE IF NOT EXISTS restoration_sessions (
    id TEXT PRIMARY KEY,                  -- UUID for session
    started_at TEXT NOT NULL,            -- ISO 8601 timestamp
    completed_at TEXT,                   -- ISO 8601 timestamp (NULL if incomplete)
    status TEXT NOT NULL,                -- 'pending', 'running', 'completed', 'failed', 'cancelled'
    total_items INTEGER DEFAULT 0,       -- Total items processed (successful + failed)
    success_count INTEGER DEFAULT 0,     -- Successfully restored items
    error_count INTEGER DEFAULT 0,       -- Failed items (moved to DLQ)
    source_instance TEXT,                -- Source Looker instance URL (for cross-instance migration)
    destination_instance TEXT NOT NULL,  -- Destination Looker instance URL
    config TEXT,                         -- JSON: session configuration (workers, rate limits, filters)
    metadata TEXT                        -- JSON: additional session metadata
);

CREATE INDEX IF NOT EXISTS idx_restoration_session_status
    ON restoration_sessions(status);
CREATE INDEX IF NOT EXISTS idx_restoration_session_started
    ON restoration_sessions(started_at DESC);
```

### 1.2 Restoration Checkpoints Table

Enables resume capability by tracking progress within a restoration session.

```sql
CREATE TABLE IF NOT EXISTS restoration_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,            -- FK to restoration_sessions.id
    content_type INTEGER NOT NULL,       -- ContentType enum value
    checkpoint_data TEXT NOT NULL,       -- JSON: {"completed_ids": [...], "last_offset": N}
    started_at TEXT NOT NULL,           -- ISO 8601 timestamp
    completed_at TEXT,                  -- ISO 8601 timestamp (NULL if incomplete)
    item_count INTEGER DEFAULT 0,       -- Items processed for this content type
    error_count INTEGER DEFAULT 0,      -- Errors encountered for this content type

    FOREIGN KEY (session_id) REFERENCES restoration_sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_restoration_checkpoint_session
    ON restoration_checkpoints(session_id);
CREATE INDEX IF NOT EXISTS idx_restoration_checkpoint_type
    ON restoration_checkpoints(content_type);
```

### 1.3 ID Mappings Table

Stores source ID → destination ID mappings for cross-instance migration.

```sql
CREATE TABLE IF NOT EXISTS id_mappings (
    source_instance TEXT NOT NULL,       -- Source Looker instance URL
    content_type INTEGER NOT NULL,       -- ContentType enum value
    source_id TEXT NOT NULL,             -- Original ID from source instance
    destination_id TEXT NOT NULL,        -- New ID in destination instance
    created_at TEXT NOT NULL,           -- ISO 8601 timestamp
    session_id TEXT,                    -- FK to restoration_sessions.id

    PRIMARY KEY (source_instance, content_type, source_id),
    FOREIGN KEY (session_id) REFERENCES restoration_sessions(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_id_mapping_dest
    ON id_mappings(destination_id);
CREATE INDEX IF NOT EXISTS idx_id_mapping_session
    ON id_mappings(session_id);
```

### 1.4 Dead Letter Queue Table

Captures failed restoration attempts with full error context.

```sql
CREATE TABLE IF NOT EXISTS dead_letter_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,            -- FK to restoration_sessions.id
    content_id TEXT NOT NULL,            -- Original content ID
    content_type INTEGER NOT NULL,       -- ContentType enum value
    content_data BLOB NOT NULL,          -- Original content blob (for retry)
    error_message TEXT NOT NULL,         -- Error message summary
    error_type TEXT NOT NULL,            -- Exception class name
    stack_trace TEXT,                    -- Full Python traceback
    retry_count INTEGER NOT NULL,        -- Number of retries attempted
    failed_at TEXT NOT NULL,            -- ISO 8601 timestamp
    metadata TEXT,                      -- JSON: additional error context

    FOREIGN KEY (session_id) REFERENCES restoration_sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_dlq_session
    ON dead_letter_queue(session_id);
CREATE INDEX IF NOT EXISTS idx_dlq_content
    ON dead_letter_queue(content_type, content_id);
CREATE INDEX IF NOT EXISTS idx_dlq_failed_at
    ON dead_letter_queue(failed_at DESC);
```

---

## 2. Python Dataclasses

### 2.1 RestorationSession

```python
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

@dataclass
class RestorationSession:
    """Represents a single restoration operation."""

    id: str = field(default_factory=lambda: str(uuid4()))
    started_at: datetime = field(default_factory=datetime.now)
    status: str = "pending"                  # SessionStatus enum value
    total_items: int = 0
    success_count: int = 0
    error_count: int = 0
    destination_instance: str = ""
    source_instance: str | None = None
    completed_at: datetime | None = None
    config: dict | None = None
    metadata: dict | None = None

    def __post_init__(self):
        """Validate status is valid."""
        valid_statuses = {"pending", "running", "completed", "failed", "cancelled"}
        if self.status not in valid_statuses:
            raise ValueError(f"Invalid status: {self.status}")
```

### 2.2 RestorationCheckpoint

```python
@dataclass
class RestorationCheckpoint:
    """Tracks progress within a restoration session for resume capability."""

    content_type: int                       # ContentType enum value
    checkpoint_data: dict                   # {"completed_ids": [...], "last_offset": N}
    started_at: datetime = field(default_factory=datetime.now)
    id: int | None = None
    session_id: str | None = None
    completed_at: datetime | None = None
    item_count: int = 0
    error_count: int = 0
```

### 2.3 IDMapping

```python
@dataclass
class IDMapping:
    """Maps source content IDs to destination content IDs for cross-instance migration."""

    source_instance: str
    content_type: int                       # ContentType enum value
    source_id: str
    destination_id: str
    created_at: datetime = field(default_factory=datetime.now)
    session_id: str | None = None
```

### 2.4 DeadLetterItem

```python
@dataclass
class DeadLetterItem:
    """Represents a content item that failed restoration after all retries."""

    session_id: str
    content_id: str
    content_type: int                       # ContentType enum value
    content_data: bytes
    error_message: str
    error_type: str                         # Exception class name
    retry_count: int
    failed_at: datetime = field(default_factory=datetime.now)
    id: int | None = None
    stack_trace: str | None = None
    metadata: dict | None = None
```

### 2.5 RestorationTask

```python
@dataclass
class RestorationTask:
    """Represents a single content item to be restored (in-memory work unit)."""

    content_id: str
    content_type: int                       # ContentType enum value
    content_data: bytes | None = None       # Lazy-loaded from SQLite
    status: str = "pending"                 # "pending", "in_progress", "completed", "failed"
    priority: int = 0                       # Based on dependency order
    retry_count: int = 0
    error_message: str | None = None

    # Metadata
    name: str | None = None
    owner_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

---

## 3. Looker SDK Model Mappings

### 3.1 Content Type to SDK Write Model Mapping

| Content Type | SDK Write Model | Create Method | Update Method |
|--------------|-----------------|---------------|---------------|
| DASHBOARD | `WriteDashboard` | `create_dashboard` | `update_dashboard` |
| LOOK | `WriteLookWithQuery` | `create_look` | `update_look` |
| FOLDER | `CreateFolder` / `UpdateFolder` | `create_folder` | `update_folder` |
| USER | `WriteUser` | `create_user` | `update_user` |
| GROUP | `WriteGroup` | `create_group` | `update_group` |
| ROLE | `WriteRole` | `create_role` | `update_role` |
| PERMISSION_SET | `WritePermissionSet` | `create_permission_set` | `update_permission_set` |
| MODEL_SET | `WriteModelSet` | `create_model_set` | `update_model_set` |
| BOARD | `WriteBoard` | `create_board` | `update_board` |
| SCHEDULED_PLAN | `WriteScheduledPlan` | `create_scheduled_plan` | `update_scheduled_plan` |
| LOOKML_MODEL | `WriteLookmlModel` | `create_lookml_model` | `update_lookml_model` |
| EXPLORE | *(Read-only via API)* | N/A | N/A |

**Note**: Explores are defined in LookML code and cannot be created/updated via REST API. They should be excluded from restoration or handled via LookML project updates.

### 3.2 Dependency Order Enum

```python
from enum import IntEnum

class DependencyOrder(IntEnum):
    """Defines restoration order based on Looker resource dependencies.

    Lower values are restored first (e.g., USERS before DASHBOARDS).
    """

    USERS = 1
    GROUPS = 2
    PERMISSION_SETS = 3
    MODEL_SETS = 4
    ROLES = 5
    FOLDERS = 6
    LOOKML_MODELS = 7
    # EXPLORES skipped (LookML-defined, not API-restorable)
    LOOKS = 8
    DASHBOARDS = 9
    BOARDS = 10
    SCHEDULED_PLANS = 11
```

---

## 4. Repository Method Extensions

Extend `SQLiteContentRepository` class in `storage/repository.py`:

### 4.1 Restoration Session Methods

```python
def create_restoration_session(self, session: RestorationSession) -> None:
    """Create new restoration session."""

def update_restoration_session(self, session: RestorationSession) -> None:
    """Update existing restoration session."""

def get_restoration_session(self, session_id: str) -> RestorationSession | None:
    """Retrieve restoration session by ID."""

def list_restoration_sessions(
    self,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0
) -> Sequence[RestorationSession]:
    """List restoration sessions with optional status filter."""
```

### 4.2 Restoration Checkpoint Methods

```python
def save_restoration_checkpoint(self, checkpoint: RestorationCheckpoint) -> int:
    """Save restoration checkpoint, returns checkpoint ID."""

def update_restoration_checkpoint(self, checkpoint: RestorationCheckpoint) -> None:
    """Update existing restoration checkpoint."""

def get_latest_restoration_checkpoint(
    self,
    content_type: int,
    session_id: str | None = None
) -> RestorationCheckpoint | None:
    """Get most recent incomplete checkpoint for content type."""

def mark_checkpoint_complete(self, checkpoint_id: int) -> None:
    """Mark checkpoint as completed with timestamp."""
```

### 4.3 ID Mapping Methods

```python
def save_id_mapping(self, mapping: IDMapping) -> None:
    """Save source ID → destination ID mapping."""

def get_id_mapping(
    self,
    source_instance: str,
    content_type: int,
    source_id: str
) -> IDMapping | None:
    """Retrieve ID mapping for source content."""

def get_destination_id(
    self,
    source_instance: str,
    content_type: int,
    source_id: str
) -> str | None:
    """Get destination ID for source ID, returns None if not mapped."""

def batch_get_mappings(
    self,
    source_instance: str,
    content_type: int,
    source_ids: Sequence[str]
) -> dict[str, str]:
    """Batch retrieve mappings, returns dict of source_id -> destination_id."""

def clear_mappings(
    self,
    source_instance: str | None = None,
    content_type: int | None = None
) -> int:
    """Clear ID mappings (all, by instance, or by type), returns count deleted."""
```

### 4.4 Dead Letter Queue Methods

```python
def save_dead_letter_item(self, item: DeadLetterItem) -> int:
    """Save failed restoration item to DLQ, returns DLQ entry ID."""

def get_dead_letter_item(self, dlq_id: int) -> DeadLetterItem | None:
    """Retrieve DLQ entry by ID."""

def list_dead_letter_items(
    self,
    session_id: str | None = None,
    content_type: int | None = None,
    limit: int = 100,
    offset: int = 0
) -> Sequence[DeadLetterItem]:
    """List DLQ entries with optional filters."""

def count_dead_letter_items(
    self,
    session_id: str | None = None,
    content_type: int | None = None
) -> int:
    """Count DLQ entries with optional filters."""

def delete_dead_letter_item(self, dlq_id: int) -> None:
    """Permanently delete DLQ entry (e.g., after successful manual retry)."""
```

### 4.5 Content Query Methods (Existing, but document here for reference)

```python
def get_content(self, content_id: str) -> ContentItem | None:
    """Retrieve content item by ID (existing method)."""

def list_content(
    self,
    content_type: int,
    include_deleted: bool = False,
    limit: int | None = None,
    offset: int = 0
) -> Sequence[ContentItem]:
    """List content items by type (existing method)."""

def count_content(
    self,
    content_type: int,
    include_deleted: bool = False
) -> int:
    """Count content items by type (existing method)."""
```

---

## 5. Validation Models

### 5.1 RestorationConfig

```python
from pydantic import BaseModel, Field, field_validator

class RestorationConfig(BaseModel):
    """Configuration for restoration operation."""

    workers: int = Field(default=8, ge=1, le=32)
    rate_limit_per_minute: int = Field(default=120, ge=1)
    rate_limit_per_second: int = Field(default=10, ge=1)
    checkpoint_interval: int = Field(default=100, ge=1)
    max_retries: int = Field(default=5, ge=0, le=10)
    dry_run: bool = False
    skip_if_modified: bool = False

    # Filtering
    content_types: list[int] | None = None   # None = all types
    content_ids: list[str] | None = None     # None = all IDs
    date_range: tuple[datetime, datetime] | None = None

    # Instance configuration
    source_instance: str | None = None       # For cross-instance migration
    destination_instance: str = ""

    @field_validator('workers')
    @classmethod
    def validate_workers(cls, v: int) -> int:
        """Warn if workers > 16 (SQLite write contention)."""
        if v > 16:
            logger.warning(f"Worker count {v} exceeds recommended limit (16)")
        return v
```

### 5.2 RestorationResult

```python
@dataclass
class RestorationResult:
    """Result of a single content restoration attempt."""

    content_id: str
    content_type: int
    status: str                             # "success", "created", "updated", "failed", "skipped"
    destination_id: str | None = None       # Populated on success
    error_message: str | None = None
    retry_count: int = 0
    duration_ms: float | None = None
```

### 5.3 RestorationSummary

```python
@dataclass
class RestorationSummary:
    """Summary of completed restoration session."""

    session_id: str
    total_items: int
    success_count: int
    created_count: int
    updated_count: int
    error_count: int
    skipped_count: int
    duration_seconds: float
    average_throughput: float               # Items per second
    content_type_breakdown: dict[int, int]  # ContentType -> count
    error_breakdown: dict[str, int]         # Error type -> count
```

---

## 6. State Transitions

### 6.1 RestorationSession Status Transitions

```
pending → running → completed
                 ↘ failed
                 ↘ cancelled
```

### 6.2 RestorationTask Status Transitions

```
pending → in_progress → completed
                      ↘ failed → (moved to DLQ)
```

### 6.3 Checkpoint Lifecycle

```
1. Create checkpoint (started_at set, completed_at = NULL)
2. Update checkpoint periodically with completed_ids
3. Mark complete (completed_at set) when all items processed
4. Resume: Query incomplete checkpoints, filter out completed_ids
```

---

## 7. Relationships

```
restoration_sessions (1) ──┬─→ (N) restoration_checkpoints
                          ├─→ (N) id_mappings
                          └─→ (N) dead_letter_queue

content_items (1) ──→ (0..1) dead_letter_queue  [via content_id]
```

---

## 8. Indexes Summary

| Table | Index | Purpose |
|-------|-------|---------|
| `restoration_sessions` | `idx_restoration_session_status` | Filter by session status |
| `restoration_sessions` | `idx_restoration_session_started` | Sort by recent sessions |
| `restoration_checkpoints` | `idx_restoration_checkpoint_session` | FK lookup |
| `restoration_checkpoints` | `idx_restoration_checkpoint_type` | Find checkpoints by content type |
| `id_mappings` | Primary key on (source_instance, content_type, source_id) | Fast source → dest lookups |
| `id_mappings` | `idx_id_mapping_dest` | Reverse lookups (dest → source) |
| `id_mappings` | `idx_id_mapping_session` | Session-based cleanup |
| `dead_letter_queue` | `idx_dlq_session` | FK lookup |
| `dead_letter_queue` | `idx_dlq_content` | Find failures by content type/ID |
| `dead_letter_queue` | `idx_dlq_failed_at` | Sort by recent failures |

---

## 9. JSON Schema Examples

### 9.1 Checkpoint Data

```json
{
  "completed_ids": ["123", "456", "789"],
  "last_offset": 300,
  "last_updated": "2025-12-13T10:30:00Z"
}
```

### 9.2 Session Config

```json
{
  "workers": 8,
  "rate_limit_per_minute": 120,
  "rate_limit_per_second": 10,
  "checkpoint_interval": 100,
  "max_retries": 5,
  "dry_run": false,
  "skip_if_modified": false,
  "content_types": [1, 2, 9],
  "content_ids": null,
  "date_range": null
}
```

### 9.3 DLQ Metadata

```json
{
  "request_payload": {"title": "...", "folder_id": "..."},
  "response_status": 422,
  "response_body": {"errors": [{"field": "folder_id", "code": "invalid"}]},
  "retry_history": [
    {"attempt": 1, "timestamp": "...", "error": "..."},
    {"attempt": 2, "timestamp": "...", "error": "..."}
  ]
}
```

---

## Summary

This data model provides:

1. **Session tracking** for auditing and progress monitoring
2. **Checkpointing** for resume capability after interruptions
3. **ID mapping** for cross-instance migration scenarios
4. **Dead letter queue** for graceful error handling
5. **Repository methods** for all CRUD operations
6. **Validation models** for configuration and results
7. **Clear relationships** and indexes for query performance

All models integrate seamlessly with existing `storage/` infrastructure while maintaining backward compatibility with extraction features.
