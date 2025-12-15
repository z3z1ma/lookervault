# LookerVault

**Ever wish you could hit "Undo" on a Looker disaster? With LookerVault, you can.**

LookerVault is a production-ready CLI tool that extracts, backs up, and restores your entire Looker content (dashboards, looks, models, users, and more) to local SQLite storage. Whether you're migrating Looker instances, implementing disaster recovery, or need a safety net for your Looker content, LookerVault makes it easy.

## Current Status: Production-Ready (v0.1.0)

LookerVault is feature-complete with enterprise-grade extraction and restoration capabilities:

- ✅ **Looker Content Extraction** - Extract all content types to SQLite storage
- ✅ **Parallel Extraction** - High-throughput extraction with 8-10x speedup (400-600 items/sec)
- ✅ **Content Restoration** - Restore content with dependency ordering and parallel workers
- ✅ **Disaster Recovery** - Resume interrupted operations, Dead Letter Queue for error recovery
- ✅ **Production-Ready** - Adaptive rate limiting, checkpoint-based resume, comprehensive error handling

### Available Commands

#### Configuration & Connectivity
- `lookervault --help` - Display help information
- `lookervault --version` - Show version information
- `lookervault check` - Verify installation and configuration readiness
- `lookervault info` - Display Looker instance information and test connectivity

#### Content Extraction
- `lookervault extract` - Extract all Looker content to SQLite
- `lookervault extract --workers 8` - Parallel extraction with 8 workers (400-600 items/sec)
- `lookervault extract --resume` - Resume interrupted extraction from checkpoint
- `lookervault extract dashboards looks` - Extract specific content types
- `lookervault verify` - Verify extracted content integrity
- `lookervault list dashboards` - List extracted content

#### Content Restoration
- `lookervault restore single dashboard <id>` - Restore single dashboard (production-safe testing)
- `lookervault restore bulk dashboards` - Restore all dashboards with dependency ordering
- `lookervault restore bulk dashboards --workers 16` - Parallel restoration with 16 workers
- `lookervault restore resume` - Resume interrupted restoration from checkpoint
- `lookervault restore dlq list` - List failed restoration items
- `lookervault restore dlq retry <id>` - Retry failed restoration
- `lookervault restore status` - Show restoration session status

#### Cloud Snapshot Management
- `lookervault snapshot upload` - Upload database snapshot to Google Cloud Storage
- `lookervault snapshot list` - List available snapshots with timestamps and sizes
- `lookervault snapshot download <ref>` - Download snapshot to local machine
- `lookervault snapshot cleanup` - Delete old snapshots based on retention policy
- `lookervault restore --from-snapshot <ref>` - Restore directly from cloud snapshot

## Features

### 🚀 High-Performance Parallel Extraction

Extract large Looker instances (10,000+ items) in minutes, not hours:

- **Dynamic Work Stealing**: Workers fetch data directly from Looker API in parallel
- **Adaptive Rate Limiting**: Automatically detects and handles API rate limits across all workers
- **Resume Capability**: Checkpoint-based resumption for interrupted extractions
- **Performance**: 400-600 items/second with 8-16 workers (vs. ~50 items/sec sequential)
- **Thread-Safe SQLite**: Thread-local connections with BEGIN IMMEDIATE transactions prevent write contention

**Example**: Extract 50,000 items in ~2 minutes with 8 workers (vs. ~17 minutes sequential)

```bash
# Parallel extraction with 8 workers (default)
lookervault extract --workers 8

# High-throughput extraction (16 workers)
lookervault extract --workers 16

# Resume interrupted extraction
lookervault extract --resume
```

### 🔄 Intelligent Content Restoration

Restore Looker content with dependency-aware ordering and robust error recovery:

- **Single-Item Restoration**: Test restoration safely with individual items before bulk operations
- **Dependency-Aware Ordering**: Automatically respects dependencies (Users → Folders → Models → Dashboards → Boards)
- **Parallel Restoration**: Multi-worker restoration with shared rate limiting (100+ items/sec)
- **Smart Update/Create**: Automatically updates existing content or creates new content based on destination state
- **Dead Letter Queue**: Captures unrecoverable failures with full error context for manual review and retry
- **Checkpoint Resume**: Resume interrupted restorations from last completed item

**Example**: Restore 10,000 dashboards in ~2 minutes with 8 workers

```bash
# Test single dashboard restoration first (production-safe)
lookervault restore single dashboard abc123 --dry-run
lookervault restore single dashboard abc123

# Bulk restoration with dependency ordering
lookervault restore bulk folders --workers 8
lookervault restore bulk dashboards --workers 16

# Resume interrupted restoration
lookervault restore resume

# Review and retry failed items
lookervault restore dlq list
lookervault restore dlq retry <id>
```

### 📊 Content Types Supported

**Core Content**:
- `dashboards` - Dashboard definitions
- `looks` - Saved looks
- `folders` - Folder structure

**LookML & Models**:
- `models` - LookML models
- `explores` - Explore definitions

**Users & Permissions**:
- `users` - User accounts
- `groups` - User groups
- `roles` - Permission roles
- `permissions` - Permission sets
- `model_sets` - Model access sets

**Scheduling & Boards**:
- `boards` - Homepage boards
- `schedules` - Scheduled deliveries

### 🛡️ Production-Ready Reliability

- **Adaptive Rate Limiting**: Automatic detection and handling of HTTP 429 responses across all workers
- **Resume Capability**: Checkpoint-based resumption for both extraction and restoration
- **Dead Letter Queue**: Captures unrecoverable failures with full error context
- **Thread-Safe Operations**: Thread-local SQLite connections with proper transaction management
- **Comprehensive Error Handling**: Transient errors retried with exponential backoff (default: 5 attempts)
- **Dry Run Mode**: Validate operations without making actual changes
- **Idempotent Operations**: Safe to re-run extractions without creating duplicates (see below)

### ☁️ Cloud Snapshot Management

Upload database snapshots to Google Cloud Storage for off-site backups and disaster recovery:

