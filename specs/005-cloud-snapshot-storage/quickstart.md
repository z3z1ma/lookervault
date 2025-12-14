# Quickstart Guide: Cloud Snapshot Management

**Feature**: 005-cloud-snapshot-storage
**Date**: 2025-12-13
**For**: End users, administrators, DevOps engineers

## Overview

This quickstart guide provides step-by-step instructions for common snapshot management workflows in LookerVault. Learn how to upload database snapshots to Google Cloud Storage, list available backups, download snapshots for local use, and restore Looker content directly from cloud storage.

---

## Prerequisites

Before using snapshot management features:

1. **Google Cloud Storage Access**
   - GCS bucket created (e.g., `lookervault-backups`)
   - Valid GCP credentials with Storage Admin role
   - `GOOGLE_APPLICATION_CREDENTIALS` environment variable set OR `gcloud auth application-default login` completed

2. **LookerVault Installation**
   - LookerVault CLI installed (`uv add lookervault`)
   - Configuration file (`lookervault.toml`) created

3. **Existing Database**
   - Local `looker.db` file from previous extraction

---

## Quick Start (5 Minutes)

### 1. Configure Snapshot Management

Create or edit `lookervault.toml`:

```toml
[snapshot]
bucket_name = "lookervault-backups"
project_id = "my-gcp-project"      # Optional, auto-detected from credentials
region = "us-central1"
prefix = "snapshots/"
filename_prefix = "looker"

[snapshot.retention]
min_days = 30
max_days = 90
min_count = 5
```

**Set GCS credentials**:
```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
```

### 2. Upload Your First Snapshot

```bash
# Upload current looker.db to cloud storage
lookervault snapshot upload
```

**Output**:
```
Compressing looker.db... ━━━━━━━━━━━━━━━━━━━━━━ 100% 00:05
Uploading looker-2025-12-13T14-30-00.db.gz... ━━━━━━━━━━━━━━━━━━━━━━ 100% 00:25

✓ Upload complete!
  Snapshot: looker-2025-12-13T14-30-00.db.gz
  Size: 104,857,600 bytes (100.0 MB)
  Compressed: 70% reduction
  Location: gs://lookervault-backups/snapshots/looker-2025-12-13T14-30-00.db.gz
```

### 3. List Available Snapshots

```bash
# View all snapshots
lookervault snapshot list
```

**Output**:
```
Available Snapshots (3)

 Index │ Filename                              │ Timestamp           │ Size (MB) │ Age
═══════╪═══════════════════════════════════════╪═════════════════════╪═══════════╪════════
 1     │ looker-2025-12-13T14-30-00.db.gz      │ 2025-12-13 14:30:00 │ 100.0     │ 2 hours
 2     │ looker-2025-12-13T10-00-00.db.gz      │ 2025-12-13 10:00:00 │ 98.5      │ 6 hours
 3     │ looker-2025-12-12T14-30-00.db.gz      │ 2025-12-12 14:30:00 │ 99.2      │ 1 day
```

### 4. Download a Snapshot

```bash
# Download snapshot #1 (most recent)
lookervault snapshot download 1
```

**Output**:
```
Downloading looker-2025-12-13T14-30-00.db.gz... ━━━━━━━━━━━━━━━━━━━━━━ 100% 00:20
Verifying checksum... ✓
Decompressing... ✓

✓ Download complete!
  Downloaded to: ./looker.db
  Size: 350.0 MB (decompressed)
  Verified: CRC32C checksum match
```

### 5. Restore from Cloud Snapshot

```bash
# Restore directly from cloud snapshot (no manual download needed)
lookervault restore dashboards --from-snapshot 1
```

**Output**:
```
Fetching snapshot metadata... ✓
Downloading snapshot to temporary location... ━━━━━━━━━━━━━━━━━━━━━━ 100% 00:20
Verifying checksum... ✓

Starting restoration from snapshot...

[Progress] Restoring dashboards...
✓ Restored 150 dashboards
✓ Restoration complete!

Cleaning up temporary snapshot file...
```

---

## Common Workflows

### Workflow 1: Daily Backup Automation

**Goal**: Automatically upload daily snapshots to cloud storage via cron job.

**Setup**:

1. Create backup script (`~/bin/lookervault-daily-backup.sh`):
```bash
#!/bin/bash
set -euo pipefail

# Set credentials
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"

# Extract latest Looker content
cd /path/to/lookervault
lookervault extract --workers 8

# Upload snapshot to cloud
lookervault snapshot upload --json > /tmp/upload-result.json

# Log result
echo "$(date): Backup complete" >> /var/log/lookervault-backup.log
```

2. Make executable:
```bash
chmod +x ~/bin/lookervault-daily-backup.sh
```

3. Add to crontab (daily at 2 AM):
```bash
crontab -e

# Add this line:
0 2 * * * /home/user/bin/lookervault-daily-backup.sh
```

**Result**: Automatic daily snapshots uploaded to GCS with timestamped filenames.

---

### Workflow 2: Disaster Recovery Test

