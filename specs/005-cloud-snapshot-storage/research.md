# Research: Cloud Snapshot Storage & Management

**Feature**: 005-cloud-snapshot-storage
**Date**: 2025-12-13
**Status**: Complete

## Overview

This document consolidates research findings for implementing cloud snapshot management in LookerVault, covering Google Cloud Storage integration, retention policies, and interactive terminal UI patterns.

---

## 1. Google Cloud Storage Integration

### Authentication Strategy

**Decision**: Use Application Default Credentials (ADC) with GOOGLE_APPLICATION_CREDENTIALS

**Rationale**:
- ADC is the recommended approach by Google Cloud for production CLI tools
- Automatically discovers credentials from multiple sources (environment variable, gcloud CLI, service accounts)
- Provides flexibility for different deployment scenarios (local dev, CI/CD, GCE/GKE)
- No need for explicit credential management in code

**Implementation Pattern**:
```python
from google.cloud import storage
from google.auth.exceptions import DefaultCredentialsError

def create_storage_client(project_id: str | None = None) -> storage.Client:
    try:
        if project_id:
            client = storage.Client(project=project_id)
        else:
            client = storage.Client()  # Auto-detect from credentials
        return client
    except DefaultCredentialsError as e:
        raise RuntimeError(
            "No valid credentials found. Set GOOGLE_APPLICATION_CREDENTIALS "
            "or run 'gcloud auth application-default login'"
        ) from e
```

**Alternatives Considered**:
- **Explicit service account JSON**: Less flexible, requires file path management
- **OAuth2 user credentials**: Not suitable for automation/CI/CD scenarios
- **API key authentication**: Not supported for Cloud Storage

---

### File Upload with Compression

**Decision**: Use automatic resumable uploads (>8MB) with gzip compression and CRC32C checksums

**Rationale**:
- SDK automatically uses resumable upload protocol for files >8MB (no configuration needed)
- Gzip compression provides 60-80% size reduction for JSON/text data (significant cost savings)
- CRC32C is Google's recommended checksum algorithm (works for all objects including composite)
- Chunked uploads with progress tracking provides good UX for large files

**Implementation Pattern**:
```python
from google.cloud import storage
from google.cloud.storage.retry import DEFAULT_RETRY
import gzip

def upload_compressed_snapshot(
    client: storage.Client,
    bucket_name: str,
    source_path: Path,
    destination_blob_name: str,
    chunk_size: int = 8 * 1024 * 1024,  # 8 MB recommended
) -> dict[str, str]:
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)

    # Compress to temporary file
    compressed_path = Path(f"{source_path}.gz")
    with open(source_path, "rb") as f_in:
        with gzip.open(compressed_path, "wb") as f_out:
            while chunk := f_in.read(chunk_size):
                f_out.write(chunk)

    # Set content encoding for transparent decompression
    blob.content_encoding = "gzip"

    # Upload with automatic resumable upload (files >8 MB)
    with open(compressed_path, "rb") as f:
        blob.upload_from_file(
            f,
            checksum="crc32c",      # Integrity verification
            retry=DEFAULT_RETRY,    # Exponential backoff
            timeout=3600,           # 1 hour for large files
        )

    compressed_path.unlink()  # Cleanup
    blob.reload()

    return {
        "name": blob.name,
        "crc32c": blob.crc32c,
        "size": blob.size,
    }
```

**Chunk Size Guidelines**:
- Minimum: 256 KiB (required by GCS)
- Recommended: 8 MiB (balance of speed vs. memory)
- Large files (>1GB): 16-32 MiB for faster uploads

**Alternatives Considered**:
- **No compression**: Simpler but 5-10x higher storage costs for text-heavy Looker content
- **MD5 checksums**: Not supported for composite objects; CRC32C is more reliable
- **Manual resumable upload sessions**: More complex; SDK's automatic handling is sufficient

---

### Integrity Verification

**Decision**: Use CRC32C checksums for all upload/download verification

**Rationale**:
- CRC32C is Google Cloud's recommended integrity check (supported for all object types)
- MD5 is legacy and not supported for composite objects
- Server-side verification happens automatically when `checksum="crc32c"` is specified
- Client-side verification ensures end-to-end data integrity