- **Automated Uploads**: Upload snapshots to GCS with timestamped filenames and compression
- **Snapshot Listing**: Browse available snapshots sorted by date with sequential indices
- **Direct Restoration**: Restore Looker content directly from cloud snapshots (no manual download)
- **Retention Policies**: Automatically delete old snapshots based on age and count limits
- **Data Integrity**: CRC32C checksum verification for all uploads and downloads
- **Interactive UI**: Browse and select snapshots with keyboard navigation
- **Cost Optimization**: 70-80% file size reduction through gzip compression

**Example**: Upload, list, and restore from cloud snapshots

```bash
# Upload snapshot to GCS
lookervault snapshot upload

# List available snapshots
lookervault snapshot list

# Download snapshot to local
lookervault snapshot download 1

# Restore directly from cloud snapshot (no download needed)
lookervault restore dashboards --from-snapshot 1

# Clean up old snapshots (retention policy)
lookervault snapshot cleanup
```

#### Retention Policy Configuration

LookerVault supports automated retention policies to control storage costs by automatically deleting old snapshots. Retention policies use a two-tier approach:

1. **GCS Retention Policy**: Minimum retention period (prevents deletion before age)
2. **Application-Level Enforcement**: Maximum age and minimum count protection

**Configuration Example** (`~/.lookervault/config.toml`):

```toml
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
min_days = 30          # Minimum retention (compliance/safety)
max_days = 90          # Maximum retention (cost optimization)
min_count = 5          # Minimum backups to always retain
lock_policy = false    # Lock retention policy (irreversible)
enabled = true         # Enable retention policy enforcement

# Caching
cache_ttl_minutes = 5

# Audit Logging
audit_log_path = "~/.lookervault/audit.log"
audit_gcs_bucket = "lookervault-audit-logs"  # Optional
```

**Retention Policy Options**:

- `min_days` (integer): Minimum retention period in days (default: 30)
  - Snapshots cannot be deleted before this age
  - Enforced via GCS bucket-level retention policy
  - Protects against accidental deletion
  - Must be >= 1 day (GCS minimum)

- `max_days` (integer): Maximum retention period in days (default: 90)
  - Snapshots older than this are automatically deleted
  - Enforced via GCS Lifecycle Management
  - Must be >= `min_days`
  - Use for cost control

- `min_count` (integer): Minimum number of snapshots to always retain (default: 5)
  - Always keeps N most recent snapshots regardless of age
  - Application-level protection using GCS temporary holds
  - Set to 0 to disable minimum count protection
  - Prevents deletion of all backups

- `lock_policy` (boolean): Lock retention policy (default: false)
  - **WARNING**: Locking is IRREVERSIBLE - cannot be undone
  - Once locked, `min_days` becomes permanent (cannot be decreased)
  - Only lock for compliance scenarios (GDPR, HIPAA, SOX)
  - Leave false for typical use cases

- `enabled` (boolean): Enable retention policy enforcement (default: true)
  - Set to false to disable automatic cleanup
  - Snapshots accumulate without limit when disabled
  - Can be toggled without affecting existing snapshots

**Environment Variables**:

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

**Common Retention Patterns**:

**1. Daily Backups with 90-Day Retention** (Recommended):
```toml
[snapshot.retention]
min_days = 7           # Keep minimum 7 days
max_days = 90          # Delete after 90 days
min_count = 14         # Always keep 14 most recent (2 weeks)
enabled = true
```

**2. Weekly Backups with 1-Year Retention**:
```toml
[snapshot.retention]
min_days = 30          # Keep minimum 30 days
max_days = 365         # Delete after 1 year
min_count = 12         # Always keep 12 most recent (~3 months)
enabled = true
```

**3. Compliance Mode (GDPR 7-Year Retention)**:
```toml
[snapshot.retention]
min_days = 2555        # 7 years (GDPR/SOX compliance)
max_days = 2555        # Same as min_days (no automatic deletion)
min_count = 0          # No minimum count protection needed
lock_policy = false    # Only lock if required by auditors
enabled = true
```

**4. Development/Testing (No Retention)**:
```toml
[snapshot.retention]
enabled = false        # Disable retention policy
```

**Cost Optimization with Retention Policies**:

- **Autoclass**: Automatically transitions snapshots to cheaper storage classes (Archive is 94% cheaper than Standard)
- **Compression**: Gzip reduces file size by 70-80% (5-10x cost savings)
- **Retention Limits**: `max_days = 90` prevents runaway storage costs
- **Minimum Count Protection**: `min_count = 5` ensures disaster recovery capability

**Expected Storage Costs** (US regions):
- **Without optimization**: $0.020/GB/month (Standard, uncompressed)
- **With compression (70% reduction)**: $0.006/GB/month
- **With Autoclass → Archive (94% reduction)**: $0.00036/GB/month
- **Total savings**: ~98% cost reduction vs. uncompressed Standard storage

**See**: [specs/005-cloud-snapshot-storage/quickstart.md](specs/005-cloud-snapshot-storage/quickstart.md) for detailed workflows and best practices

#### Snapshot Workflow Examples

**Retention Policy Cleanup**:
```bash
# Preview cleanup (dry-run - default behavior)
lookervault snapshot cleanup

# Expected output:
# [DRY-RUN] Retention Policy Cleanup Preview
# Snapshots to protect (5 most recent): 5 snapshots
# Snapshots to delete (older than 90 days): 2 snapshots
#   ✗ looker-2025-09-10T14-30-00.db.gz (95 days old, 98.2 MB)
#   ✗ looker-2025-09-05T14-30-00.db.gz (100 days old, 97.8 MB)
# [DRY-RUN] Would delete 2 snapshots, saving 196.0 MB.

# Execute cleanup (requires --no-dry-run and --force)
lookervault snapshot cleanup --no-dry-run --force

# Automate daily cleanup (cron job at 3 AM)
# Add to crontab: 0 3 * * * cd /path/to/lookervault && lookervault snapshot cleanup --no-dry-run --force
```

**Download with Filtering**:
```bash
# List snapshots with filters
lookervault snapshot list --limit 10                    # Show 10 most recent
lookervault snapshot list --filter "2025-12"            # December 2025 snapshots
lookervault snapshot list --filter "last-7-days"        # Last week
lookervault snapshot list --verbose                     # Detailed metadata

# Download to custom location
lookervault snapshot download 1 --output /backups/looker-recovery.db

# Overwrite existing file
lookervault snapshot download 1 --output looker.db --overwrite

# Filter by name pattern and download
lookervault snapshot list --filter "2025-12-13" | jq '.snapshots[0].sequential_index' | xargs lookervault snapshot download
```