**Goal**: Verify disaster recovery process by restoring from a previous snapshot.

**Steps**:

1. **List available snapshots**:
```bash
lookervault snapshot list
```

2. **Download snapshot from 1 week ago** (e.g., snapshot #7):
```bash
lookervault snapshot download 7 --output /tmp/recovery-test.db
```

3. **Verify snapshot integrity**:
```bash
# Checksum is automatically verified during download
# If successful, snapshot is ready for testing
```

4. **Perform test restoration** (dry-run):
```bash
lookervault restore dashboards --from-snapshot 7 --dry-run
```

5. **Execute actual restoration** (if dry-run passed):
```bash
lookervault restore dashboards --from-snapshot 7
```

6. **Verify restored content** in Looker UI.

**Result**: Confidence that disaster recovery process works correctly.

---

### Workflow 3: Retention Policy Management

**Goal**: Maintain storage costs by automatically deleting old snapshots.

**Setup**:

1. Configure retention policy in `lookervault.toml`:
```toml
[snapshot.retention]
min_days = 30       # Cannot delete before 30 days
max_days = 90       # Auto-delete after 90 days
min_count = 5       # Always keep 5 most recent
enabled = true
```

2. **Preview cleanup** (dry-run):
```bash
lookervault snapshot cleanup
```

**Output**:
```
[DRY-RUN] Retention Policy Cleanup Preview

Snapshots to protect (5 most recent): 5 snapshots
Snapshots to delete (older than 90 days): 2 snapshots
  ✗ looker-2025-09-10T14-30-00.db.gz (95 days old, 98.2 MB)
  ✗ looker-2025-09-05T14-30-00.db.gz (100 days old, 97.8 MB)

[DRY-RUN] Would delete 2 snapshots, saving 196.0 MB.
```

3. **Execute cleanup**:
```bash
lookervault snapshot cleanup --no-dry-run --force
```

4. **Automate cleanup** (daily cron job at 3 AM):
```bash
crontab -e

# Add this line:
0 3 * * * cd /path/to/lookervault && lookervault snapshot cleanup --no-dry-run --force
```

**Result**: Automatic cleanup keeps storage costs predictable and controlled.

---

### Workflow 4: Migration to New Environment

**Goal**: Migrate Looker content from production to staging using cloud snapshots.

**Steps**:

**On Production Server**:

1. Extract and upload latest snapshot:
```bash
# Extract current state
lookervault extract --workers 8

# Upload to cloud
lookervault snapshot upload
```

**On Staging Server**:

2. Configure staging environment:
```bash
# Set staging Looker credentials
export LOOKERVAULT_CLIENT_ID="staging-client-id"
export LOOKERVAULT_CLIENT_SECRET="staging-client-secret"

# Use same GCS bucket (shared snapshots)
export LOOKERVAULT_GCS_BUCKET="lookervault-backups"
```

3. List snapshots:
```bash
lookervault snapshot list
```

4. Restore from production snapshot:
```bash
# Restore all content from snapshot #1 (production)
lookervault restore --from-snapshot 1 --workers 8
```

**Result**: Staging environment synchronized with production using cloud storage as intermediary.

---

### Workflow 5: Selective Content Restoration

**Goal**: Restore only specific content types from a snapshot.

**Steps**:

1. **List snapshots**:
```bash
lookervault snapshot list
```

2. **Restore dashboards only** from snapshot #3:
```bash
lookervault restore dashboards --from-snapshot 3
```

3. **Restore multiple content types**:
```bash
lookervault restore dashboards looks folders --from-snapshot 3
```

4. **Dry-run to preview** before actual restore:
```bash
lookervault restore dashboards looks --from-snapshot 3 --dry-run
```

**Result**: Granular control over what content is restored from snapshots.

---

## Advanced Usage

### Upload with Custom Compression

```bash
# Maximum compression (slower upload, smaller file)
lookervault snapshot upload --compression-level 9

# Fastest compression (faster upload, larger file)
lookervault snapshot upload --compression-level 1

# Disable compression (fastest, largest file)
lookervault snapshot upload --no-compress
```

### Download to Specific Location

```bash
# Download to custom path
lookervault snapshot download 1 --output /backups/looker-recovery.db

# Overwrite existing file without confirmation
lookervault snapshot download 1 --output looker.db --overwrite
```

### List with Filters

```bash
# Show 10 most recent snapshots
lookervault snapshot list --limit 10

# Show snapshots from December 2025
lookervault snapshot list --filter "2025-12"

# Show snapshots from last 7 days
lookervault snapshot list --filter "last-7-days"

# Detailed metadata view
lookervault snapshot list --verbose
```

### Delete Old Snapshots

```bash
# Delete snapshot #10 (with confirmation)
lookervault snapshot delete 10

# Delete without confirmation
lookervault snapshot delete 10 --force

# Preview deletion (dry-run)
lookervault snapshot delete 10 --dry-run
```

### JSON Output for Automation

All commands support `--json` flag for machine-parseable output:

```bash
# Upload with JSON output
lookervault snapshot upload --json | jq '.snapshot.gcs_path'
# Output: "gs://lookervault-backups/snapshots/looker-2025-12-13T14-30-00.db.gz"

# List with JSON output
lookervault snapshot list --json | jq '.snapshots[] | select(.sequential_index == 1)'
# Output: {...snapshot metadata...}

# Download with JSON output
lookervault snapshot download 1 --json | jq '.checksum_verified'
# Output: true
```

---

## Troubleshooting

### Problem: Authentication Failed

**Error**:
```
✗ Error: Authentication failed
  No valid credentials found.
```

**Solutions**:

1. **Set GOOGLE_APPLICATION_CREDENTIALS**:
```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
```

2. **Use gcloud CLI**:
```bash
gcloud auth application-default login
```

3. **Verify credentials**:
```bash
# Check if credentials work
gcloud storage ls gs://lookervault-backups
```

---

### Problem: Bucket Not Found

**Error**:
```
✗ Error: Bucket not found
  Bucket 'lookervault-backups' does not exist.
```

**Solutions**:

1. **Create bucket**:
```bash
gcloud storage buckets create gs://lookervault-backups \
  --location=us-central1 \
  --uniform-bucket-level-access
```

2. **Verify bucket name** in `lookervault.toml`:
```toml
[snapshot]
bucket_name = "lookervault-backups"  # Must match actual bucket
```

---

### Problem: Upload Slow or Timing Out

**Error**:
```
✗ Error: Upload timed out after 120s
```

**Solutions**:

1. **Check network connection**:
```bash
ping -c 4 storage.googleapis.com
```

2. **Reduce compression level** (faster upload, larger file):
```bash
lookervault snapshot upload --compression-level 3
```

3. **Disable compression** for very large files:
```bash
lookervault snapshot upload --no-compress
```

4. **Check firewall settings** (allow HTTPS to `*.googleapis.com`)

---

### Problem: Checksum Verification Failed

**Error**:
```
✗ Error: Checksum verification failed
  Downloaded file is corrupted.
```

**Solutions**:

1. **Retry download** (network glitch):
```bash
lookervault snapshot download 1
```

2. **Skip checksum verification** (not recommended):
```bash
lookervault snapshot download 1 --no-verify-checksum
```

3. **Contact support** if persistent (corrupted snapshot in GCS)

---

### Problem: Snapshot Not Found

**Error**:
```
✗ Error: Invalid snapshot reference
  Snapshot "2025-12-13T14-99-00" not found.
```

**Solutions**:

1. **List available snapshots**:
```bash
lookervault snapshot list
```

2. **Use sequential index** instead of timestamp:
```bash
lookervault snapshot download 1  # Instead of exact timestamp
```

3. **Clear cache** and retry:
```bash
lookervault snapshot list --no-cache
```

---

## Best Practices

### 1. Regular Backups

- **Daily uploads**: Schedule daily snapshots via cron (see Workflow 1)
- **Pre-change snapshots**: Upload snapshot before major Looker configuration changes
- **Post-migration snapshots**: Upload after successful content migration

### 2. Retention Management

- **Configure retention policy**: Set `max_days` to control storage costs
- **Minimum count protection**: Always keep at least 5-10 most recent snapshots
- **Test cleanup first**: Run `lookervault snapshot cleanup` (dry-run) before forcing

### 3. Disaster Recovery Testing

- **Quarterly tests**: Restore from snapshot to verify disaster recovery process works
- **Document runbooks**: Maintain step-by-step recovery procedures
- **Monitor restoration time**: Track how long full restoration takes (for RTO planning)

### 4. Cost Optimization

- **Enable Autoclass**: Automatic storage class transitions reduce costs (set in GCS bucket)
- **Compression**: Always use compression (70-80% size reduction for JSON content)
- **Regional storage**: Use regional buckets instead of multi-regional (30% cheaper)
- **Monitor costs**: Set up cost alerts in GCP console

### 5. Security

- **Encrypt snapshots**: Use GCS server-side encryption (enabled by default)
- **Service account permissions**: Use least-privilege IAM roles (Storage Admin for bucket only)
- **Rotate credentials**: Regularly rotate service account keys
- **Audit logging**: Enable GCS Data Access logs for compliance

---

## Next Steps

- **Read the full documentation**: See `spec.md` for detailed feature specification
- **Review data model**: See `data-model.md` for entity definitions
- **CLI reference**: See `contracts/cli-commands.md` for complete command documentation
- **Contact support**: Open GitHub issue for questions or bug reports

---

## Summary

Cloud snapshot management in LookerVault provides:

✅ **Off-site backups** in Google Cloud Storage
✅ **Automated retention** with cost control
✅ **Disaster recovery** with point-in-time restoration
✅ **Data integrity** via CRC32C checksum verification
✅ **Compression** for storage cost reduction (70-80% typical)
✅ **CLI-first design** for automation and scripting

**Get started in 5 minutes**: Upload, list, download, and restore from cloud snapshots with simple CLI commands.