**Implementation Pattern**:
```python
import google_crc32c
import base64

def verify_download_integrity(blob: storage.Blob, local_path: Path) -> bool:
    # Compute local checksum
    crc32c_hash = google_crc32c.Checksum()
    with open(local_path, "rb") as f:
        while chunk := f.read(8192):
            crc32c_hash.update(chunk)

    local_crc32c = base64.b64encode(crc32c_hash.digest()).decode("utf-8")

    # Compare with GCS-stored checksum
    if blob.crc32c == local_crc32c:
        return True
    else:
        local_path.unlink()  # Delete corrupted file
        return False
```

**Required Dependency**: `google-crc32c` (add via `uv add google-crc32c`)

---

### Retry Logic and Error Handling

**Decision**: Use SDK's built-in DEFAULT_RETRY for most operations; add tenacity for application-level retries

**Rationale**:
- SDK's DEFAULT_RETRY handles common transient errors (429, 500, 502, 503, 504, network failures)
- Exponential backoff with jitter is built-in
- Tenacity provides additional flexibility for custom retry logic (e.g., DLQ integration)
- Separate retry concerns: SDK for network/API errors, application for business logic

**Implementation Pattern**:
```python
from google.api_core import retry, exceptions
from google.cloud.storage.retry import DEFAULT_RETRY

# Production retry policy
PRODUCTION_RETRY = retry.Retry(
    initial=1.0,           # 1 second initial delay
    maximum=60.0,          # Max 60 seconds between retries
    multiplier=2.0,        # Exponential backoff
    deadline=600.0,        # 10 minute total timeout
    predicate=retry.if_exception_type(
        exceptions.TooManyRequests,      # 429
        exceptions.InternalServerError,  # 500
        exceptions.BadGateway,           # 502
        exceptions.ServiceUnavailable,   # 503
        exceptions.GatewayTimeout,       # 504
        ConnectionError,
    ),
)

blob.upload_from_file(f, retry=PRODUCTION_RETRY, timeout=3600, checksum="crc32c")
```

**Alternatives Considered**:
- **No retries**: Too fragile for production use (network is unreliable)
- **Tenacity-only**: SDK retry is more efficient for network-level errors
- **Custom retry logic**: Reinventing the wheel; SDK's implementation is battle-tested

---

### Bucket Listing and Caching

**Decision**: Use SDK's automatic pagination with 5-minute local cache for metadata

**Rationale**:
- SDK handles pagination transparently via iterators (max 1000 results per page)
- Local caching reduces API calls and improves CLI responsiveness
- 5-minute TTL balances freshness vs. performance
- Sequential indices (1, 2, 3...) require consistent ordering (sort by timestamp)

**Implementation Pattern**:
```python
from datetime import datetime, timedelta
import json
from pathlib import Path

class BlobCache:
    def __init__(self, cache_dir: Path, ttl_minutes: int = 5):
        self.cache_dir = cache_dir
        self.ttl = timedelta(minutes=ttl_minutes)

    def get(self, bucket_name: str, prefix: str = "") -> list[dict] | None:
        cache_path = self.cache_dir / f"{bucket_name}_{prefix}.json"

        if not cache_path.exists():
            return None

        # Check if cache expired
        cache_age = datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
        if cache_age > self.ttl:
            cache_path.unlink()
            return None

        with open(cache_path) as f:
            return json.load(f)

    def set(self, bucket_name: str, blobs: list[storage.Blob], prefix: str = ""):
        cache_path = self.cache_dir / f"{bucket_name}_{prefix}.json"

        blob_data = [
            {
                "name": blob.name,
                "size": blob.size,
                "updated": blob.updated.isoformat() if blob.updated else None,
                "crc32c": blob.crc32c,
            }
            for blob in blobs
        ]

        with open(cache_path, "w") as f:
            json.dump(blob_data, f)
```

**Alternatives Considered**:
- **No caching**: Slow for frequent list operations (every command makes API call)
- **Longer TTL (>5 min)**: Risk of showing stale data after uploads
- **Database cache**: Overkill for simple metadata; JSON files are sufficient