**Restore from Specific Snapshot**:
```bash
# Restore from snapshot by sequential index
lookervault restore dashboards --from-snapshot 1         # Most recent
lookervault restore dashboards --from-snapshot 5         # 5th most recent

# Restore from snapshot with timestamp reference
lookervault snapshot list --filter "2025-12-13T14-30"   # Find snapshot index
lookervault restore dashboards --from-snapshot 3         # Use index from list

# Restore multiple content types from snapshot
lookervault restore dashboards looks folders --from-snapshot 3

# Dry-run first to preview restoration
lookervault restore dashboards --from-snapshot 3 --dry-run

# Full restoration workflow from cloud snapshot
lookervault snapshot list                                # 1. List available snapshots
lookervault snapshot download 7 --output /tmp/test.db    # 2. Download for testing
lookervault restore dashboards --from-snapshot 7 --dry-run  # 3. Test restore
lookervault restore dashboards --from-snapshot 7         # 4. Execute restore
```

**Daily Backup Automation**:
```bash
# Create automated backup script (~/bin/lookervault-daily-backup.sh)
#!/bin/bash
set -euo pipefail
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
cd /path/to/lookervault
lookervault extract --workers 8
lookervault snapshot upload --json > /tmp/upload-result.json
echo "$(date): Backup complete" >> /var/log/lookervault-backup.log

# Make executable and add to crontab (daily at 2 AM)
# chmod +x ~/bin/lookervault-daily-backup.sh
# crontab -e
# 0 2 * * * /home/user/bin/lookervault-daily-backup.sh
```

### 📝 YAML Export/Import Workflow

Modify Looker content in bulk using human-editable YAML files with the `unpack` and `pack` commands. Edit dashboards, looks, and other content through simple text manipulation.

#### Key Features
- **Full and Folder Strategies**: Export content organized by type or folder hierarchy
- **Bulk Modifications**: Edit YAML files with standard text tools (sed, grep, Python)
- **Complete Validation**: Check modifications before restoration
- **Checkpoint-Based**: Resume interrupted pack/unpack operations
- **Dry Run Mode**: Validate without making changes

#### Workflow: Extract → Unpack → Modify → Pack → Restore

```bash
# 1. Extract content to SQLite database
lookervault extract --workers 8 dashboards looks

# 2. Unpack to YAML files (full strategy)
lookervault unpack --output-dir export/ --strategy full

# 3. Modify YAML files (multiple approaches)
# A. Bash: Update filter using sed
sed -i 's/model: old_model/model: new_model/g' export/dashboards/*.yaml

# B. Python: Complex transformations
python scripts/update_dashboards.py export/dashboards/

# C. Text Editor: Manual edits
# Open export/dashboards/ and modify files directly

# 4. Pack modified YAML back to database
lookervault pack --input-dir export/ --db-path modified.db

# 5. Restore to Looker
lookervault restore bulk dashboards --workers 8
```

#### Bulk Modification Examples

**1. Update Dashboard Model References**
```bash
# Replace model references across all dashboards
sed -i 's/model: "old_sales_model"/model: "new_sales_model"/g' export/dashboards/*.yaml
```

**2. Update Titles with Python**
```python
# update_titles.py
import yaml
from pathlib import Path

def update_dashboard_titles(export_dir):
    for yaml_file in Path(export_dir).glob("dashboards/*.yaml"):
        with open(yaml_file, 'r') as f:
            dashboard = yaml.safe_load(f)

        # Add prefix to all dashboard titles
        dashboard['title'] = f"[Updated] {dashboard['title']}"

        with open(yaml_file, 'w') as f:
            yaml.safe_dump(dashboard, f)

update_dashboard_titles("export/")
```

**3. Filter Transformations**
```python
# update_filters.py
import yaml
from pathlib import Path

def update_dashboard_filters(export_dir):
    for yaml_file in Path(export_dir).glob("dashboards/*.yaml"):
        with open(yaml_file, 'r') as f:
            dashboard = yaml.safe_load(f)

        for element in dashboard.get('dashboard_elements', []):
            query = element.get('query', {})
            filters = query.get('filters', {})

            # Update time-based filters
            if filters.get('date') == '30 days':
                filters['date'] = '90 days'

        with open(yaml_file, 'w') as f:
            yaml.safe_dump(dashboard, f)

update_dashboard_filters("export/")
```

#### Unpack/Pack Command Options

**Unpack Command**:
```bash
# Full strategy: content by type
lookervault unpack --output-dir export/ --strategy full

# Folder strategy: mirror Looker folder hierarchy
lookervault unpack --output-dir export/ --strategy folder

# Specific content types
lookervault unpack --content-types dashboards,looks

# Dry run (validate without unpacking)
lookervault unpack --dry-run

# Verbose output
lookervault unpack --verbose
```

**Pack Command**:
```bash
# Pack modified YAML back to database
lookervault pack --input-dir export/ --db-path modified.db

# Dry run (validate without changes)
lookervault pack --dry-run

# Force mode (delete items for missing YAML)
lookervault pack --force

# Verbose output
lookervault pack --verbose
```

**See**: [YAML Export/Import Documentation](CLAUDE.md#yaml-export-import-006-yaml-export-import) for complete details.

## Installation

### Prerequisites

- Python 3.13 or later
- Access to a Looker instance with API credentials
- Read permissions in Looker for content extraction
- Write permissions for content restoration (if restoring)

### Install from Source

```bash
# Clone the repository
git clone https://github.com/yourusername/lookervault.git
cd lookervault

# Create virtual environment with uv
uv venv

# Activate virtual environment
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in development mode
uv sync --all-extras --dev
```

### Verify Installation

```bash
# Check version
lookervault --version

# Verify connectivity
lookervault check
```

## Configuration

### 1. Create Configuration File

Create `~/.lookervault/config.toml`:

```toml
[lookervault]
config_version = "1.0"

[lookervault.looker]
api_url = "https://your-looker-instance.com:19999"
client_id = ""  # Set via LOOKERVAULT_CLIENT_ID env var
client_secret = ""  # Set via LOOKERVAULT_CLIENT_SECRET env var
timeout = 30
verify_ssl = true

[lookervault.output]
default_format = "table"  # or "json"
color_enabled = true
```

See `tests/fixtures/sample_config.toml` for a complete example.

### 2. Set Environment Variables

```bash
export LOOKERVAULT_CLIENT_ID="your_client_id"
export LOOKERVAULT_CLIENT_SECRET="your_client_secret"
```

For permanent configuration, add these to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.).

