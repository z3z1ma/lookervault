# CLI Interface Contract: Looker Content Restoration

**Feature**: 004-looker-restoration
**Date**: 2025-12-13
**Status**: Complete

## Overview

This document defines the CLI interface for Looker content restoration commands. All commands follow the existing `lookervault` CLI patterns using typer.

---

## Command Structure

```
lookervault restore <subcommand> [arguments] [options]
```

---

## Subcommands

### 1. `restore single` - Single Item Restoration (P1 - MVP)

Restore a single content item by type and ID.

```bash
lookervault restore single <content-type> <content-id> [options]
```

**Arguments:**
- `content-type` (required): Content type to restore
  - Choices: `dashboard`, `look`, `folder`, `user`, `group`, `role`, `board`, `scheduled_plan`, `lookml_model`, `permission_set`, `model_set`
- `content-id` (required): ID of the content item to restore

**Options:**
- `--db-path PATH`: Path to SQLite backup database (default: `./lookervault.db`)
- `--dry-run`: Validate and show what would be restored without making changes (default: `false`)
- `--force`: Skip confirmation prompts (default: `false`)
- `--json`: Output results in JSON format (default: `false`)

**Examples:**
```bash
# Restore single dashboard (interactive confirmation)
lookervault restore single dashboard 42

# Dry run to test restoration
lookervault restore single dashboard 42 --dry-run

# Force restore without confirmation
lookervault restore single look 123 --force --db-path /backups/looker.db

# JSON output for automation
lookervault restore single folder 5 --json
```

**Output (Human-Readable):**
```
Restoring Dashboard ID: 42
✓ Found in backup: "Sales Analytics Dashboard"
✓ Checking destination instance...
  → Dashboard exists in destination (ID: 42)
  → Will UPDATE existing dashboard
✓ Validating dependencies...
  → Folder ID 5 exists ✓
  → Look ID 789 exists ✓
✓ Restoration successful!
  Destination ID: 42
  Duration: 2.3s
```

**Output (JSON):**
```json
{
  "status": "success",
  "content_type": "dashboard",
  "content_id": "42",
  "operation": "update",
  "destination_id": "42",
  "duration_ms": 2300,
  "dependencies_checked": ["folder:5", "look:789"]
}
```

**Exit Codes:**
- `0`: Success
- `1`: General error
- `2`: Content not found in backup
- `3`: Validation error
- `4`: API error (rate limit, authentication, etc.)

---

### 2. `restore bulk` - Bulk Type Restoration (P2)

Restore all content of a specific type.

```bash
lookervault restore bulk <content-type> [options]
```

**Arguments:**
- `content-type` (required): Content type to restore (same choices as `single`)

**Options:**
- `--db-path PATH`: Path to SQLite backup database
- `--workers N`: Number of parallel workers (default: `8`, range: `1-32`)
- `--rate-limit-per-minute N`: API rate limit per minute (default: `120`)
- `--rate-limit-per-second N`: Burst rate limit per second (default: `10`)
- `--checkpoint-interval N`: Save checkpoint every N items (default: `100`)
- `--max-retries N`: Maximum retry attempts for transient errors (default: `5`)
- `--skip-if-modified`: Skip items modified in destination since backup (default: `false`)
- `--dry-run`: Validate without making changes (default: `false`)
- `--json`: Output results in JSON format (default: `false`)

**Examples:**
```bash
# Restore all dashboards with 8 workers
lookervault restore bulk dashboard

# High-throughput restore with 16 workers
lookervault restore bulk dashboard --workers 16

# Conservative restore with lower rate limits
lookervault restore bulk look --rate-limit-per-minute 60 --rate-limit-per-second 5

# Dry run to see what would be restored
lookervault restore bulk folder --dry-run
```

**Output (Human-Readable with Progress):**
```
Restoring all dashboards...
✓ Found 1,234 dashboards in backup
✓ Destination instance connected

Progress: ████████████████░░░░ 80% (987/1234)
  Success: 950 created, 37 updated
  Errors: 0
  Throughput: 120 items/sec
  Elapsed: 8.2s | ETA: 2.1s

✓ Restoration complete!
  Total: 1,234 items
  Success: 1,200 (97.2%)
  Created: 950
  Updated: 250
  Failed: 34 (moved to dead letter queue)
  Duration: 10.3s
  Average throughput: 119.8 items/sec
```

**Output (JSON):**
```json
{
  "status": "completed",
  "content_type": "dashboard",
  "summary": {
    "total_items": 1234,
    "success_count": 1200,
    "created_count": 950,
    "updated_count": 250,
    "error_count": 34,
    "skipped_count": 0,
    "duration_seconds": 10.3,
    "average_throughput": 119.8
  },
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Exit Codes:**
- `0`: All items succeeded
- `1`: Some items failed (but moved to DLQ gracefully)
- `2`: Fatal error (session aborted)

---

### 3. `restore all` - Full Restoration (P2)

Restore all content types in dependency order.

```bash
lookervault restore all [options]
```

**Arguments:** (none)

**Options:** (same as `bulk` plus:)
- `--exclude-types TYPE [TYPE ...]`: Exclude specific content types
- `--only-types TYPE [TYPE ...]`: Restore only specified types

**Examples:**
```bash
# Restore everything
lookervault restore all

