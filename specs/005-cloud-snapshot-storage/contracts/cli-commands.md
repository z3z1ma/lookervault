# CLI Commands Contract: Cloud Snapshot Management

**Feature**: 005-cloud-snapshot-storage
**Date**: 2025-12-13

## Overview

This document defines the CLI command interface for snapshot management in LookerVault. All commands follow the existing Typer-based CLI patterns with consistent flag naming and output formatting.

---

## Command Group: `snapshot`

All snapshot-related commands are grouped under the `snapshot` command group:

```bash
lookervault snapshot <subcommand> [OPTIONS] [ARGUMENTS]
```

---

## Commands

### 1. `lookervault snapshot upload`

Upload local database snapshot to Google Cloud Storage.

**Syntax**:
```bash
lookervault snapshot upload [OPTIONS]
```

**Options**:
- `--source PATH` - Path to local database file (default: `./looker.db`)
- `--compress / --no-compress` - Enable/disable gzip compression (default: `--compress`)
- `--compression-level INT` - Gzip compression level 1-9 (default: 6)
- `--dry-run` - Preview upload without executing (default: False)
- `--json` - Output results as JSON (default: False)

**Examples**:
```bash
# Upload current looker.db with default settings
lookervault snapshot upload

# Upload specific file with maximum compression
lookervault snapshot upload --source /path/to/backup.db --compression-level 9

# Preview upload (dry run)
lookervault snapshot upload --dry-run

# Upload with JSON output (for scripting)
lookervault snapshot upload --json
```

**Output (Human-Readable)**:
```
Compressing looker.db... ━━━━━━━━━━━━━━━━━━━━━━ 100% 00:05
Uploading looker-2025-12-13T14-30-00.db.gz... ━━━━━━━━━━━━━━━━━━━━━━ 100% 00:25

✓ Upload complete!
  Snapshot: looker-2025-12-13T14-30-00.db.gz
  Size: 104,857,600 bytes (100.0 MB)
  Compressed: 70% reduction
  CRC32C: AAAAAA==
  Location: gs://lookervault-backups/snapshots/looker-2025-12-13T14-30-00.db.gz
```

**Output (JSON)**:
```json
{
  "success": true,
  "snapshot": {
    "filename": "looker-2025-12-13T14-30-00.db.gz",
    "timestamp": "2025-12-13T14:30:00Z",
    "size_bytes": 104857600,
    "size_mb": 100.0,
    "crc32c": "AAAAAA==",
    "gcs_path": "gs://lookervault-backups/snapshots/looker-2025-12-13T14-30-00.db.gz",
    "compression_ratio": 0.30
  }
}
```

**Exit Codes**:
- `0` - Upload successful
- `1` - Upload failed (network error, authentication error, etc.)
- `2` - Validation error (invalid source path, configuration error)

---

### 2. `lookervault snapshot list`

List available snapshots in Google Cloud Storage.

**Syntax**:
```bash
lookervault snapshot list [OPTIONS]
```

**Options**:
- `--limit INT` - Maximum number of snapshots to display (default: all)
- `--filter TEXT` - Filter snapshots by date range (e.g., "last-7-days", "last-30-days", "2025-12")
- `--verbose` - Show detailed metadata (size, CRC32C, tags, etc.)
- `--json` - Output results as JSON (default: False)
- `--no-cache` - Skip local cache, fetch fresh data from GCS (default: False)

**Examples**:
```bash
# List all snapshots (uses cache if available)
lookervault snapshot list

# List 10 most recent snapshots
lookervault snapshot list --limit 10

# List snapshots from December 2025
lookervault snapshot list --filter "2025-12"

# List with detailed metadata
lookervault snapshot list --verbose

# List with JSON output (for scripting)
lookervault snapshot list --json
```

**Output (Human-Readable)**:
```
Available Snapshots (10)

 Index │ Filename                              │ Timestamp           │ Size (MB) │ Age
═══════╪═══════════════════════════════════════╪═════════════════════╪═══════════╪════════
 1     │ looker-2025-12-13T14-30-00.db.gz      │ 2025-12-13 14:30:00 │ 100.0     │ 2 hours
 2     │ looker-2025-12-13T10-00-00.db.gz      │ 2025-12-13 10:00:00 │ 98.5      │ 6 hours
 3     │ looker-2025-12-12T14-30-00.db.gz      │ 2025-12-12 14:30:00 │ 99.2      │ 1 day
...

Use index number to download or restore (e.g., lookervault snapshot download 1)
```