### 3. Configure Cloud Snapshot Storage (Optional)

To use cloud snapshot features (upload, list, download snapshots), configure Google Cloud Storage access:

#### A. Create GCS Bucket

```bash
# Create bucket for snapshot storage
gcloud storage buckets create gs://lookervault-backups \
  --location=us-central1 \
  --uniform-bucket-level-access

# Enable Autoclass for cost optimization (optional)
gcloud storage buckets update gs://lookervault-backups --autoclass
```

#### B. Set Up Service Account

```bash
# Create service account
gcloud iam service-accounts create lookervault-snapshots \
  --display-name="LookerVault Snapshot Manager"

# Grant Storage Admin role for the bucket
gcloud storage buckets add-iam-policy-binding gs://lookervault-backups \
  --member="serviceAccount:lookervault-snapshots@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.admin"

# Create and download service account key
gcloud iam service-accounts keys create ~/lookervault-sa-key.json \
  --iam-account=lookervault-snapshots@PROJECT_ID.iam.gserviceaccount.com
```

**Important**: Replace `PROJECT_ID` with your actual GCP project ID.

#### C. Configure Credentials

**Option 1: Environment Variable (Recommended for production)**
```bash
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/lookervault-sa-key.json"
```

**Option 2: Application Default Credentials (Development)**
```bash
gcloud auth application-default login
```

#### D. Update Configuration File

Add GCS settings to `~/.lookervault/config.toml`:

```toml
[lookervault.snapshot]
bucket_name = "lookervault-backups"
project_id = "my-gcp-project"      # Optional, auto-detected from credentials
region = "us-central1"
prefix = "snapshots/"              # Optional subdirectory in bucket
filename_prefix = "looker"

[lookervault.snapshot.retention]
enabled = true
min_days = 30      # Minimum age before deletion
max_days = 90      # Automatically delete snapshots older than this
min_count = 5      # Always keep this many recent snapshots
```

#### E. Verify Setup

```bash
# Test GCS access
lookervault snapshot list

# Upload a snapshot
lookervault snapshot upload
```

**For detailed setup instructions, troubleshooting, and best practices**, see [Cloud Snapshot Management Quickstart](specs/005-cloud-snapshot-storage/quickstart.md).

## Quick Start Guide

### 1. Verify Connection

```bash
# Check configuration and connectivity
lookervault check

# View instance information
lookervault info
```

### 2. Extract Content

```bash
# Extract all content types (parallel, 8 workers)
lookervault extract --workers 8

# Extract specific content types
lookervault extract dashboards looks --workers 8

# Resume interrupted extraction
lookervault extract --resume

# Verify extracted content
lookervault verify

# List extracted dashboards
lookervault list dashboards
```

### 3. Restore Content

```bash
# Test single dashboard restoration (production-safe)
lookervault restore single dashboard abc123 --dry-run
lookervault restore single dashboard abc123

# Bulk restoration with dependency ordering
lookervault restore bulk folders --workers 8
lookervault restore bulk dashboards --workers 16

# Resume interrupted restoration
lookervault restore resume

# Check for failures
lookervault restore dlq list

# Retry failed item
lookervault restore dlq retry <dlq_id>
```

## Usage Examples

### Content Extraction Workflows

#### Basic Extraction
```bash
# Sequential extraction (backward compatible)
lookervault extract --workers 1

# Parallel extraction with 8 workers (default)
lookervault extract --workers 8

# High-throughput extraction
lookervault extract --workers 16 --rate-limit-per-minute 120
```

#### Resume Interrupted Extraction
```bash
# If extraction was interrupted (Ctrl+C, network failure, etc.)
lookervault extract --resume

# Output:
# ℹ Found incomplete extraction from 2025-12-13 10:30:15
# ℹ Resuming from checkpoint: dashboards (offset 500/1000)
# ⠋ Extracting dashboards... ████████████░░░░░░░░ 750/1000 (75%)
```

#### Extract Specific Content Types
```bash
# Extract only dashboards and looks
lookervault extract dashboards looks --workers 8

# Extract only user-related content
lookervault extract users groups roles --workers 4
```

### Folder-Level Filtering
```bash
# Extract dashboards from specific folder(s)
lookervault extract dashboards --folder-ids "123,456" --workers 8

# Recursive folder extraction (includes all subfolders)
lookervault extract dashboards --folder-ids "789" --recursive --workers 8

# Restore dashboards to specific folder(s)
lookervault restore bulk dashboards --folder-ids "123,456" --workers 8

# Recursive folder restoration
lookervault restore bulk dashboards --folder-ids "789" --recursive --workers 8
```

#### Folder Filtering Notes
- **Supported Content Types**: Currently, only dashboards and looks support native folder-level SDK filtering
- **Performance**: Folder filtering uses SDK-level filtering for dashboards and looks, resulting in faster extraction
- **Other Content Types**: User, group, role, and other content types are fetched fully and filtered in-memory
- **Recursive Option**: `--recursive` includes all child folders and their contents
- **Multiple Folders**: Specify multiple folder IDs separated by commas

#### JSON Output for Automation
```bash
# Machine-readable JSON output
lookervault extract --output json --workers 8

# Output (structured JSON events):
# {"event":"extraction_started","timestamp":"2025-12-13T10:30:00Z","workers":8}
# {"event":"extraction_progress","content_type":"dashboards","completed":500,"total":1000}
# {"event":"extraction_complete","total_items":10500,"duration_seconds":135.4}
```

### Content Restoration Workflows