# Restore everything except scheduled plans
lookervault restore all --exclude-types scheduled_plan

# Restore only users, groups, and roles
lookervault restore all --only-types user group role

# Full restore with custom configuration
lookervault restore all --workers 12 --rate-limit-per-minute 180
```

**Output (Human-Readable):**
```
Restoring all content types in dependency order...

[1/9] Users...
  ✓ 150 users restored (8.2s, 18.3 items/sec)

[2/9] Groups...
  ✓ 45 groups restored (2.1s, 21.4 items/sec)

[3/9] Roles...
  ✓ 12 roles restored (0.9s, 13.3 items/sec)

[4/9] Folders...
  ✓ 200 folders restored (15.3s, 13.1 items/sec)

[5/9] LookML Models...
  ✓ 8 models restored (1.2s, 6.7 items/sec)

[6/9] Looks...
  ✓ 500 looks restored (42.5s, 11.8 items/sec)

[7/9] Dashboards...
  ✓ 1,234 dashboards restored (95.2s, 13.0 items/sec)

[8/9] Boards...
  ✓ 25 boards restored (1.8s, 13.9 items/sec)

[9/9] Scheduled Plans...
  ✓ 67 scheduled plans restored (5.4s, 12.4 items/sec)

✓ Full restoration complete!
  Total: 2,241 items
  Success: 2,200 (98.2%)
  Failed: 41 (moved to dead letter queue)
  Total Duration: 3m 52s
```

---

### 4. `restore resume` - Resume Interrupted Restoration (P2)

Resume a previously interrupted restoration session.

```bash
lookervault restore resume [session-id] [options]
```

**Arguments:**
- `session-id` (optional): Specific session ID to resume (defaults to most recent incomplete session)

**Options:**
- `--db-path PATH`: Path to SQLite backup database
- (All other options from `bulk` apply)

**Examples:**
```bash
# Resume most recent incomplete session
lookervault restore resume

# Resume specific session
lookervault restore resume 550e8400-e29b-41d4-a716-446655440000

# Resume with different worker count
lookervault restore resume --workers 4
```

**Output:**
```
Resuming restoration session: 550e8400-e29b-41d4-a716-446655440000
✓ Found incomplete checkpoint
  Content Type: dashboards
  Completed: 500/1,234 items
  Remaining: 734 items

Progress: ████████████████████ 100% (1234/1234)
  Success: 1,200 (950 new, 250 resumed)
  Errors: 34
  Throughput: 125 items/sec

✓ Restoration resumed and completed!
```

---

### 5. `restore dlq` - Dead Letter Queue Management

Manage failed restoration items.

#### 5.1 `restore dlq list` - List DLQ Entries

```bash
lookervault restore dlq list [options]
```

**Options:**
- `--session-id ID`: Filter by session ID
- `--content-type TYPE`: Filter by content type
- `--limit N`: Maximum entries to show (default: `100`)
- `--offset N`: Pagination offset (default: `0`)
- `--json`: Output in JSON format

**Examples:**
```bash
# List all DLQ entries
lookervault restore dlq list

# List DLQ entries for specific session
lookervault restore dlq list --session-id 550e8400...

# List only dashboard failures
lookervault restore dlq list --content-type dashboard

# JSON output for automation
lookervault restore dlq list --json --limit 1000
```

**Output:**
```
Dead Letter Queue Entries (34 total)

ID    Content Type    Content ID    Error Type          Failed At           Retries
----  --------------  ------------  ------------------  ------------------  -------
1     dashboard       42            ValidationError     2025-12-13 10:30    5
2     look            123           DependencyError     2025-12-13 10:31    3
3     folder          5             ConflictError       2025-12-13 10:32    5
...
```

#### 5.2 `restore dlq show` - Show DLQ Entry Details

```bash
lookervault restore dlq show <dlq-id>
```

**Arguments:**
- `dlq-id` (required): DLQ entry ID

**Examples:**
```bash
# Show full error details
lookervault restore dlq show 1
```

**Output:**
```
DLQ Entry #1

Content Type: dashboard
Content ID: 42
Session ID: 550e8400-e29b-41d4-a716-446655440000

Error Details:
  Type: ValidationError
  Message: Invalid folder_id: folder 999 does not exist in destination
  Retries: 5/5
  Failed At: 2025-12-13 10:30:15

Stack Trace:
  File "restoration/restorer.py", line 123, in restore_item
    result = self.client.sdk.update_dashboard(...)
  looker_sdk.error.SDKError: 422 Unprocessable Entity
  ...

Content Preview:
  Title: "Sales Analytics Dashboard"
  Folder ID: 999
  Owner ID: 42
