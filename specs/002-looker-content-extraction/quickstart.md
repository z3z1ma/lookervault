# Quickstart Guide: Looker Content Extraction

**Feature**: 002-looker-content-extraction
**Date**: 2025-12-13
**Audience**: Developers and operators

## Overview

This guide shows how to extract all content from a Looker instance to local SQLite storage. After completing this guide, you'll be able to:

- Extract all Looker content types (dashboards, looks, models, users, etc.)
- View extraction progress in real-time
- Resume interrupted extractions
- Verify extracted content integrity
- Query extracted content

**Estimated Time**: 5-15 minutes for first extraction (depends on instance size)

---

## Prerequisites

1. **Looker API credentials** configured in `.env` or `looker.ini`
2. **Python 3.13+** installed
3. **LookerVault** installed: `uv sync`
4. **Read permissions** in Looker for all content you want to extract

### Verify Setup

```bash
# Check Looker connection
lookervault check

# Should output:
# ✓ Connected to Looker at https://your-instance.looker.com
# ✓ Authenticated as: your-email@example.com
# ✓ API version: 4.0
```

---

## Quick Start (5 Minutes)

### 1. Run First Extraction

```bash
# Extract all content types
lookervault extract

# With progress display (default):
# ⠋ Extracting dashboards... ████████████████████ 100/100 (100%) 0:00:45 remaining
# ⠋ Extracting looks... ██████████░░░░░░░░░░ 50/100 (50%) 0:00:30 remaining
```

**What happens:**
- Connects to Looker API
- Extracts all content types sequentially
- Serializes to msgpack format
- Stores in `looker.db` SQLite file
- Creates checkpoints for resume capability

**Output:**
```
✓ Extraction complete!
  Dashboards: 100 items
  Looks: 50 items
  Folders: 25 items
  Users: 200 items
  Total: 375 items in 2m 15s
  Storage: looker.db (15.2 MB)
```

### 2. View Extracted Content

```bash
# List all dashboards
lookervault list dashboards

# Output (table format):
# ID               Name              Owner           Updated     Size
# 123              Sales Overview    john@ex.com     2d ago      45.2 KB
# 456              Marketing Dash    jane@ex.com     Today       123.5 KB
```

### 3. Verify Integrity

```bash
# Verify all extracted content
lookervault verify

# Output:
# ✓ Verifying content integrity...
#   Dashboards: 100/100 valid
#   Looks: 50/50 valid
#   ✓ All content verified successfully
```

---

## Common Usage Patterns

### Extract Specific Content Types

```bash
# Extract only dashboards and looks
lookervault extract --types dashboards,looks

# Extract only user-related content
lookervault extract --types users,groups,roles
```

**Available Types:**
- `dashboards` - Dashboard definitions
- `looks` - Saved looks
- `models` - LookML models (includes explores)
- `folders` - Folder structure
- `users` - User accounts
- `groups` - User groups
- `roles` - Permission roles
- `boards` - Homepage boards
- `schedules` - Scheduled deliveries
- `permissions` - Permission sets
- `model_sets` - Model access sets

### Resume Interrupted Extraction

```bash
# If extraction was interrupted (Ctrl+C, network failure, etc.)
lookervault extract --resume

# Output:
# ℹ Found incomplete extraction from 2025-12-13 10:30:15
# ℹ Resuming from checkpoint: dashboards (offset 500/1000)
# ⠋ Extracting dashboards... ████████████░░░░░░░░ 750/1000 (75%)
```

### JSON Output (for scripting)

```bash
# Machine-readable JSON output
lookervault extract --output json

# Output (structured JSON events):
# {"event":"extraction_started","timestamp":"2025-12-13T10:30:00Z","types":["dashboards","looks"]}
# {"event":"extraction_progress","content_type":"dashboards","completed":50,"total":100,"percentage":50.0}
# {"event":"extraction_complete","total_items":150,"duration_seconds":135.4}
```

### Custom Configuration

```bash
# Use custom config file
lookervault extract --config /path/to/config.toml

# Specify database path
lookervault extract --db /path/to/custom.db

# Adjust batch size (for memory-constrained environments)
lookervault extract --batch-size 50
```

---

## Advanced Usage

### Incremental Extraction

```bash
# Extract only new/changed content since last extraction
lookervault extract --incremental

# Uses timestamps to detect changes
# Significantly faster for regular backups
```

### Selective Field Extraction

```bash
# Extract only specific fields (reduces size/time)
lookervault extract --fields id,title,description,updated_at

# Default extracts all fields for faithful restoration
```