#### Production Testing (Single-Item Restoration)
```bash
# Test with dry run first
lookervault restore single dashboard abc123 --dry-run

# Expected output:
# ✓ Found in backup: "Sales Dashboard"
# ✓ Checking destination...
#   → Dashboard exists (ID: abc123)
#   → Will UPDATE existing dashboard
# ✓ Dry run complete (no changes made)

# If successful, restore for real
lookervault restore single dashboard abc123
```

#### Bulk Restoration with Dependencies
```bash
# Restore in dependency order
# Users → Groups → Folders → Models → Dashboards → Boards

# 1. Restore users and groups (dependencies for ownership)
lookervault restore bulk users --workers 8
lookervault restore bulk groups --workers 8

# 2. Restore folders (dependencies for content location)
lookervault restore bulk folders --workers 8

# 3. Restore content (dashboards, looks)
lookervault restore bulk looks --workers 16
lookervault restore bulk dashboards --workers 16

# 4. Check for failures
lookervault restore dlq list
```

#### Resume Interrupted Restoration
```bash
# Restoration interrupted after 5,000 of 10,000 dashboards
# Ctrl+C or network failure

# Resume from last checkpoint
lookervault restore resume dashboards

# System skips already-completed items and continues from item 5,001
```

#### Dead Letter Queue Management
```bash
# List all failed items
lookervault restore dlq list

# List failed items for specific session
lookervault restore dlq list --session-id <session_id>

# Show error details for specific item
lookervault restore dlq show <dlq_id>

# Retry single failed item
lookervault restore dlq retry <dlq_id>

# Clear DLQ entries for session
lookervault restore dlq clear --session-id <session_id> --force
```

#### Restoration Session Status
```bash
# Show latest restoration session
lookervault restore status

# Show specific session
lookervault restore status --session-id <session_id>

# List all sessions
lookervault restore status --all
```

### Performance Tuning

#### Optimal Extraction Performance
```bash
# Default (good balance): 8 workers
lookervault extract --workers 8

# High throughput: 16 workers (SQLite write limit)
lookervault extract --workers 16

# Memory-constrained: reduce workers and batch size
lookervault extract --workers 4 --batch-size 50
```

#### Optimal Restoration Performance
```bash
# Default (good balance): 8 workers
lookervault restore bulk dashboards --workers 8

# High throughput: 16 workers
lookervault restore bulk dashboards --workers 16

# Conservative (avoid rate limits): 4 workers, lower rate limits
lookervault restore bulk dashboards --workers 4 --rate-limit-per-minute 60
```

## Performance Characteristics

### Extraction Performance
- **Sequential (1 worker)**: ~50 items/second
- **8 workers**: ~400 items/second (8x speedup)
- **16 workers**: ~600 items/second (12x speedup)
- **Large Datasets**: 50,000 items in ~2 minutes with 8 workers (vs. ~17 minutes sequential)

### Restoration Performance
- **Single-Item**: <10 seconds including dependency validation
- **Bulk (8 workers)**: 100+ items/second (API-bound, scales with worker count)
- **Large Datasets**: 50,000 items in <10 minutes with 8 workers (~83 items/sec minimum)
- **Resume Overhead**: Minimal - checkpoint queries use indexed lookups


## Idempotent Operations (Upsert Behavior)

LookerVault uses **idempotent write operations** for all SQLite database writes, making it safe to re-run extraction commands without creating duplicates or corrupting data.

### What is Upsert?

**Upsert** = "Update or Insert" - SQLite's `INSERT ... ON CONFLICT DO UPDATE` pattern that:
- Inserts new records if they don't exist
- Updates existing records if they already exist (based on unique constraints)
- Prevents duplicate records and database conflicts

### Why This Matters

You can safely:
- **Re-run extractions** without worrying about duplicates
- **Resume interrupted operations** from any point
- **Run parallel workers** without coordination overhead
- **Recover from errors** by simply re-running the command

### How It Works

All SQLite write operations use the `ON CONFLICT` clause:

```sql
INSERT INTO content_items (
    id, content_type, name, owner_id, owner_email,
    created_at, updated_at, synced_at, deleted_at,
    content_size, content_data, folder_id
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(id) DO UPDATE SET
    content_type = excluded.content_type,
    name = excluded.name,
    owner_id = excluded.owner_id,
    -- ... all other fields updated ...
```

**Key Points**:
- **Unique Constraint**: Each table has unique constraints on natural keys (e.g., `id` for content_items)
- **Conflict Detection**: SQLite detects when INSERT would violate unique constraint
- **Update Behavior**: On conflict, existing record is updated with new values
- **Atomicity**: Operation is atomic - no partial updates or race conditions

### What Operations Are Idempotent?

All write operations in LookerVault are idempotent:

1. **Content Extraction** (`save_content()`):
   - Unique key: `id` (Looker content ID)
   - Re-running extraction updates existing content instead of creating duplicates

2. **Checkpoint Saves** (`save_checkpoint()`):
   - Unique key: `(session_id, content_type, started_at)`
   - Re-saving same checkpoint updates progress counters

3. **Extraction Sessions** (`create_extraction_session()`):
   - Unique key: `id` (session ID)
   - Re-creating session with same ID updates session metadata

4. **Dead Letter Queue** (`save_to_dlq()`):
   - Unique key: `(session_id, content_id, content_type, retry_count)`
   - Same failure at same retry count updates error details (deduplication)

5. **ID Mappings** (`save_id_mapping()`):
   - Unique key: `(source_instance, content_type, source_id)`
   - Re-mapping same ID updates destination_id

6. **Restoration Checkpoints** (`save_restoration_checkpoint()`):
   - Unique key: `(session_id, content_type, started_at)`
   - Re-saving checkpoint updates restoration progress

7. **Restoration Sessions** (`create_restoration_session()`):
   - Unique key: `id` (session ID)
   - Re-creating session updates session metadata

### Practical Examples

#### Safe Re-run After Interruption

```bash
# Extraction interrupted after 5,000 of 10,000 dashboards
# Ctrl+C or network failure

# Simply re-run the extraction
lookervault extract dashboards --workers 8

# What happens:
# - First 5,000 dashboards: UPDATED (ON CONFLICT DO UPDATE)
# - Next 5,000 dashboards: INSERTED (no conflict)
# - Result: Complete dataset with no duplicates
```

#### Safe Parallel Extraction