```

#### 5.3 `restore dlq retry` - Retry DLQ Entry

```bash
lookervault restore dlq retry <dlq-id> [options]
```

**Arguments:**
- `dlq-id` (required): DLQ entry ID to retry

**Options:**
- `--fix-dependencies`: Attempt to auto-fix dependency errors (e.g., create missing folders)
- `--force`: Retry even if error type is not typically retryable
- `--json`: Output in JSON format

**Examples:**
```bash
# Retry single DLQ entry
lookervault restore dlq retry 1

# Retry with dependency auto-fix
lookervault restore dlq retry 1 --fix-dependencies
```

**Output:**
```
Retrying DLQ Entry #1 (Dashboard ID: 42)...
✓ Retry successful!
  Destination ID: 42
  Removed from dead letter queue
```

#### 5.4 `restore dlq clear` - Clear DLQ Entries

```bash
lookervault restore dlq clear [options]
```

**Options:**
- `--session-id ID`: Clear only entries for specific session
- `--content-type TYPE`: Clear only entries for specific type
- `--all`: Clear all entries (requires confirmation)
- `--force`: Skip confirmation

**Examples:**
```bash
# Clear DLQ entries for specific session
lookervault restore dlq clear --session-id 550e8400...

# Clear all DLQ entries (with confirmation)
lookervault restore dlq clear --all

# Force clear without confirmation
lookervault restore dlq clear --all --force
```

---

### 6. `restore status` - Show Restoration Status

Show status of restoration sessions.

```bash
lookervault restore status [session-id] [options]
```

**Arguments:**
- `session-id` (optional): Specific session ID (defaults to most recent)

**Options:**
- `--all`: Show all sessions
- `--json`: Output in JSON format

**Examples:**
```bash
# Show most recent session status
lookervault restore status

# Show specific session
lookervault restore status 550e8400...

# List all sessions
lookervault restore status --all
```

**Output:**
```
Restoration Session: 550e8400-e29b-41d4-a716-446655440000

Status: completed
Started: 2025-12-13 10:00:00
Completed: 2025-12-13 10:10:30
Duration: 10m 30s

Source Instance: https://looker-backup.company.com
Destination Instance: https://looker.company.com

Progress:
  Total Items: 2,241
  Success: 2,200 (98.2%)
    Created: 1,800
    Updated: 400
  Failed: 41 (in DLQ)
  Average Throughput: 3.6 items/sec

By Content Type:
  Users: 150/150 (100%)
  Groups: 45/45 (100%)
  Roles: 12/12 (100%)
  Folders: 200/200 (100%)
  Models: 8/8 (100%)
  Looks: 489/500 (97.8%) - 11 failed
  Dashboards: 1,204/1,234 (97.6%) - 30 failed
  Boards: 25/25 (100%)
  Scheduled Plans: 67/67 (100%)
```

---

## Global Options

Available for all `restore` subcommands:

- `--verbose` / `-v`: Enable verbose logging
- `--quiet` / `-q`: Suppress non-essential output
- `--help` / `-h`: Show help message

---

## Environment Variables

- `LOOKERVAULT_DB_PATH`: Default database path
- `LOOKER_BASE_URL`: Destination Looker instance URL
- `LOOKER_CLIENT_ID`: Looker API client ID
- `LOOKER_CLIENT_SECRET`: Looker API client secret

---

## Configuration File Support

Optionally load defaults from `lookervault.toml`:

```toml
[restore]
workers = 8
rate_limit_per_minute = 120
rate_limit_per_second = 10
checkpoint_interval = 100
max_retries = 5

[restore.filters]
exclude_types = ["scheduled_plan"]
```

---

## Error Handling

All commands follow consistent error handling:

1. **Validation errors**: Exit early with code 3, show clear error message
2. **API errors**: Retry with backoff, move to DLQ if exhausted, exit code 4
3. **User cancellation**: Ctrl+C handled gracefully, checkpoint saved, exit code 130
4. **Fatal errors**: Session aborted, detailed error logged, exit code 2

---

## Progress Display

Real-time progress for bulk operations uses Rich library:

```
Restoring Dashboards ██████████████████░░ 80% (987/1234)
Success: 950 • Errors: 0 • Throughput: 120 items/sec • ETA: 2.1s
```

Progress updates every 100ms, showing:
- Progress bar with percentage
- Current / total items
- Success / error counts
- Current throughput (items/sec)
- Estimated time to completion (ETA)

---

## Summary

The CLI interface provides:

1. **Granular testing**: `single` for P1 production safety
2. **Flexible bulk restore**: `bulk` per-type, `all` for full restore
3. **Resume capability**: `resume` leverages checkpoints
4. **Error management**: `dlq` commands for reviewing/retrying failures
5. **Status tracking**: `status` for monitoring progress
6. **Consistent UX**: Follows existing `lookervault extract` patterns
7. **Automation-friendly**: JSON output, exit codes, env var support

All commands are implemented using typer with rich progress displays, matching the existing lookervault CLI experience.