### Parallel Extraction (Future)

```bash
# Extract multiple content types in parallel (not MVP)
lookervault extract --parallel --workers 4
```

---

## Troubleshooting

### Rate Limit Errors

**Symptom**: `WARNING: Rate limit hit, will retry in 30 seconds`

**Solution**: Automatic - tenacity handles retry with exponential back-off.

**To prevent**:
```bash
# Reduce batch size to make fewer API calls
lookervault extract --batch-size 50
```

### Memory Errors

**Symptom**: `MemoryError` or system slowdown

**Solution**:
```bash
# Reduce batch size to process fewer items at once
lookervault extract --batch-size 25

# Extract one content type at a time
lookervault extract --types dashboards
lookervault extract --types looks
```

### Connection Errors

**Symptom**: `ConnectionError: Unable to connect to Looker`

**Solution**:
1. Verify credentials: `lookervault check`
2. Check network/VPN connection
3. Verify Looker instance is accessible
4. Check API credentials haven't expired

### Extraction Stalls

**Symptom**: Progress bar stops moving

**Possible causes**:
- Very large item being processed (10MB+)
- Network timeout
- Looker API slowness

**Solution**:
```bash
# Check logs for details
lookervault extract --verbose

# Ctrl+C to cancel, then resume
lookervault extract --resume
```

### Timeout Errors

**Symptom**: `HTTPSConnectionPool... Read timed out. (read timeout=30)`

**Cause**: Large instances with 10,000+ items timing out on API calls

**Solution 1 - Increase Timeout**:
```bash
# Set 5-minute timeout for large instances
export LOOKERVAULT_TIMEOUT=300
lookervault extract --types dashboards
```

**Solution 2 - Use Pagination**:
```bash
# Reduce batch size for smaller API calls
lookervault extract --batch-size 50
```

**Permanent Fix** (in config file):
```toml
[lookervault.looker]
timeout = 300  # 5 minutes
```

### Interrupted Extraction

**Symptom**: Extraction stopped mid-process (Ctrl+C, crash, network failure)

**Recovery**: Resume automatically picks up where it left off
```bash
# Resume from last checkpoint
lookervault extract --resume

# Output:
# ✓ Resuming from checkpoint...
#   Dashboards: Already complete (1250 items)
#   Looks: Resuming from item 450/800
```

**How Resume Works**:
- Checkpoints created after each content type
- Safe to interrupt at any time
- No duplicate items (uses UPSERT)
- Can switch between content types

**Force Fresh Start**:
```bash
# Disable resume to start over
lookervault extract --no-resume

# Or delete checkpoints manually
rm looker.db  # Start completely fresh
```

### Datetime/Timezone Errors

**Symptom**: `TypeError: can't subtract offset-naive and offset-aware datetimes`

**Status**: Fixed in latest version (uses UTC timestamps consistently)

**Workaround** (if on older version):
```bash
# Update to latest version
uv sync
```

### API Rate Limiting

**Symptom**: Frequent `429 Too Many Requests` errors

**Automatic Handling**: Built-in exponential backoff with tenacity

**Manual Adjustment**:
```bash
# Reduce batch size to slow down requests
lookervault extract --batch-size 25

# Extract one type at a time to space out requests
lookervault extract --types dashboards
sleep 60
lookervault extract --types looks
```

**Monitor Progress**:
```bash
# Watch retry behavior
lookervault extract --verbose

# Output shows retries:
# WARNING: Rate limit exceeded, retrying in 30s...
# INFO: Retry attempt 1/5
```

### Database Corruption

**Symptom**: `SQLITE_CORRUPT` or verification failures

**Recovery Steps**:
```bash
# 1. Verify the issue
lookervault verify

# 2. If corruption confirmed, re-extract affected types
mv looker.db looker.db.backup
lookervault extract --types dashboards,looks

# 3. Compare with backup to see what was lost
sqlite3 looker.db.backup "SELECT content_type, COUNT(*) FROM content_items GROUP BY content_type"
```

**Prevention**:
- Use `--resume` for safe interruption
- Don't kill process with `kill -9`
- Ensure disk space available
- Regular backups with `cleanup` command

### Memory Warnings

**Symptom**: `Memory usage is elevated: 500.0 MB`

**Automatic Handling**: Warnings at 500MB and 1GB thresholds

**If Critical Warning Appears**:
```bash
# Reduce batch size immediately
lookervault extract --batch-size 25

# Extract smaller content types first
lookervault extract --types users,groups
```