**Output (Verbose)**:
```
Snapshot 1 of 10
─────────────────────────────────────────────────────────
  Filename:   looker-2025-12-13T14-30-00.db.gz
  Timestamp:  2025-12-13 14:30:00 UTC
  Size:       100.0 MB (104,857,600 bytes)
  CRC32C:     AAAAAA==
  Encoding:   gzip
  Tags:       production
  Location:   gs://lookervault-backups/snapshots/looker-2025-12-13T14-30-00.db.gz
  Created:    2025-12-13 14:32:15 UTC
  Updated:    2025-12-13 14:32:15 UTC
  Age:        2 hours
```

**Output (JSON)**:
```json
{
  "total_count": 10,
  "snapshots": [
    {
      "sequential_index": 1,
      "filename": "looker-2025-12-13T14-30-00.db.gz",
      "timestamp": "2025-12-13T14:30:00Z",
      "size_bytes": 104857600,
      "size_mb": 100.0,
      "crc32c": "AAAAAA==",
      "gcs_path": "gs://lookervault-backups/snapshots/looker-2025-12-13T14-30-00.db.gz",
      "content_encoding": "gzip",
      "tags": ["production"],
      "created": "2025-12-13T14:32:15Z",
      "updated": "2025-12-13T14:32:15Z",
      "age_days": 0
    }
  ]
}
```

**Exit Codes**:
- `0` - List successful
- `1` - List failed (network error, authentication error, etc.)
- `2` - No snapshots found

---

### 3. `lookervault snapshot download`

Download snapshot from Google Cloud Storage to local file.

**Syntax**:
```bash
lookervault snapshot download <SNAPSHOT_REF> [OPTIONS]
```

**Arguments**:
- `SNAPSHOT_REF` - Snapshot reference: sequential index (1, 2, 3...) OR timestamp (2025-12-13T14-30-00)

**Options**:
- `--output PATH` - Output path for downloaded file (default: `./looker.db`)
- `--overwrite / --no-overwrite` - Overwrite existing file without confirmation (default: `--no-overwrite`)
- `--verify-checksum / --no-verify-checksum` - Verify CRC32C checksum after download (default: `--verify-checksum`)
- `--json` - Output results as JSON (default: False)

**Examples**:
```bash
# Download snapshot #1 (most recent)
lookervault snapshot download 1

# Download by timestamp
lookervault snapshot download 2025-12-13T14-30-00

# Download to specific path
lookervault snapshot download 1 --output /path/to/backup.db

# Download and overwrite without confirmation
lookervault snapshot download 1 --overwrite

# Download with JSON output
lookervault snapshot download 1 --json
```

**Output (Human-Readable)**:
```
Downloading looker-2025-12-13T14-30-00.db.gz... ━━━━━━━━━━━━━━━━━━━━━━ 100% 00:20
Verifying checksum... ✓ CRC32C: AAAAAA==
Decompressing... ✓

✓ Download complete!
  Snapshot: looker-2025-12-13T14-30-00.db.gz
  Downloaded to: ./looker.db
  Size: 350.0 MB (decompressed)
  Verified: CRC32C checksum match
```

**Output (JSON)**:
```json
{
  "success": true,
  "snapshot": {
    "filename": "looker-2025-12-13T14-30-00.db.gz",
    "timestamp": "2025-12-13T14:30:00Z"
  },
  "local_path": "./looker.db",
  "size_bytes": 367001600,
  "checksum_verified": true
}
```

**Exit Codes**:
- `0` - Download successful
- `1` - Download failed (network error, checksum mismatch, etc.)
- `2` - Validation error (invalid snapshot reference, file already exists)

---

### 4. `lookervault snapshot delete`

Delete snapshot from Google Cloud Storage.

**Syntax**:
```bash
lookervault snapshot delete <SNAPSHOT_REF> [OPTIONS]
```