```bash
# Multiple workers extracting simultaneously
lookervault extract dashboards --workers 16

# What happens:
# - Worker 1 extracts dashboards 0-100
# - Worker 2 extracts dashboards 100-200
# - If ranges overlap (e.g., due to resume), upsert prevents duplicates
# - Result: Each dashboard appears exactly once in database
```

#### Safe Resume from Checkpoint

```bash
# Extraction interrupted during "dashboards" content type
lookervault extract --resume

# What happens:
# - System loads checkpoint (e.g., "dashboards at offset 5000")
# - Re-extracts from beginning (offset 0) for "dashboards"
# - Upsert updates first 5,000 records (already extracted)
# - Inserts remaining records (5,001-10,000)
# - Result: Complete, deduplicated dataset
```

### Performance Impact

Upsert operations have minimal performance overhead:

- **Same Performance**: INSERT and UPDATE have similar performance in SQLite
- **No Extra Queries**: Single SQL statement (no SELECT + INSERT/UPDATE)
- **Index Optimization**: Unique constraints use B-tree indexes for fast conflict detection
- **Batch Commits**: Multiple upserts grouped in single transaction for efficiency

**Measured Impact**: <1% overhead vs. plain INSERT for typical content extraction workloads

### Technical Implementation

**Database Schema** (from `storage/schema.py`):
- All tables have unique constraints on natural keys
- Unique constraints added in schema version 2 (migration v001_add_unique_constraints)
- Enables idempotent upsert operations across all tables

**Repository Pattern** (from `storage/repository.py`):
- All write methods use `INSERT ... ON CONFLICT DO UPDATE`
- Docstrings document upsert behavior for clarity
- Tests validate idempotency (`tests/test_repository_upsert.py`)

**Thread Safety**:
- Thread-local connections prevent race conditions
- BEGIN IMMEDIATE transactions acquire write lock immediately
- SQLITE_BUSY retry logic with exponential backoff handles contention

### Testing

Comprehensive test suite validates upsert behavior:

```bash
# Run upsert-specific tests
uv run pytest tests/test_repository_upsert.py -v

# Tests verify:
# - Re-saving same content updates (not duplicates)
# - Primary keys remain consistent across upserts
# - All fields update correctly on conflict
# - Natural unique keys work as expected
```

### When Upsert Happens