**Long-term Fix**:
- Increase system RAM
- Extract content types individually
- Use smaller batch sizes

---

## Verification & Validation

### Verify Specific Content Type

```bash
# Verify only dashboards
lookervault verify --type dashboards

# Output:
# ✓ Verifying dashboards...
#   Checking 100 items...
#   ✓ All dashboards valid
#   ✓ No corruption detected
```

### Compare with Looker

```bash
# Compare local DB with current Looker state
lookervault verify --compare-live

# Output:
# ℹ Comparing with Looker instance...
#   New items in Looker: 5 dashboards
#   Modified items: 3 looks
#   Deleted items: 1 folder
#   ✓ Local DB is 1 day old
```

### Integrity Checks

```bash
# Full integrity check (slower but comprehensive)
lookervault verify --full

# Checks:
# - Binary data is valid msgpack
# - Deserialization succeeds
# - Content size matches stored size
# - No SQLite corruption
```

---

## Querying Extracted Content

### List Content

```bash
# List all content of a type
lookervault list dashboards

# With filters
lookervault list dashboards --created-after 2025-01-01
```

### Export Content

```bash
# Export specific dashboard to JSON
lookervault export dashboard::123 > dashboard.json

# Export all dashboards to directory
lookervault export dashboards --output-dir ./dashboards/
```

### Search Content

```bash
# Search by name
lookervault search "Sales"

# Output:
# Dashboards:
#   dashboard::123 - Sales Overview
#   dashboard::456 - Q4 Sales Report
# Looks:
#   look::789 - Sales by Region
```

---

## Configuration

### Environment Variables

```bash
# Looker API credentials
export LOOKER_BASE_URL="https://your-instance.looker.com"
export LOOKER_CLIENT_ID="your-client-id"
export LOOKER_CLIENT_SECRET="your-client-secret"

# Extraction settings
export LOOKERVAULT_DB_PATH="./looker.db"
export LOOKERVAULT_BATCH_SIZE="100"
export LOOKERVAULT_OUTPUT_MODE="table"  # or "json"
```

### Config File (looker.ini or lookervault.toml)

```toml
[looker]
base_url = "https://your-instance.looker.com"
client_id = "your-client-id"
client_secret = "your-client-secret"
verify_ssl = true
timeout = 30

[extraction]
db_path = "./looker.db"
batch_size = 100
default_fields = "id,title,description,folder,created_at,updated_at"
auto_resume = true

[storage]
retention_days = 30  # Keep soft-deleted items for 30 days
max_blob_size_mb = 10  # Warn on items > 10MB
```

---

## Performance Tuning

### For Large Instances (10,000+ items)

```bash
# Increase batch size (more memory, fewer API calls)
lookervault extract --batch-size 200

# Use incremental mode for regular backups
lookervault extract --incremental
```

### For Small/Memory-Constrained Environments

```bash
# Decrease batch size
lookervault extract --batch-size 25

# Extract one type at a time
for type in dashboards looks folders users; do
    lookervault extract --types $type
done
```

### For Faster Extractions

```bash
# Reduce fields (only extract what you need)
lookervault extract --fields id,title,updated_at

# Skip verification during extraction
lookervault extract --no-verify
```

---

## Monitoring & Logging

### Progress Monitoring

```bash
# Human-readable progress (default)
lookervault extract
# Uses Rich progress bars

# Machine-readable progress
lookervault extract --output json | jq
# Emits JSON events for parsing
```

### Logging

```bash
# Verbose logging
lookervault extract --verbose

# Debug logging (very detailed)
lookervault extract --debug

# Log to file
lookervault extract --log-file extraction.log

# Log format options
lookervault extract --log-format json  # Structured logging
```

### Metrics

```bash
# View extraction statistics
lookervault stats

# Output:
# Extraction Statistics
#   Total extractions: 15
#   Last extraction: 2025-12-13 10:30:15
#   Total items: 1,500
#   Database size: 45.2 MB
#   Average extraction time: 3m 20s
#   Success rate: 98.5%
```

---

## Automation

### Cron Job (Daily Backups)

```bash
# Add to crontab
0 2 * * * cd /path/to/lookervault && lookervault extract --incremental --output json >> /var/log/lookervault.log 2>&1
```

### CI/CD Integration