---

### Required Dependencies

```bash
uv add google-cloud-storage  # Core GCS SDK
uv add google-crc32c          # Checksum verification
uv add tenacity               # Application-level retry (optional, for DLQ)
```

---

## 2. Retention Policies and Cleanup

### Retention Strategy

**Decision**: Combined GCS Lifecycle Management + Application-Level Enforcement

**Rationale**:
- **GCS Lifecycle Policies**: Fully automated by Google, zero operational overhead, handles age-based deletion
- **Application-Level Logic**: Required for "minimum backup count" protection (GCS doesn't support "keep N latest")
- **Two-Tier Protection**: Retention policy prevents premature deletion, lifecycle policy enforces maximum age
- **Safety Mechanism**: Always keep minimum N backups (default: 5) regardless of age

**Implementation Pattern**:
```python
from google.cloud import storage
from datetime import timedelta

def configure_retention_with_lifecycle(
    bucket_name: str,
    min_retention_days: int,
    max_age_days: int,
):
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    # Step 1: Set retention policy (minimum protection)
    bucket.retention_period = timedelta(days=min_retention_days).total_seconds()
    bucket.patch()

    # Step 2: Add lifecycle deletion rule (automatic cleanup)
    bucket.add_lifecycle_delete_rule(age=max_age_days)
    bucket.patch()
```

**Minimum Backup Count Protection** (Application-Level):
```python
def enforce_minimum_backup_count(bucket_name: str, prefix: str, min_count: int):
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    # List all backups sorted by creation time (newest first)
    blobs = sorted(
        bucket.list_blobs(prefix=prefix),
        key=lambda b: b.time_created,
        reverse=True
    )

    # Protect N most recent backups with temporary hold
    for blob in blobs[:min_count]:
        if not blob.temporary_hold:
            blob.temporary_hold = True
            blob.patch()

    # Remove hold from older backups (allows lifecycle deletion)
    for blob in blobs[min_count:]:
        if blob.temporary_hold:
            blob.temporary_hold = False
            blob.patch()
```

**Configuration Format**:
```yaml
retention:
  min_days: 30        # Minimum retention (compliance/safety)
  max_days: 90        # Maximum retention (cost optimization)
  min_count: 5        # Minimum backups to always retain
  lock_policy: false  # Lock retention policy (irreversible)
```

**Alternatives Considered**:
- **GCS Lifecycle Only**: Doesn't support "keep N latest" requirement
- **Application-Level Only**: Requires scheduled job; less reliable than GCS-managed lifecycle
- **Immutable Backup Vaults**: Too rigid for typical use cases; overkill for non-compliance scenarios

---

### Cleanup Execution Strategy

**Decision**: Scheduled Cron + GCS Lifecycle (Primary), with On-Demand CLI Command (Secondary)

**Rationale**:
- **GCS Lifecycle** runs automatically in background (fully managed, no operational burden)
- **Scheduled Cron** enforces application-level rules (minimum backup count) daily
- **On-Demand CLI** provides manual cleanup for testing and ad-hoc operations
- Separation of concerns: GCS handles age-based deletion, application handles custom logic

**Trade-offs Analysis**:

| Strategy | Pros | Cons | Use Case |
|----------|------|------|----------|
| **During Upload** | Simple, no separate job | Adds latency, may fail during upload errors | Small datasets, low frequency |
| **On-Demand CLI** | Full control, predictable | Requires manual intervention | Testing, one-time cleanup |
| **Scheduled Cron** | Fully automated, decoupled | Requires job scheduler | Production (recommended) |
| **GCS Lifecycle** | Zero overhead, highly reliable | Limited to simple rules | Age-based deletion (recommended) |

**Implementation Pattern**:
```python
# CLI command for on-demand cleanup
@app.command()
def cleanup(
    dry_run: bool = typer.Option(True, help="Preview deletions"),
    older_than: int = typer.Option(None, help="Delete backups older than N days"),
    force: bool = typer.Option(False, help="Skip confirmation"),
):
    if not dry_run and not force:
        typer.confirm("This will delete backups. Continue?", abort=True)

    executor = CleanupExecutor(config, bucket_name)
    deleted_count = executor.execute_cleanup(dry_run=dry_run)

    print(f"{'[DRY-RUN] ' if dry_run else ''}Deleted {deleted_count} backups")
```

**Alternatives Considered**:
- **Upload-Triggered Cleanup**: Adds latency to uploads; cleanup failures block uploads
- **Webhook-Triggered**: Overcomplicated for simple age-based deletion

---

### Safe Deletion Patterns

**Decision**: Use GCS Object Holds + Soft Delete (7-day recovery) + Tag-Based Protection

**Rationale**:
- **Object Holds**: Prevent accidental deletion of critical backups (reversible protection)
- **Soft Delete**: 7-day recovery window for deleted objects (no data loss risk)
- **Tag-Based Protection**: Custom metadata for categorizing backups (production, staging, critical)
- **Multiple Layers**: Defense-in-depth approach to prevent data loss

**Implementation Pattern**:
```python
from enum import Enum

class BackupTag(Enum):
    PRODUCTION = "production"  # Critical production backups
    STAGING = "staging"        # Non-critical staging backups
    CRITICAL = "critical"      # Never auto-delete

def tag_backup(blob: storage.Blob, tags: list[BackupTag]):
    blob.metadata = blob.metadata or {}
    blob.metadata["tags"] = ",".join(t.value for t in tags)

    # Apply protection based on tags
    if BackupTag.CRITICAL in tags or BackupTag.PRODUCTION in tags:
        blob.temporary_hold = True  # Prevent deletion

    blob.patch()
```

**Protection Levels**:
1. **Retention Policy**: Minimum retention period (e.g., 30 days) - cannot delete before age
2. **Object Holds**: Temporary hold prevents deletion (can be toggled manually)
3. **Soft Delete**: 7-day recovery for accidentally deleted objects
4. **Lifecycle Policy**: Automatic deletion after maximum age (e.g., 90 days)

**Alternatives Considered**:
- **Immutable Backup Vaults**: Overkill for typical use cases; permanent locks are too rigid
- **Versioning**: Adds complexity and cost; soft delete provides similar recovery capability
- **No Protection**: Too risky for disaster recovery tool

---

### Audit Logging

**Decision**: Application-Level Audit Logging (JSON Lines) + GCS Data Access Logs

**Rationale**:
- **Application-Level Logs**: Capture high-level operations (upload, download, delete) with context
- **GCS Data Access Logs**: Capture low-level API calls for compliance/forensics
- **JSON Lines Format**: Easy to parse, append-only, streaming-friendly
- **Dual Storage**: Local log file + centralized GCS bucket for durability

**Implementation Pattern**:
```python
from datetime import datetime, timezone
import json

class AuditLogger:
    def __init__(self, local_path: Path, gcs_bucket: str | None = None):
        self.local_path = local_path
        self.gcs_bucket = gcs_bucket

    def log_deletion(
        self,
        blob_name: str,
        blob_size: int,
        blob_created: datetime,
        reason: str,
        user: str,
        dry_run: bool = False,
    ):
        audit_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": "DELETE" if not dry_run else "DELETE_DRY_RUN",
            "blob_name": blob_name,
            "blob_size_bytes": blob_size,
            "blob_age_days": (datetime.now(timezone.utc) - blob_created).days,
            "reason": reason,
            "user": user,
            "dry_run": dry_run,
        }

        # Write to local audit log (JSON Lines)
        with self.local_path.open("a") as f:
            f.write(json.dumps(audit_entry) + "\n")

        # Optionally write to centralized GCS bucket
        if self.gcs_bucket:
            self._write_to_gcs(audit_entry)
```

**Retention Periods** (Compliance-Driven):
- GDPR: 5-7 years
- HIPAA: 6 years
- SOX: 7 years (2555 days)
- PCI DSS: 1 year

**Alternatives Considered**:
- **GCS Data Access Logs Only**: Not sufficient for high-level context (why was deletion triggered?)
- **Database Audit Trail**: Overkill for append-only logs; JSON Lines is simpler
- **No Audit Logging**: Fails compliance requirements and disaster recovery analysis

---

### Cost Optimization

**Decision**: Use GCS Autoclass + Gzip Compression + Regional Storage

**Rationale**:
- **Autoclass**: Automatic storage class transitions (Standard → Nearline → Coldline → Archive) based on access patterns
- **Cost Reduction**: Archive is 6% the cost of Standard ($0.0012 vs $0.020 per GB/month)
- **Gzip Compression**: 60-80% size reduction for JSON/text data (5-10x cost savings)
- **Regional Storage**: 30% cheaper than multi-regional ($0.020 vs $0.026 per GB/month)

**Implementation Pattern**:
```python
def enable_autoclass(bucket_name: str):
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    bucket.autoclass_enabled = True
    bucket.autoclass_terminal_storage_class = "ARCHIVE"
    bucket.patch()
```

**Storage Class Pricing** (US regions):
- Standard: $0.020/GB/month (frequent access)
- Nearline: $0.010/GB/month (30-day SLA)
- Coldline: $0.004/GB/month (90-day SLA)
- Archive: $0.0012/GB/month (365-day SLA) ← **94% cheaper than Standard**

**Expected Savings**:
- **Compression**: 70% reduction → $0.006/GB/month (Standard class)
- **Autoclass → Archive**: Additional 94% reduction → $0.00036/GB/month
- **Total**: ~98% cost reduction vs. uncompressed Standard storage

**Alternatives Considered**:
- **Manual Lifecycle Transitions**: More work; Autoclass is simpler and automatic
- **No Compression**: 5-10x higher costs for text-heavy Looker content
- **Multi-Regional Storage**: Unnecessary for backups; regional is sufficient and 30% cheaper

---

## 3. Interactive Terminal UI

### Library Selection

**Decision**: Use Rich (existing) + rich-menu for simple interactive selections; defer Textual for future

**Rationale**:
- **Rich** is already integrated in LookerVault for progress bars and tables
- **rich-menu** provides simple interactive menus without major dependency overhead
- **Textual** is powerful but overkill for initial MVP (defer to P3: Interactive UI)
- **Incremental adoption**: Start simple, add complexity only if needed

**Implementation Pattern**:
```python
from rich_menu import Menu
from rich.console import Console

console = Console()

def interactive_snapshot_picker(snapshots: list[dict]) -> dict | None:
    # Auto-detect if terminal supports interactivity
    if not sys.stdout.isatty():
        return None  # Fallback to non-interactive

    try:
        from rich_menu import Menu

        menu_items = [
            f"{i}. {s['name']} ({s['size_mb']} MB, {s['timestamp']})"
            for i, s in enumerate(snapshots, 1)
        ]

        menu = Menu(*menu_items)
        selection = menu.ask()

        # Parse selection index
        index = int(selection.split(".")[0]) - 1
        return snapshots[index]

    except ImportError:
        console.print("[yellow]Install rich-menu: uv add rich-menu[/yellow]")
        return None
```

**Library Comparison**:

| Library | Use Case | Complexity | Integration | Recommendation |
|---------|----------|------------|-------------|----------------|
| **Rich** | Output formatting, progress | ✅ Low | ✅ Already integrated | Use for all output |
| **rich-menu** | Simple menus | ✅ Low | ✅ Easy | Use for P1 interactive mode |
| **prompt_toolkit** | Advanced input, autocomplete | ⚠️ Medium | New dependency | Consider for future |
| **Textual** | Full TUI apps | ⚠️ High | New dependency | Defer to P3 |

**Alternatives Considered**:
- **Textual Immediately**: Too complex for MVP; can add later if users request advanced features
- **curses**: Low-level, harder to maintain; Rich ecosystem is better for Python 3.13
- **No Interactive Mode**: Misses opportunity for improved UX in P3

---

### Keyboard Navigation Patterns

**Decision**: Use standard patterns (arrow keys, Enter, Escape, /) with auto-detection and fallback

**Rationale**:
- **Standard keybindings**: Matches user expectations from fzf, kubectl, gh CLI
- **Auto-detection**: Check `sys.stdout.isatty()` to determine if interactive mode is possible
- **Graceful fallback**: Non-interactive mode for CI/CD pipelines and scripts
- **Accessibility**: Works across terminal emulators and screen sizes

**Standard Keybindings**:
```
↑/↓        Navigate list
Enter      Select/confirm
Escape/q   Cancel/quit
/          Search/filter
?          Help
g/G        Top/bottom
```

**Implementation Pattern**:
```python
import sys

def detect_interactive_mode() -> bool:
    """Detect if terminal supports interactive mode."""
    return sys.stdout.isatty()

def interactive_or_fallback(items: list[str], default: str | None = None) -> str:
    """Interactive picker with automatic fallback."""
    if detect_interactive_mode():
        # Try interactive mode
        try:
            from rich_menu import Menu
            menu = Menu(*items)
            return menu.ask()
        except ImportError:
            pass

    # Fallback to default or first item
    return default or items[0]
```

**Alternatives Considered**:
- **Force interactive mode**: Fails in CI/CD pipelines (requires `--non-interactive` flag)
- **Custom keybindings**: Confusing for users; standard patterns are better

---

### Graceful Fallback Strategy

**Decision**: Auto-detect terminal capabilities; fallback to non-interactive mode for CI/CD

**Rationale**:
- **Scriptability**: CLI tools must work in automated environments (cron, CI/CD)
- **Environment Detection**: Use `sys.stdout.isatty()` to detect if connected to terminal
- **Multiple Fallbacks**: Environment variable → command-line argument → first item
- **User Control**: Provide `--non-interactive` flag to force fallback behavior

**Implementation Pattern**:
```python
@app.command()
def list_snapshots(
    interactive: bool = typer.Option(
        None,
        "--interactive/--non-interactive",
        help="Enable/disable interactive mode (auto-detect if not specified)"
    ),
):
    """List available snapshots."""

    # Auto-detect if not specified
    if interactive is None:
        interactive = sys.stdout.isatty()

    snapshots = fetch_snapshots()

    if interactive:
        selected = interactive_picker(snapshots)
    else:
        # Non-interactive: print all snapshots
        for i, snapshot in enumerate(snapshots, 1):
            print(f"{i}. {snapshot['name']} ({snapshot['size_mb']} MB)")
```

**Alternatives Considered**:
- **Always interactive**: Breaks in CI/CD
- **Always non-interactive**: Misses UX improvement opportunity
- **Require explicit flag**: Auto-detection is more user-friendly

---

## Summary of Key Decisions

### GCS Integration
- **Authentication**: Application Default Credentials (ADC)
- **Upload**: Automatic resumable upload (>8MB) + gzip compression
- **Integrity**: CRC32C checksums for all operations
- **Retry**: SDK's DEFAULT_RETRY + optional tenacity for application-level logic
- **Caching**: 5-minute local cache for snapshot listings

### Retention & Cleanup
- **Strategy**: GCS Lifecycle Management + Application-Level Enforcement
- **Execution**: Scheduled cron (primary) + on-demand CLI (secondary)
- **Protection**: Object holds + soft delete + tag-based categorization
- **Audit**: Application-level JSON Lines logs + GCS Data Access logs
- **Cost**: Autoclass + gzip compression + regional storage

### Interactive UI
- **Library**: Rich (existing) + rich-menu (simple menus)
- **Navigation**: Standard keybindings (arrow keys, Enter, Escape)
- **Fallback**: Auto-detect terminal capabilities; graceful degradation to non-interactive

### Dependencies to Add
```bash
uv add google-cloud-storage   # GCS SDK
uv add google-crc32c           # Checksum verification
uv add rich-menu               # Interactive menus (optional)
```

---

## Next Steps (Phase 1)

1. **Data Model Design** (`data-model.md`): Define Pydantic models for SnapshotMetadata, RetentionPolicy, GCSStorageProvider
2. **API Contracts** (`contracts/`): Define CLI command interfaces and configuration schemas
3. **Quickstart Guide** (`quickstart.md`): Document common workflows (upload, list, download, restore from snapshot)
4. **Agent Context Update**: Run `.specify/scripts/bash/update-agent-context.sh` to update CLAUDE.md with new technologies