**Arguments**:
- `SNAPSHOT_REF` - Snapshot reference: sequential index (1, 2, 3...) OR timestamp (2025-12-13T14-30-00)

**Options**:
- `--force` - Skip confirmation prompt (default: False)
- `--dry-run` - Preview deletion without executing (default: False)
- `--json` - Output results as JSON (default: False)

**Examples**:
```bash
# Delete snapshot #5 (with confirmation)
lookervault snapshot delete 5

# Delete without confirmation
lookervault snapshot delete 5 --force

# Preview deletion (dry run)
lookervault snapshot delete 5 --dry-run

# Delete with JSON output
lookervault snapshot delete 5 --force --json
```

**Output (Human-Readable)**:
```
⚠ Warning: This will permanently delete the following snapshot:

  Filename:  looker-2025-12-10T10-00-00.db.gz
  Timestamp: 2025-12-10 10:00:00 UTC
  Size:      98.5 MB
  Age:       3 days

Are you sure you want to delete this snapshot? (y/N): y

Deleting looker-2025-12-10T10-00-00.db.gz...

✓ Snapshot deleted successfully.
  Note: Soft delete enabled. Recovery possible for 7 days via GCS console.
```

**Exit Codes**:
- `0` - Deletion successful
- `1` - Deletion failed (protected snapshot, network error, etc.)
- `2` - Validation error (invalid snapshot reference, user cancelled)

---

### 5. `lookervault snapshot cleanup`

Clean up old snapshots based on retention policy.

**Syntax**:
```bash
lookervault snapshot cleanup [OPTIONS]
```

**Options**:
- `--dry-run` - Preview cleanup without executing (default: True)
- `--force` - Execute cleanup without confirmation (default: False)
- `--older-than INT` - Override retention policy: delete snapshots older than N days
- `--json` - Output results as JSON (default: False)

**Examples**:
```bash
# Preview cleanup (dry run, default)
lookervault snapshot cleanup

# Execute cleanup (with confirmation)
lookervault snapshot cleanup --no-dry-run

# Execute cleanup without confirmation
lookervault snapshot cleanup --no-dry-run --force

# Delete snapshots older than 60 days (override retention policy)
lookervault snapshot cleanup --older-than 60 --no-dry-run --force

# Cleanup with JSON output
lookervault snapshot cleanup --json
```

**Output (Human-Readable)**:
```
[DRY-RUN] Retention Policy Cleanup Preview

Retention Policy:
  Minimum retention: 30 days
  Maximum retention: 90 days
  Minimum count: 5 snapshots

Snapshots to protect (5 most recent):
  1. looker-2025-12-13T14-30-00.db.gz (2 hours old)
  2. looker-2025-12-13T10-00-00.db.gz (6 hours old)
  3. looker-2025-12-12T14-30-00.db.gz (1 day old)
  4. looker-2025-12-11T14-30-00.db.gz (2 days old)
  5. looker-2025-12-10T14-30-00.db.gz (3 days old)

Snapshots to delete (2 snapshots older than 90 days):
  ✗ looker-2025-09-10T14-30-00.db.gz (95 days old, 98.2 MB)
  ✗ looker-2025-09-05T14-30-00.db.gz (100 days old, 97.8 MB)

[DRY-RUN] Would delete 2 snapshots, saving 196.0 MB.
Run with --no-dry-run to execute cleanup.
```

**Exit Codes**:
- `0` - Cleanup successful (or dry-run preview)
- `1` - Cleanup failed (network error, etc.)
- `2` - Validation error (invalid configuration)

---

## Modified Command: `lookervault restore`

Add `--from-snapshot` flag to existing restore commands.

**Syntax**:
```bash
lookervault restore [CONTENT_TYPES...] [OPTIONS]
```

**New Options**:
- `--from-snapshot TEXT` - Restore from cloud snapshot: sequential index (1, 2, 3...) OR timestamp (2025-12-13T14-30-00)

**Examples**:
```bash
# Restore all content types from snapshot #3
lookervault restore --from-snapshot 3

# Restore dashboards and looks from snapshot by timestamp
lookervault restore dashboards looks --from-snapshot 2025-12-13T14-30-00

# Restore from snapshot with dry-run
lookervault restore --from-snapshot 1 --dry-run

# Restore from snapshot with 16 workers
lookervault restore --from-snapshot 2 --workers 16
```