```yaml
# GitHub Actions example
name: Daily Looker Backup
on:
  schedule:
    - cron: '0 2 * * *'

jobs:
  backup:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Extract Looker Content
        env:
          LOOKER_BASE_URL: ${{ secrets.LOOKER_BASE_URL }}
          LOOKER_CLIENT_ID: ${{ secrets.LOOKER_CLIENT_ID }}
          LOOKER_CLIENT_SECRET: ${{ secrets.LOOKER_CLIENT_SECRET }}
        run: |
          uv run lookervault extract --output json
      - name: Upload Database
        uses: actions/upload-artifact@v4
        with:
          name: looker-backup
          path: looker.db
```

---

## Best Practices

### 1. Regular Backups

```bash
# Daily incremental backups
lookervault extract --incremental

# Weekly full backups
# (cron: 0 3 * * 0)
lookervault extract --full
```

### 2. Verify After Extraction

```bash
# Always verify critical extractions
lookervault extract && lookervault verify
```

### 3. Monitor Database Size

```bash
# Check database size regularly
du -h looker.db

# Apply retention policy to prevent unlimited growth
lookervault cleanup --retention-days 30
```

### 4. Test Restore Capability

```bash
# Periodically test that content can be restored (future feature)
lookervault test-restore --dry-run
```

### 5. Secure Credentials

```bash
# Use environment variables, not config files in version control
export LOOKER_CLIENT_SECRET="$(cat /secure/path/secret.txt)"

# Or use secret management
export LOOKER_CLIENT_SECRET="$(aws secretsmanager get-secret-value --secret-id looker-api-secret --query SecretString --output text)"
```

---

## Next Steps

After completing this quickstart:

1. **Schedule Regular Backups**: Set up cron/CI for automated extractions
2. **Implement Restore**: Follow restore guide (future feature)
3. **Monitor Performance**: Track extraction times and database growth
4. **Test Recovery**: Verify you can restore content when needed
5. **Explore API**: Use Python API for custom integrations

---

## Command Reference

### Extract Commands

```bash
lookervault extract [OPTIONS]

Options:
  --types TEXT         Comma-separated content types
  --output TEXT        Output format: table|json [default: table]
  --config PATH        Custom config file
  --db PATH            Database path [default: ./looker.db]
  --batch-size INT     Items per batch [default: 100]
  --resume             Resume incomplete extraction
  --incremental        Extract only changed items
  --fields TEXT        Comma-separated field list
  --verbose            Verbose logging
  --debug              Debug logging
  --log-file PATH      Log to file
  --help               Show help
```

### Verify Commands

```bash
lookervault verify [OPTIONS]

Options:
  --type TEXT          Content type to verify
  --compare-live       Compare with current Looker state
  --full               Full integrity check
  --verbose            Verbose output
  --help               Show help
```

### Info and List Commands

```bash
# Show Looker instance information
lookervault info [OPTIONS]

Options:
  --config PATH        Config file path
  --output TEXT        Output format: table|json

# List extracted content
lookervault list CONTENT_TYPE [OPTIONS]

Arguments:
  CONTENT_TYPE         Type to list (dashboards, looks, users, etc.)

Options:
  --db PATH            Database path (default: looker.db)
  --created-after TEXT Filter by creation date (ISO format)
  --limit INT          Limit results
  --offset INT         Pagination offset
  --output TEXT        Output format: table|json
  --help               Show help
```

---

## FAQ

**Q: How long does extraction take?**
A: Depends on instance size. Typical: 1,000 items ≈ 5-10 minutes.

**Q: Can I run multiple extractions simultaneously?**
A: No, SQLite has write locks. Run sequentially or use separate databases.

**Q: What happens if extraction fails?**
A: Checkpoints allow resuming with `--resume`. No partial data committed.

**Q: Is extracted data encrypted?**
A: Not by default. Encrypt looker.db file if needed (OS-level).

**Q: Can I extract from multiple Looker instances?**
A: Yes, use different databases: `--db prod.db` vs `--db dev.db`.

**Q: How much disk space do I need?**
A: Approximately 2-5x the total size of your Looker content (due to compression).

---

## Getting Help

```bash
# Built-in help
lookervault --help
lookervault extract --help

# Check version
lookervault --version

# View logs
tail -f ~/.lookervault/logs/extract.log

# Report issues
# https://github.com/your-org/lookervault/issues
```

---

## Summary

**Basic Workflow:**
1. `lookervault check` - Verify connection
2. `lookervault extract` - Extract all content
3. `lookervault verify` - Verify integrity
4. `lookervault list` - Query extracted content
5. `lookervault cleanup` - Remove old soft-deleted items

**For Production:**
- Use `--incremental` for regular backups
- Enable `--output json` for automation
- Schedule with cron/CI
- Monitor database growth
- Test restore capability regularly

You're now ready to extract and manage Looker content backups!
