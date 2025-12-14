# Data Model: Cloud Snapshot Storage & Management

**Feature**: 005-cloud-snapshot-storage
**Date**: 2025-12-13

## Overview

This document defines the data models and entities for cloud snapshot management in LookerVault. All models use Pydantic for validation and configuration management.

---

## Core Entities

### SnapshotMetadata

Represents metadata about a single snapshot stored in Google Cloud Storage.

**Attributes**:
- `sequential_index: int` - User-facing index (1, 2, 3...) for easy reference
- `filename: str` - Full blob name in GCS (e.g., "looker-2025-12-13T14-30-00.db.gz")
- `timestamp: datetime` - UTC timestamp extracted from filename
- `size_bytes: int` - Size of the snapshot file in bytes
- `size_mb: float` - Computed property: size in megabytes (for display)
- `gcs_bucket: str` - GCS bucket name where snapshot is stored
- `gcs_path: str` - Full GCS path (gs://bucket/prefix/filename)
- `crc32c: str` - Base64-encoded CRC32C checksum for integrity verification
- `content_encoding: str | None` - Content encoding (e.g., "gzip")
- `tags: list[str]` - Protection tags (production, staging, critical, etc.)
- `created: datetime` - Blob creation timestamp in GCS
- `updated: datetime` - Last modified timestamp in GCS

**Relationships**:
- Stored in GCS bucket (one-to-many: bucket contains many snapshots)
- Referenced by restoration operations (many-to-one: multiple restores can use same snapshot)

**Validation Rules**:
- `sequential_index` must be positive integer
- `filename` must match pattern: `{prefix}-YYYY-MM-DDTHH-MM-SS.db[.gz]`
- `timestamp` must be valid UTC datetime
- `size_bytes` must be non-negative
- `crc32c` must be valid base64-encoded string

**Example**:
```python
SnapshotMetadata(
    sequential_index=1,
    filename="looker-2025-12-13T14-30-00.db.gz",
    timestamp=datetime(2025, 12, 13, 14, 30, 0, tzinfo=timezone.utc),
    size_bytes=104857600,  # 100 MB
    size_mb=100.0,
    gcs_bucket="lookervault-backups",
    gcs_path="gs://lookervault-backups/snapshots/looker-2025-12-13T14-30-00.db.gz",
    crc32c="AAAAAA==",
    content_encoding="gzip",
    tags=["production"],
    created=datetime(2025, 12, 13, 14, 32, 15, tzinfo=timezone.utc),
    updated=datetime(2025, 12, 13, 14, 32, 15, tzinfo=timezone.utc),
)
```

---

### RetentionPolicy

Defines how long snapshots are retained and when they are automatically deleted.

**Attributes**:
- `min_days: int` - Minimum retention period in days (safety mechanism, default: 30)
- `max_days: int` - Maximum retention period in days (cost control, default: 90)
- `min_count: int` - Minimum number of snapshots to always retain (default: 5)
- `lock_policy: bool` - Whether to lock GCS retention policy (irreversible, default: False)
- `enabled: bool` - Whether retention policy enforcement is enabled (default: True)

**Relationships**:
- Applied during snapshot upload operations (enforces minimum retention via GCS bucket policy)
- Applied during cleanup operations (enforces maximum age and minimum count)

**Validation Rules**:
- `min_days` must be >= 1
- `max_days` must be >= `min_days`
- `min_count` must be >= 0 (0 means no minimum count protection)
- If `lock_policy` is True, `min_days` becomes permanent (cannot be decreased)

**Constraints**:
- GCS retention policy minimum: 1 day
- GCS retention policy maximum: 36,500 days (100 years)
- Lifecycle policy age must be >= retention policy age

**Example**:
```python
RetentionPolicy(
    min_days=30,          # Cannot delete before 30 days
    max_days=90,          # Auto-delete after 90 days
    min_count=5,          # Always keep 5 most recent
    lock_policy=False,    # Not locked (can be changed)
    enabled=True,         # Enforcement enabled
)
```

---

### GCSStorageProvider

Represents configuration for Google Cloud Storage connection and operations.

**Attributes**:
- `bucket_name: str` - GCS bucket name for snapshot storage
- `project_id: str | None` - GCP project ID (auto-detected from credentials if None)
- `credentials_path: str | None` - Path to service account JSON key (uses ADC if None)
- `region: str` - GCS bucket region (default: "us-central1")
- `storage_class: str` - Initial storage class (default: "STANDARD")
- `autoclass_enabled: bool` - Whether to enable GCS Autoclass (default: True)
- `prefix: str` - Object name prefix for snapshots (default: "snapshots/")
- `filename_prefix: str` - Snapshot filename prefix (default: "looker")
- `compression_enabled: bool` - Whether to compress snapshots with gzip (default: True)
- `compression_level: int` - Gzip compression level 1-9 (default: 6)

**Relationships**:
- Manages snapshot upload, download, listing, and deletion operations
- Configured via lookervault.toml or environment variables

**Validation Rules**:
- `bucket_name` must be valid GCS bucket name (lowercase, alphanumeric, hyphens)
- `region` must be valid GCS region (e.g., "us-central1", "europe-west1")
- `storage_class` must be one of: STANDARD, NEARLINE, COLDLINE, ARCHIVE
- `compression_level` must be 1-9 (1=fastest, 9=best compression)
- `prefix` must not start with "/" and should end with "/" for directory-style naming

**Example**:
```python
GCSStorageProvider(
    bucket_name="lookervault-backups",
    project_id="my-gcp-project",
    credentials_path=None,  # Use ADC
    region="us-central1",
    storage_class="STANDARD",
    autoclass_enabled=True,
    prefix="snapshots/",
    filename_prefix="looker",
    compression_enabled=True,
    compression_level=6,
)
```

---

### SnapshotConfig

Top-level configuration for snapshot management (integrates all entities).

**Attributes**:
- `provider: GCSStorageProvider` - GCS storage configuration
- `retention: RetentionPolicy` - Retention and cleanup policy
- `cache_ttl_minutes: int` - Local cache TTL for snapshot listings (default: 5)
- `audit_log_path: str` - Path to local audit log file (default: "~/.lookervault/audit.log")
- `audit_gcs_bucket: str | None` - GCS bucket for centralized audit logs (optional)

**Relationships**:
- Loaded from lookervault.toml configuration file
- Passed to snapshot CLI commands and service classes

**Validation Rules**:
- `cache_ttl_minutes` must be >= 0 (0 disables caching)
- `audit_log_path` must be writable
- `audit_gcs_bucket` must be valid GCS bucket name if specified

**Example**:
```python
SnapshotConfig(
    provider=GCSStorageProvider(
        bucket_name="lookervault-backups",
        region="us-central1",
    ),
    retention=RetentionPolicy(
        min_days=30,
        max_days=90,
        min_count=5,
    ),
    cache_ttl_minutes=5,
    audit_log_path="~/.lookervault/audit.log",
    audit_gcs_bucket="lookervault-audit-logs",
)
```

---

## Configuration Schema

### lookervault.toml Format

```toml
# Snapshot management configuration
[snapshot]
# GCS Storage Provider
bucket_name = "lookervault-backups"
project_id = "my-gcp-project"  # Optional, auto-detected from credentials
region = "us-central1"
storage_class = "STANDARD"
autoclass_enabled = true
prefix = "snapshots/"
filename_prefix = "looker"

# Compression
compression_enabled = true
compression_level = 6  # 1 (fast) to 9 (best)

# Retention Policy
[snapshot.retention]
min_days = 30
max_days = 90
min_count = 5
lock_policy = false
enabled = true

# Caching
cache_ttl_minutes = 5

# Audit Logging
audit_log_path = "~/.lookervault/audit.log"
audit_gcs_bucket = "lookervault-audit-logs"  # Optional
```

### Environment Variables

Configuration can also be provided via environment variables:

```bash
# GCS credentials (uses Application Default Credentials if not set)
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"

# GCS bucket configuration
export LOOKERVAULT_GCS_BUCKET="lookervault-backups"
export LOOKERVAULT_GCS_PROJECT="my-gcp-project"
export LOOKERVAULT_GCS_REGION="us-central1"

# Retention policy overrides
export LOOKERVAULT_RETENTION_MIN_DAYS=30
export LOOKERVAULT_RETENTION_MAX_DAYS=90
export LOOKERVAULT_RETENTION_MIN_COUNT=5
```

---

## State Transitions

### Snapshot Lifecycle States

```
Created (Local) → Uploading → Uploaded (Active) → Protected → Archived → Deleted
```

**State Descriptions**:

1. **Created (Local)**: SQLite database file exists locally (looker.db)
2. **Uploading**: File is being compressed and uploaded to GCS
3. **Uploaded (Active)**: Snapshot is available in GCS (STANDARD storage class)
4. **Protected**: Snapshot has `temporary_hold = True` (cannot be deleted by lifecycle)
5. **Archived**: Snapshot transitioned to ARCHIVE storage class (via Autoclass or lifecycle)
6. **Deleted**: Snapshot removed from GCS (soft-deleted for 7 days, then permanently deleted)

**Transition Triggers**:

| From State | To State | Trigger | Duration |
|------------|----------|---------|----------|
| Created → Uploading | User runs `upload` command | Immediate |
| Uploading → Uploaded | Upload completes successfully | ~30s for 100MB |
| Uploaded → Protected | User/system applies temporary hold | Immediate |
| Uploaded → Archived | Autoclass or lifecycle policy | 365 days (default) |
| Any → Deleted | Lifecycle policy (age > max_days) or manual deletion | Configurable |
| Deleted → Permanently Deleted | GCS soft delete period expires | 7 days |

---

## Data Flow Diagrams

### Upload Flow

```
Local Database (looker.db)
    ↓
Compression (gzip, level 6)
    ↓
CRC32C Checksum Computation
    ↓
GCS Resumable Upload (8MB chunks)
    ↓
Server-Side Checksum Verification
    ↓
SnapshotMetadata Creation
    ↓
Apply Retention Policy (if enabled)
    ↓
Audit Log Entry
    ↓
Cache Update (local)
```

### Download Flow

```
List Snapshots (cached or live)
    ↓
User Selects by Index or Timestamp
    ↓
Fetch SnapshotMetadata
    ↓
Download from GCS (with progress)
    ↓
CRC32C Checksum Verification
    ↓
Decompression (if gzip)
    ↓
Save as looker.db (local)
    ↓
Audit Log Entry
```

### Retention Enforcement Flow

```
Scheduled Cron Job (daily)
    ↓
List All Snapshots
    ↓
Sort by Creation Time (newest first)
    ↓
Protect N Most Recent (temporary_hold = True)
    ↓
Identify Candidates for Deletion (age > max_days)
    ↓
Check Minimum Count (skip if < min_count total)
    ↓
Remove Temporary Hold from Old Snapshots
    ↓
GCS Lifecycle Policy Deletes (background)
    ↓
Audit Log Entries
```

---

## Indexes and Queries

### Snapshot Listing Query

**Purpose**: Retrieve all snapshots sorted by timestamp (newest first) with sequential indices

```python
def list_snapshots(bucket_name: str, prefix: str) -> list[SnapshotMetadata]:
    # 1. Fetch from GCS (with pagination)
    blobs = client.list_blobs(bucket_name, prefix=prefix)

    # 2. Sort by creation time (newest first)
    sorted_blobs = sorted(blobs, key=lambda b: b.time_created, reverse=True)

    # 3. Assign sequential indices (1, 2, 3...)
    metadata = [
        SnapshotMetadata(
            sequential_index=i,
            filename=blob.name,
            timestamp=parse_timestamp_from_filename(blob.name),
            size_bytes=blob.size,
            gcs_bucket=bucket_name,
            crc32c=blob.crc32c,
            created=blob.time_created,
            updated=blob.updated,
        )
        for i, blob in enumerate(sorted_blobs, start=1)
    ]

    return metadata
```

**Performance Considerations**:
- Use local cache (5-minute TTL) to avoid repeated API calls
- GCS list operations paginate at 1000 results (handled automatically by SDK)
- For 100 snapshots: ~200ms query time, ~50ms with cache

### Snapshot Lookup by Index

**Purpose**: Retrieve specific snapshot by sequential index

```python
def get_snapshot_by_index(index: int) -> SnapshotMetadata:
    # List all snapshots (uses cache if available)
    snapshots = list_snapshots(bucket_name, prefix)

    # Index is 1-based (user-facing)
    if index < 1 or index > len(snapshots):
        raise ValueError(f"Invalid index {index}. Valid range: 1-{len(snapshots)}")

    return snapshots[index - 1]
```

### Snapshot Lookup by Timestamp

**Purpose**: Retrieve specific snapshot by exact timestamp

```python
def get_snapshot_by_timestamp(timestamp: datetime) -> SnapshotMetadata:
    # Construct expected filename
    filename = f"{filename_prefix}-{timestamp.strftime('%Y-%m-%dT%H-%M-%S')}.db.gz"

    # Fetch specific blob
    blob = bucket.blob(f"{prefix}{filename}")

    if not blob.exists():
        raise ValueError(f"Snapshot not found: {filename}")

    blob.reload()  # Fetch metadata

    return SnapshotMetadata(
        sequential_index=None,  # Not assigned yet
        filename=blob.name,
        timestamp=timestamp,
        size_bytes=blob.size,
        gcs_bucket=bucket_name,
        crc32c=blob.crc32c,
        created=blob.time_created,
        updated=blob.updated,
    )
```

---

## Assumptions

1. **Timestamp Uniqueness**: Snapshot filenames include UTC timestamp with second precision; multiple uploads within the same second are unlikely but would cause filename conflicts (handled by failing the upload with clear error message)

2. **Single Bucket**: All snapshots for a Looker instance are stored in a single GCS bucket (multi-bucket support not required for MVP)

3. **Sequential Index Stability**: Sequential indices (1, 2, 3...) are computed dynamically each time snapshots are listed; indices may change if snapshots are deleted (acceptable for CLI tool)

4. **Cache Consistency**: 5-minute cache TTL means snapshot listings may be stale for up to 5 minutes after uploads/deletions (acceptable trade-off for performance)

5. **Compression Benefit**: Gzip compression provides significant size reduction for Looker JSON content (60-80% typical); binary blobs in SQLite may not compress well (documented limitation)

6. **Storage Class Transitions**: Autoclass automatically manages storage class transitions; manual lifecycle policies are alternative if Autoclass is disabled

7. **Soft Delete Protection**: GCS soft delete (7-day recovery) is enabled by default; provides safety net for accidental deletions (user should verify GCS bucket configuration)