**Behavior**:
1. Download snapshot to temporary location (`/tmp/lookervault-snapshot-{timestamp}.db`)
2. Perform restoration using existing restoration logic
3. Clean up temporary snapshot file after completion (success or failure)
4. All existing restore flags work with `--from-snapshot` (dry-run, workers, rate limits, etc.)

**Output**:
```
Fetching snapshot metadata... ✓
Downloading snapshot looker-2025-12-13T14-30-00.db.gz to temporary location...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 00:20

Verifying checksum... ✓ CRC32C: AAAAAA==

Starting restoration from snapshot...

[... existing restore output ...]

✓ Restoration complete!
Cleaning up temporary snapshot file...
```

---

## Global Options

All snapshot commands support these global options (inherited from main CLI):

- `--config PATH` - Path to lookervault.toml config file (default: `./lookervault.toml`)
- `--verbose / --no-verbose` - Enable verbose logging (default: `--no-verbose`)
- `--help` - Show help message and exit

---

## Configuration File Integration

Commands read configuration from `lookervault.toml`:

```toml
[snapshot]
bucket_name = "lookervault-backups"
project_id = "my-gcp-project"
region = "us-central1"
prefix = "snapshots/"
filename_prefix = "looker"
compression_enabled = true
compression_level = 6

[snapshot.retention]
min_days = 30
max_days = 90
min_count = 5
enabled = true
```

Configuration precedence (highest to lowest):
1. Command-line flags
2. Environment variables
3. lookervault.toml file
4. Default values

---

## Error Handling

All commands follow consistent error handling patterns:

**Network Errors**:
```
✗ Error: Failed to connect to Google Cloud Storage
  Network error: Connection timeout after 30s

  Troubleshooting:
  - Check internet connection
  - Verify GCS bucket exists: gs://lookervault-backups
  - Check firewall settings
```

**Authentication Errors**:
```
✗ Error: Authentication failed
  No valid credentials found.

  Solutions:
  1. Set GOOGLE_APPLICATION_CREDENTIALS environment variable:
     export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"

  2. Run gcloud auth application-default login

  3. Configure service account in lookervault.toml
```

**Validation Errors**:
```
✗ Error: Invalid snapshot reference
  Snapshot "2025-12-13T14-99-00" not found.

  Available snapshots: run "lookervault snapshot list"
```

**Checksum Mismatch**:
```
✗ Error: Checksum verification failed
  Downloaded file is corrupted.
  Expected CRC32C: AAAAAA==
  Actual CRC32C:   BBBBBB==

  Downloaded file has been deleted.
  Please retry the download.
```

---

## Interactive Mode (P3 - Future Enhancement)

Add `--interactive` flag to snapshot commands for terminal UI:

```bash
# Interactive snapshot picker
lookervault snapshot download --interactive

# Interactive restore from snapshot
lookervault restore --interactive --from-snapshot
```

**Interactive UI Features**:
- Arrow key navigation
- Real-time search/filter
- Preview panel showing snapshot metadata
- Confirmation prompts with Escape to cancel

**Fallback**: Auto-detect terminal capabilities; fall back to non-interactive if not supported.

---

## Exit Code Summary

| Code | Meaning | Examples |
|------|---------|----------|
| 0 | Success | Operation completed successfully |
| 1 | Runtime error | Network failure, API error, checksum mismatch |
| 2 | Validation error | Invalid arguments, configuration error, user cancelled |
| 3 | Not found | Snapshot not found, bucket doesn't exist |

---

## Contract Compliance

✅ **CLI-First Interface** (Constitution Principle II):
- All operations accessible via CLI commands
- Scriptable with `--json` output
- Consistent flag naming and exit codes
- No required user interaction (except confirmation prompts with `--force` override)

✅ **Machine-Parseable Output**:
- `--json` flag for automation
- Consistent JSON schema across commands
- Exit codes follow standard conventions

✅ **Error Messages**:
- Clear, actionable error messages
- Troubleshooting steps provided
- Errors go to stderr, results to stdout