**Automatic** (you don't need to do anything special):
- Re-running `lookervault extract` on same database
- Resume operations (`--resume` flag)
- Parallel workers processing overlapping ranges
- Checkpoint saves during extraction/restoration

**What Gets Updated**:
- All content fields (name, owner, timestamps, content_data, etc.)
- Progress counters (items_completed, items_failed in checkpoints)
- Session metadata (completed_at, error_message in sessions)
- Error details (stack_trace, failed_at in DLQ)

**What Stays the Same**:
- Primary keys (id field)
- Unique constraint fields (natural keys)
- Database row IDs (SQLite ROWID)

### FAQ

**Q: What if I want to start fresh instead of upsert?**

A: Delete the database file and re-run extraction:

```bash
rm looker.db
lookervault extract --workers 8
```

**Q: Will upsert overwrite my manual database changes?**

A: Yes. Re-running extraction updates all fields with latest values from Looker API. Manual changes will be lost.

**Q: Can I disable upsert behavior?**

A: No. Upsert is built into the database schema and repository pattern. It's a core design principle for reliability.

**Q: What happens if unique constraints change between runs?**

A: Schema migrations handle constraint changes safely. Existing data is preserved during migration.

**Q: How do I verify no duplicates exist?**

A: Query the database directly:

```bash
sqlite3 looker.db "SELECT id, COUNT(*) FROM content_items GROUP BY id HAVING COUNT(*) > 1"
# Empty result = no duplicates (expected)
```

## Development

### Running Tests

```bash
# Run all tests with coverage
uv run pytest tests/ -v --cov

# Run only unit tests
uv run pytest tests/unit/

# Run only integration tests
uv run pytest tests/integration/
```

### Code Quality

This project uses modern Rust-based tools for code quality:

```bash
# Format code
uvx ruff format

# Lint and auto-fix issues
uvx ruff check --fix

# Type check
uvx ty check

# Run all pre-commit checks
uvx ruff format && uvx ruff check --fix && uvx ty check && uv run pytest
```

**CRITICAL**: No changes should be committed without running ALL checks above. All checks must pass before committing.

### Development Workflow

```bash
# 1. Create virtual environment
uv venv

# 2. Sync dependencies
uv sync --all-extras --dev

# 3. Make changes to code

# 4. Run code quality checks
uvx ruff format
uvx ruff check --fix
uvx ty check

# 5. Run tests
uv run pytest

# 6. Commit changes (all checks must pass)
```

### Adding Dependencies

**IMPORTANT**: This project uses `uv` for all Python package management operations.

```bash
# Add production dependency
uv add <package>

# Add development dependency
uv add --dev <package>

# Update lockfile
uv lock

# Sync environment with lockfile
uv sync
```

**DO NOT** use `pip install`, `pip freeze`, `virtualenv`, `poetry`, or similar tools.

**DO NOT** manually edit `[project]`, `[project.optional-dependencies]`, `[project.scripts]`, or `[build-system]` in pyproject.toml.

### Project Structure

```
src/lookervault/
├── cli/                          # CLI commands and output formatting
│   ├── commands/                 # Individual command implementations
│   │   ├── extract.py            # Content extraction commands
│   │   ├── restore.py            # Content restoration commands
│   │   ├── check.py              # Connectivity checks
│   │   └── info.py               # Instance information
│   ├── main.py                   # Typer app definition
│   └── output.py                 # Output formatting utilities
├── config/                       # Configuration management
│   ├── models.py                 # Pydantic data models
│   ├── loader.py                 # Config file loading
│   └── validator.py              # Readiness checks
├── looker/                       # Looker SDK integration
│   ├── client.py                 # SDK wrapper
│   ├── connection.py             # Connection testing
│   └── extractor.py              # Content extraction logic
├── storage/                      # SQLite storage layer
│   ├── repository.py             # Thread-safe repository with retry logic
│   ├── schema.py                 # Database schema definitions
│   └── models.py                 # Storage data models
├── extraction/                   # Parallel extraction engine
│   ├── parallel_orchestrator.py  # Main parallel extraction engine
│   ├── offset_coordinator.py     # Thread-safe offset range coordinator
│   ├── work_queue.py             # Thread-safe work distribution
│   ├── metrics.py                # Thread-safe metrics aggregation
│   ├── rate_limiter.py           # Adaptive rate limiting
│   └── performance.py            # Performance tuning utilities
└── restoration/                  # Content restoration engine
    ├── restorer.py               # Single-item restoration logic
    ├── parallel_orchestrator.py  # Multi-worker restoration coordinator
    ├── deserializer.py           # Binary blob to SDK object deserialization
    ├── dead_letter_queue.py      # Failed item capture and retry
    └── dependency_graph.py       # Dependency order relationships
```

## Configuration Options

### Extraction Configuration

**Command-line options**:
- `--workers N` - Number of parallel workers (default: 8, max: 50)
- `--batch-size N` - Items per batch (default: 100)
- `--rate-limit-per-minute N` - API rate limit (default: 120 req/min)
- `--rate-limit-per-second N` - Burst rate limit (default: 10 req/sec)
- `--resume` - Resume interrupted extraction from checkpoint
- `--output json|table` - Output format (default: table)
- `--folder-ids ID1,ID2,...` - Extract content from specific folder(s)
- `--recursive` - Include all subfolders when using `--folder-ids`
  - **Note**: Only works for dashboards and looks
  - Other content types will filter in-memory

### Restoration Configuration

**Command-line options**:
- `--workers N` - Number of parallel workers (default: 8, max: 50)
- `--rate-limit-per-minute N` - API rate limit (default: 120 req/min)
- `--rate-limit-per-second N` - Burst rate limit (default: 10 req/sec)
- `--checkpoint-interval N` - Save checkpoint every N items (default: 100)
- `--max-retries N` - Max retry attempts for transient errors (default: 5)
- `--dry-run` - Validate without making changes
- `--json` - JSON output for scripting
- `--folder-ids ID1,ID2,...` - Restore content to specific folder(s)
- `--recursive` - Include all subfolders when using `--folder-ids`
  - **Note**: Defaults to specific folder replacement
  - Useful for targeted content restoration

### Environment Variables

```bash
# Looker API credentials (required)
export LOOKERVAULT_CLIENT_ID="your_client_id"
export LOOKERVAULT_CLIENT_SECRET="your_client_secret"

# Optional configuration
export LOOKERVAULT_API_URL="https://your-looker-instance.com:19999"
export LOOKERVAULT_DB_PATH="./looker.db"
export LOOKERVAULT_CONFIG="/path/to/config.toml"
export LOOKERVAULT_TIMEOUT="300"  # 5 minutes for large instances
```

## Troubleshooting

### Rate Limit Errors (HTTP 429)

**Symptom**: `WARNING: Rate limit hit, will retry in 30 seconds`

**Solution**: Adaptive rate limiting handles this automatically. If persistent:

```bash
# Reduce rate limits
lookervault extract --workers 8 --rate-limit-per-minute 60 --rate-limit-per-second 5

# Or reduce worker count
lookervault extract --workers 4
```

### Memory Issues

**Symptom**: `MemoryError` or high memory usage

**Solution**:

```bash
# Reduce batch size and worker count
lookervault extract --workers 4 --batch-size 50

# Extract content types individually
lookervault extract dashboards --workers 8
lookervault extract looks --workers 8
```

### SQLite Write Contention

**Symptom**: `SQLITE_BUSY` errors or warnings about worker count

**Solution**: These are automatically retried with exponential backoff. If persistent:

```bash
# Reduce worker count (16 is SQLite write limit)
lookervault extract --workers 8
lookervault restore bulk dashboards --workers 8
```

### Connection Errors

**Symptom**: `ConnectionError: Unable to connect to Looker`

**Solution**:

1. Verify credentials: `lookervault check`
2. Check network/VPN connection
3. Verify Looker instance is accessible
4. Check API credentials haven't expired
5. Increase timeout for large instances:

```bash
export LOOKERVAULT_TIMEOUT=300  # 5 minutes
lookervault extract
```

### Resume Not Working

**Symptom**: `--resume` flag doesn't resume from checkpoint

**Solution**:

```bash
# Verify checkpoint exists
lookervault restore status --all

# If checkpoint corrupted, delete session and restart
rm looker.db  # Only if you want to start fresh
lookervault extract --workers 8
```

### YAML Validation Errors

**Symptom**: `lookervault pack` fails with validation errors when importing modified YAML files

#### Invalid YAML Syntax

**Error Message**:
```
ValidationError: Invalid YAML syntax in export/dashboards/abc123.yaml: mapping values are not allowed here
```

**Causes**:
- Missing quotes around strings with special characters
- Incorrect indentation (YAML requires consistent 2-space indentation)
- Unescaped colons or other special characters
- Mixed tabs and spaces

**Solution**:
```bash
# Validate YAML syntax before packing
python3 -c "import yaml; yaml.safe_load(open('export/dashboards/abc123.yaml'))"

# Common fixes:
# 1. Add quotes around strings with colons
title: "Sales: Regional Analysis"  # Correct
title: Sales: Regional Analysis    # Incorrect

# 2. Fix indentation (use 2 spaces, not tabs)
elements:
  - id: "elem1"      # Correct (2-space indent)
    title: "Revenue"

# 3. Escape special characters
description: "Q1 results (updated)"  # Use quotes for parentheses
```

#### Missing Required Fields

**Error Message**:
```
[Structure] DASHBOARD missing required 'elements' field
[Structure] LOOK missing required 'query' field
```

**Causes**:
- Accidentally deleted required fields during modification
- Incorrect YAML structure after bulk edits

**Solution**:
```bash
# Check which fields are required for each content type:
# DASHBOARD: id, title, elements
# LOOK: id, title, query

# Example: Restore missing 'elements' field
elements:
  - id: "elem1"
    title: "Element Title"
    query:
      model: "sales"
      view: "transactions"
      fields: ["transactions.total_revenue"]

# Use --dry-run to validate before packing
lookervault pack --input-dir export/ --dry-run
```

#### Query Structure Errors

**Error Message**:
```
[Query] Missing required query fields: model, view in dashboards/456.yaml:15
[Query] Query validation failed in looks/789.yaml: 'fields' must be a list
```

**Causes**:
- Missing required query fields (`model`, `view`, `fields`)
- Incorrect data types (e.g., `fields` must be a list, not a string)
- Invalid Looker SDK query structure

**Solution**:
```bash
# Correct query structure (required fields):
query:
  model: "sales"              # Required: LookML model name
  view: "transactions"        # Required: View name
  fields:                     # Required: List of fields
    - "transactions.date"
    - "transactions.total_revenue"
  filters:                    # Optional: Filter definitions
    "transactions.date": "30 days"
  sorts:                      # Optional: Sort order
    - "transactions.date desc"

# Common mistakes:
# 1. Missing required fields
query:
  model: "sales"
  # Missing 'view' and 'fields' - will fail

# 2. Wrong data type for fields
query:
  fields: "transactions.revenue"  # Incorrect: must be a list
  fields: ["transactions.revenue"]  # Correct

# Validate with --dry-run
lookervault pack --input-dir export/ --dry-run
```

#### Field-Level Validation Errors

**Error Message**:
```
[Field] Field 'title' cannot be empty in dashboards/123.yaml:5
[Field] Field 'title' exceeds 255 characters in dashboards/456.yaml:8
[Field] Dashboard filters must be a dictionary, got list in dashboards/789.yaml:12
```

**Causes**:
- Empty or whitespace-only titles
- Title exceeds maximum length (255 characters)
- Incorrect data types for fields

**Solution**:
```bash
# 1. Fix empty titles
title: ""                    # Incorrect: empty string
title: "Sales Dashboard"     # Correct

# 2. Shorten long titles
title: "This is a very long dashboard title that exceeds the 255 character limit..."  # Too long
title: "Sales Dashboard - Q1 2025"  # Under 255 characters

# 3. Fix incorrect data types
filters:                     # Correct: dictionary
  "date": "30 days"
  "region": "US"

filters:                     # Incorrect: list
  - "date: 30 days"

# Use --verbose for detailed error locations
lookervault pack --input-dir export/ --dry-run --verbose
```

#### Checksum Mismatches

**Error Message**:
```
WARNING: Export checksum mismatch detected
Expected: sha256:abc123...
Computed: sha256:def456...
```

**Causes**:
- YAML files were modified after export
- Files were added/removed from export directory
- Manual edits to `metadata.json`

**Solution**:
```bash
# This is a WARNING, not an error - pack will continue
# Checksum mismatch indicates modifications were made (expected behavior)

# If you see this unexpectedly:
# 1. Verify no accidental changes to YAML files
# 2. Check if files were added/deleted
# 3. Review metadata.json integrity

# To proceed with intentional modifications:
lookervault pack --input-dir export/  # Pack will continue despite warning

# To validate all modifications before packing:
lookervault pack --input-dir export/ --dry-run --verbose
```

#### Validation Best Practices

1. **Always use `--dry-run` first**:
```bash
lookervault pack --input-dir export/ --dry-run
```

2. **Use `--verbose` for detailed error locations**:
```bash
lookervault pack --input-dir export/ --dry-run --verbose
```

3. **Test modifications on a small subset first**:
```bash
# Extract single dashboard
lookervault extract dashboards --folder-ids "123" --workers 1

# Unpack and modify
lookervault unpack --output-dir test_export/
# [Modify YAML files]

# Validate with dry-run
lookervault pack --input-dir test_export/ --dry-run

# If successful, apply to full dataset
```

4. **Validate YAML syntax before packing**:
```bash
# Python validation script
python3 << 'EOF'
import yaml
from pathlib import Path

for yaml_file in Path("export/dashboards").glob("*.yaml"):
    try:
        with open(yaml_file) as f:
            yaml.safe_load(f)
        print(f"✓ {yaml_file.name}")
    except Exception as e:
        print(f"✗ {yaml_file.name}: {e}")
EOF
```

5. **Keep backups before bulk modifications**:
```bash
# Create snapshot before modifications
lookervault snapshot upload --name "pre-modification"

# Make modifications
# [Edit YAML files]

# Pack and restore
lookervault pack --input-dir export/
lookervault restore bulk dashboards --workers 8

# If issues occur, restore from snapshot
lookervault snapshot download 1
```

## Roadmap

### Current Features (v0.1.0)
- ✅ CLI baseline with Looker connectivity
- ✅ Content extraction (all types)
- ✅ Parallel extraction (8-10x speedup)
- ✅ Content restoration with dependency ordering
- ✅ Parallel restoration with DLQ and error recovery
- ✅ Resume capability for extraction and restoration
- ✅ Dead Letter Queue for failed items

### Recent Features (v0.2.0)
- ✅ **Cloud Snapshot Storage**: Upload database snapshots to Google Cloud Storage
- ✅ **Snapshot Management**: List, download, and restore from cloud snapshots
- ✅ **Automated Retention**: Delete old snapshots based on retention policies
- ✅ **Interactive UI**: Browse and select snapshots with keyboard navigation

### Future Features (Not Yet Implemented)

- 🔄 **Cross-Instance Migration**: Restore content to different Looker instance with ID remapping
- 🔍 **Content Diff**: Compare backups and show changes between versions
- 📈 **Incremental Extraction**: Extract only changed content since last backup
- 🔐 **Encryption**: Encrypt SQLite database at rest
- 🔍 **Content Search**: Full-text search across extracted content
- 📤 **Content Export**: Export content to JSON, YAML, or other formats

See the project roadmap for detailed feature planning.

## Exit Codes

LookerVault uses standard exit codes:

- `0` - Success
- `1` - General error
- `2` - Configuration error
- `3` - Connection error
- `130` - Interrupted by user (Ctrl+C)

## Contributing

Contributions are welcome! Please see CONTRIBUTING.md for guidelines.

## License

See LICENSE file for details.

## Support

- Report issues: [GitHub Issues](https://github.com/yourusername/lookervault/issues)
- Documentation: [Wiki](https://github.com/yourusername/lookervault/wiki)
- Quickstart Guides: See `specs/*/quickstart.md` for detailed implementation guides
