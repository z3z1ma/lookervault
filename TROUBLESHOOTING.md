# Troubleshooting Guide

This guide explains common error messages you may encounter when using LookerVault, what they mean, and how to resolve them.

## Table of Contents

- [Configuration Errors](#configuration-errors)
- [Authentication Errors](#authentication-errors)
- [Rate Limit Errors](#rate-limit-errors)
- [Network Connection Errors](#network-connection-errors)
- [Timeout Errors](#timeout-errors)
- [Database Errors](#database-errors)
- [Content Extraction Errors](#content-extraction-errors)
- [Content Restoration Errors](#content-restoration-errors)
- [YAML Validation Errors](#yaml-validation-errors)
- [Cloud Storage Errors](#cloud-storage-errors)
- [Exit Codes](#exit-codes)

---

## Configuration Errors

### `Configuration error: Invalid TOML syntax`

**What it means**: The configuration file contains invalid TOML syntax.

**Common causes**:
- Missing quotes around string values
- Unbalanced brackets or parentheses
- Invalid escape sequences
- Using `=` instead of `:` for key-value pairs

**How to fix**:
```bash
# Validate your TOML syntax
lookervault check

# Common fixes:
# 1. Use quotes for strings
api_url = "https://looker.example.com:19999"  # Correct
api_url = https://looker.example.com:19999     # Incorrect

# 2. Escape special characters
password = "my\"password"  # Correct
password = "my"password"   # Incorrect

# 3. Use valid boolean values
verify_ssl = true   # Correct
verify_ssl = "yes"  # Incorrect
```

### `Configuration file not found: ~/.lookervault/config.toml`

**What it means**: LookerVault cannot find your configuration file.

**How to fix**:
```bash
# Create the configuration directory
mkdir -p ~/.lookervault

# Create a minimal config file
cat > ~/.lookervault/config.toml << 'EOF'
[looker]
api_url = "https://your-looker-instance.com:19999"
client_id = ""  # Set via LOOKERVAULT_CLIENT_ID env var
client_secret = ""  # Set via LOOKERVAULT_CLIENT_SECRET env var
timeout = 30
verify_ssl = true

[output]
default_format = "table"
color_enabled = true
EOF

# Verify configuration
lookervault check
```

### `Invalid LOOKERVAULT_TIMEOUT value`

**What it means**: The `LOOKERVAULT_TIMEOUT` environment variable is not a valid integer.

**How to fix**:
```bash
# Set timeout as an integer (seconds)
export LOOKERVAULT_TIMEOUT=300  # 5 minutes - Correct
export LOOKERVAULT_TIMEOUT="5m"  # Incorrect

# Verify configuration
lookervault check
```

---

## Authentication Errors

### `Authentication failed - invalid credentials`

**What it means**: Your Looker API credentials are incorrect or have expired.

**Common causes**:
- Invalid client ID or client secret
- API credentials have been revoked or expired
- Environment variables not set correctly
- Wrong user permissions

**How to fix**:
```bash
# 1. Verify credentials are set
echo $LOOKERVAULT_CLIENT_ID
echo $LOOKERVAULT_CLIENT_SECRET

# 2. If empty, set them in your shell profile (~/.bashrc, ~/.zshrc, etc.)
export LOOKERVAULT_CLIENT_ID="your_client_id"
export LOOKERVAULT_CLIENT_SECRET="your_client_secret"

# 3. Test authentication
lookervault check

# 4. If still failing, regenerate API credentials in Looker Admin panel:
#    - Go to: Admin -> Users -> [Your User] -> Edit API Settings
#    - Generate new client ID and secret
#    - Update environment variables with new credentials
```

### `401 Unauthorized` or `Unauthorized: Invalid API credentials`

**What it means**: The Looker API rejected your authentication request.

**How to fix**:
```bash
# Clear any cached credentials
unset LOOKERVAULT_CLIENT_ID LOOKERVAULT_CLIENT_SECRET

# Set fresh credentials
export LOOKERVAULT_CLIENT_ID="your_new_client_id"
export LOOKERVAULT_CLIENT_SECRET="your_new_client_secret"

# Test connection
lookervault info

# If you see "connected: true" and "authenticated: true", you're good to go
```

### `Forbidden: Insufficient permissions`

**What it means**: Your Looker user account lacks required permissions.

**How to fix**:
1. Ensure your Looker account has the following permissions:
   - **View** access for content you want to extract
   - **Edit** access for content you want to restore
   - **Admin** or **Develop** permissions for LookML models

2. Contact your Looker administrator to grant necessary permissions.

3. Test with a user that has admin privileges:
```bash
# Temporarily use admin credentials for testing
export LOOKERVAULT_CLIENT_ID="admin_client_id"
export LOOKERVAULT_CLIENT_SECRET="admin_client_secret"

lookervault check
```

---

## Rate Limit Errors

### `WARNING: Rate limit hit, will retry in 30 seconds`

**What it means**: LookerVault has hit the Looker API rate limit and will automatically retry after waiting.

**What happens automatically**:
- LookerVault uses **adaptive rate limiting** to detect and handle rate limits
- Requests are automatically retried with exponential backoff
- Default retry behavior: up to 5 attempts with increasing delays

**How to fix (if persistent)**:
```bash
# Option 1: Reduce worker count (fewer concurrent requests)
lookervault extract --workers 4  # Instead of 8

# Option 2: Reduce rate limits
lookervault extract --workers 8 \
  --rate-limit-per-minute 60 \
  --rate-limit-per-second 5

# Option 3: Extract content types individually
lookervault extract dashboards --workers 4
lookervault extract looks --workers 4
```

### `RateLimitError: Rate limit exceeded`

**What it means**: All retry attempts have been exhausted due to persistent rate limiting.

**How to fix**:
```bash
# 1. Significantly reduce throughput
lookervault extract --workers 2 \
  --rate-limit-per-minute 30 \
  --rate-limit-per-second 2

# 2. Extract during off-peak hours (fewer API calls from other users)

# 3. Use checkpoint resume if interrupted
lookervault extract --resume
```

### `Too Many Requests (HTTP 429)`

**What it means**: The Looker API returned HTTP 429, indicating rate limiting.

**Automatic handling**:
- LookerVault detects `429` responses automatically
- Adaptive rate limiter adjusts to avoid future rate limits
- Failed requests are retried with exponential backoff

**If rate limits persist**:
```bash
# Looker API rate limits by default:
# - 120 requests per minute
# - 10 requests per second

# Conservative settings for large instances:
lookervault extract --workers 4 \
  --rate-limit-per-minute 100 \
  --rate-limit-per-second 8
```

---

## Network Connection Errors

### `ConnectionError: Unable to connect to Looker`

**What it means**: LookerVault cannot establish a network connection to your Looker instance.

**Common causes**:
- Network connectivity issues (VPN, firewall, proxy)
- Incorrect API URL
- Looker instance is down or unreachable
- DNS resolution failures

**How to fix**:
```bash
# 1. Verify network connectivity
ping your-looker-instance.com
curl -I https://your-looker-instance.com:19999

# 2. Verify API URL is correct
lookervault info

# 3. If using VPN, ensure VPN is connected
# Check VPN status and reconnect if needed

# 4. Check for firewall/proxy issues
# Temporarily disable firewall to test (use caution)

# 5. Verify DNS resolution
nslookup your-looker-instance.com
dig your-looker-instance.com

# 6. Test with explicit timeout
export LOOKERVAULT_TIMEOUT=120  # 2 minutes
lookervault check
```

### `Connection timeout - check network connectivity`

**What it means**: The connection attempt to Looker timed out.

**How to fix**:
```bash
# 1. Increase timeout value for large instances
export LOOKERVAULT_TIMEOUT=300  # 5 minutes

# 2. Check network latency
ping your-looker-instance.com

# 3. Verify API URL includes port
# Correct:  https://looker.company.com:19999
# Incorrect: https://looker.company.com

# 4. Test connection manually
curl -v https://your-looker-instance.com:19999/api/v4.0/user

# 5. If behind corporate proxy, configure proxy settings
export HTTP_PROXY="http://proxy.company.com:8080"
export HTTPS_PROXY="http://proxy.company.com:8080"
```

### `SSL verification failed`

**What it means**: The SSL/TLS certificate verification failed.

**How to fix**:
```bash
# Option 1: Fix SSL certificate (recommended)
# Ensure your Looker instance has a valid SSL certificate

# Option 2: Disable SSL verification (not recommended for production)
# Edit ~/.lookervault/config.toml:
[looker]
verify_ssl = false  # Disables SSL verification

# Option 3: Use self-signed certificate
export SSL_CERT_FILE="/path/to/certificate.pem"
export REQUESTS_CA_BUNDLE="/path/to/ca-bundle.pem"
```

---

## Timeout Errors

### `Request timeout after 30 seconds`

**What it means**: A Looker API request took longer than the configured timeout.

**Common causes**:
- Large Looker instance (10,000+ items)
- Slow network connection
- Looker instance under heavy load
- Complex queries or large dashboards

**How to fix**:
```bash
# 1. Increase timeout for large instances
export LOOKERVAULT_TIMEOUT=300  # 5 minutes
lookervault extract --workers 8

# 2. Reduce worker count to decrease concurrent load
lookervault extract --workers 4

# 3. Extract during off-peak hours

# 4. Use checkpoint resume for large extractions
lookervault extract --workers 8
# If interrupted:
lookervault extract --resume
```

### `TimeoutError: Operation timed out`

**What it means**: An operation exceeded the maximum allowed time.

**How to fix**:
```bash
# Increase timeout in config file
# Edit ~/.lookervault/config.toml:
[looker]
timeout = 300  # 5 minutes

# Or via environment variable
export LOOKERVAULT_TIMEOUT=600  # 10 minutes

# Retry the operation
lookervault extract --resume
```

---

## Database Errors

### `SQLITE_BUSY: database is locked`

**What it means**: Multiple workers are trying to write to the database simultaneously.

**Automatic handling**:
- LookerVault automatically retries with exponential backoff
- Thread-local connections prevent most contention

**If persistent**:
```bash
# Reduce worker count (16 is SQLite write limit)
lookervault extract --workers 8  # Instead of 16

# For restoration:
lookervault restore bulk dashboards --workers 8
```

### `StorageError: Database operation failed`

**What it means**: A database operation failed after all retry attempts.

**Common causes**:
- Disk full
- File system permissions
- Corrupted database file
- Database schema mismatch

**How to fix**:
```bash
# 1. Check disk space
df -h

# 2. Check file permissions
ls -la looker.db
chmod 644 looker.db

# 3. Verify database integrity
sqlite3 looker.db "PRAGMA integrity_check;"

# 4. If corrupted, start fresh (warning: loses data)
rm looker.db
lookervault extract --workers 8

# 5. Check for schema version mismatch
sqlite3 looker.db "SELECT version FROM schema_version;"
```

### `NotFoundError: Content not found`

**What it means**: Requested content does not exist in the database.

**How to fix**:
```bash
# 1. Verify content was extracted
lookervault list dashboards
lookervault list looks

# 2. Search for content by name
lookervault list dashboards | grep "Dashboard Name"

# 3. Re-extract if missing
lookervault extract dashboards --workers 8

# 4. Verify database path
ls -la looker.db
export LOOKERVAULT_DB_PATH="./looker.db"
```

---

## Content Extraction Errors

### `ExtractionError: Failed to extract content`

**What it means**: Content extraction failed due to an API error.

**Common causes**:
- API rate limiting (see [Rate Limit Errors](#rate-limit-errors))
- Network connectivity issues
- Invalid content ID
- Looker instance errors

**How to fix**:
```bash
# 1. Check connectivity
lookervault info

# 2. Use checkpoint resume to skip problematic items
lookervault extract --resume

# 3. Reduce worker count for stability
lookervault extract --workers 4

# 4. Extract specific content type
lookervault extract dashboards --workers 8

# 5. Check Dead Letter Queue for failed items
lookervault restore dlq list
```

### `OrchestrationError: Extraction failed`

**What it means**: The extraction workflow failed due to an unrecoverable error.

**How to fix**:
```bash
# 1. Check extraction session status
lookervault restore status --all

# 2. Review error details in database
sqlite3 looker.db "SELECT * FROM extraction_sessions ORDER BY started_at DESC LIMIT 1;"

# 3. Resume from checkpoint
lookervault extract --resume

# 4. If checkpoint is corrupted, start fresh
rm looker.db
lookervault extract --workers 8
```

### `NotFoundError: Folder ID '123' not found`

**What it means**: The specified folder ID does not exist in your Looker instance.

**How to fix**:
```bash
# 1. List all folders to find correct ID
lookervault list folders

# 2. Use folder name instead (requires folder expansion)
# First extract all folders
lookervault extract folders --workers 8

# 3. Verify folder ID exists in Looker UI
# Navigate to: Looker -> Folders -> [Folder Name]
# Check URL for folder ID

# 4. Use recursive folder extraction
lookervault extract dashboards --folder-ids "123" --recursive --workers 8
```

---

## Content Restoration Errors

### `RestorationError: Failed to update content`

**What it means**: Content restoration failed due to an API error.

**Common causes**:
- Rate limiting (see [Rate Limit Errors](#rate-limit-errors))
- Invalid content structure
- Missing dependencies (users, groups, folders)
- Permission issues

**How to fix**:
```bash
# 1. Verify dependencies exist
lookervault restore status

# 2. Check Dead Letter Queue for error details
lookervault restore dlq list

# 3. View specific DLQ entry
lookervault restore dlq show <dlq_id>

# 4. Retry failed items
lookervault restore dlq retry <dlq_id>

# 5. Use dry-run to validate before restoring
lookervault restore bulk dashboards --dry-run --workers 8
```

### `DeserializationError: Cannot deserialize content`

**What it means**: The content in the database cannot be converted back to a Looker object.

**Common causes**:
- Corrupted binary blob in database
- Schema version mismatch
- Invalid msgpack/JSON data

**How to fix**:
```bash
# 1. Verify database integrity
sqlite3 looker.db "PRAGMA integrity_check;"

# 2. Re-extract corrupted content
lookervault extract dashboards --workers 8

# 3. If database is corrupted, start fresh
rm looker.db
lookervault extract --workers 8
```

### `DependencyError: Cannot resolve dependencies`

**What it means**: Required dependencies for content are missing.

**Common causes**:
- Referenced user doesn't exist
- Referenced folder doesn't exist
- Referenced model or look doesn't exist
- Circular dependency detected

**How to fix**:
```bash
# 1. Restore in dependency order:
#    Users -> Groups -> Folders -> Models -> Dashboards -> Boards
lookervault restore bulk users --workers 8
lookervault restore bulk groups --workers 8
lookervault restore bulk folders --workers 8
lookervault restore bulk looks --workers 8
lookervault restore bulk dashboards --workers 8

# 2. Test single item restoration first
lookervault restore single dashboard <id> --dry-run

# 3. Check for missing dependencies
lookervault restore status --session-id <session_id>

# 4. View DLQ for dependency errors
lookervault restore dlq list
```

### `ValidationError: Content validation failed`

**What it means**: Content fails validation before restoration.

**Common causes**:
- Missing required fields
- Invalid field values
- Content structure doesn't match Looker API expectations

**How to fix**:
```bash
# 1. Use dry-run to see validation errors
lookervault restore bulk dashboards --dry-run --workers 8

# 2. View specific DLQ entry for details
lookverault restore dlq show <dlq_id>

# 3. Re-extract content to fix corruption
lookervault extract dashboards --workers 8

# 4. Manually fix content in database (advanced)
sqlite3 looker.db "UPDATE content_items SET content_data = '...' WHERE id = '...';"
```

---

## YAML Validation Errors

### `Invalid YAML syntax in export/dashboards/abc123.yaml`

**What it means**: The YAML file has syntax errors.

**Common causes**:
- Missing quotes around strings with special characters
- Incorrect indentation (YAML requires consistent 2-space indentation)
- Unescaped colons or other special characters
- Mixed tabs and spaces

**How to fix**:
```bash
# 1. Validate YAML syntax before packing
python3 -c "import yaml; yaml.safe_load(open('export/dashboards/abc123.yaml'))"

# 2. Common fixes:

# Add quotes around strings with colons
title: "Sales: Regional Analysis"  # Correct
title: Sales: Regional Analysis    # Incorrect

# Fix indentation (use 2 spaces, not tabs)
elements:
  - id: "elem1"      # Correct (2-space indent)
    title: "Revenue"

# Escape special characters
description: "Q1 results (updated)"  # Use quotes for parentheses

# 3. Use --dry-run to validate before packing
lookervault pack --input-dir export/ --dry-run
```

### `[Structure] DASHBOARD missing required 'elements' field`

**What it means**: Required fields are missing from the YAML structure.

**How to fix**:
```bash
# 1. Check which fields are required for each content type:
# DASHBOARD: id, title, elements
# LOOK: id, title, query

# 2. Restore missing 'elements' field
elements:
  - id: "elem1"
    title: "Element Title"
    query:
      model: "sales"
      view: "transactions"
      fields: ["transactions.total_revenue"]

# 3. Use --dry-run to validate before packing
lookervault pack --input-dir export/ --dry-run
```

### `[Query] Missing required query fields: model, view`

**What it means**: Query definition is missing required fields.

**How to fix**:
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

# Validate with --dry-run
lookervault pack --input-dir export/ --dry-run
```

### `[Field] Field 'title' cannot be empty`

**What it means**: A required field has an invalid value.

**How to fix**:
```bash
# 1. Fix empty titles
title: ""                    # Incorrect: empty string
title: "Sales Dashboard"     # Correct

# 2. Shorten long titles (max 255 characters)
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

---

## Cloud Storage Errors

### `AuthenticationError: GCS authentication failed`

**What it means**: Google Cloud Storage credentials are invalid or missing.

**How to fix**:
```bash
# 1. Verify credentials are set
echo $GOOGLE_APPLICATION_CREDENTIALS

# 2. Set credentials path
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"

# 3. Verify service account has Storage Admin role
gcloud storage buckets get-iam-policy gs://your-bucket

# 4. Test GCS access
lookervault snapshot list

# 5. If using ADC, authenticate
gcloud auth application-default login
```

### `RuntimeError: Bucket access denied`

**What it means**: The service account lacks permissions for the GCS bucket.

**How to fix**:
```bash
# 1. Grant Storage Admin role to service account
gcloud storage buckets add-iam-policy-binding gs://lookervault-backups \
  --member="serviceAccount:lookervault-snapshots@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.admin"

# 2. Verify bucket exists
gcloud storage buckets list

# 3. Test bucket access
gsutil ls gs://lookervault-backups
```

### `OSError: Upload failed`

**What it means**: File upload to GCS failed.

**Common causes**:
- Network connectivity issues
- Insufficient storage quota
- Invalid bucket name
- File size exceeds limits

**How to fix**:
```bash
# 1. Check bucket configuration
lookervault snapshot list

# 2. Verify bucket name in config
# Edit ~/.lookervault/config.toml:
[snapshot]
bucket_name = "lookervault-backups"  # Must match actual bucket name

# 3. Test network connectivity
ping storage.googleapis.com

# 4. Check GCS quota
gcloud services project-info describe

# 5. Reduce file size with compression
# Edit config:
[snapshot]
compression_enabled = true
compression_level = 6
```

---

## Exit Codes

LookerVault uses standard exit codes to indicate success or failure:

| Exit Code | Meaning | Common Causes |
|-----------|---------|---------------|
| `0` | Success | Operation completed successfully |
| `1` | General error | Network issues, API errors, runtime errors |
| `2` | Configuration error | Invalid config, missing credentials, validation errors |
| `3` | Connection error | Cannot connect to Looker instance |
| `130` | Interrupted by user | Ctrl+C pressed |

**Checking exit codes**:
```bash
# Run command and capture exit code
lookervault extract
echo $?  # Prints exit code

# Use in scripts
lookervault extract --workers 8
if [ $? -eq 0 ]; then
  echo "Extraction successful"
else
  echo "Extraction failed with exit code $?"
fi
```

---

## Getting Additional Help

If you're still unable to resolve an error:

1. **Check the logs**: Enable verbose logging for more details
   ```bash
   lookervault extract --verbose --workers 8
   ```

2. **Review the database**: Check extraction sessions and DLQ entries
   ```bash
   sqlite3 looker.db "SELECT * FROM extraction_sessions ORDER BY started_at DESC LIMIT 5;"
   lookervault restore dlq list
   ```

3. **Test with minimal configuration**: Reduce complexity to isolate the issue
   ```bash
   lookervault extract dashboards --workers 1
   ```

4. **Report the issue**: If the error persists, please report it with:
   - Full error message
   - LookerVault version (`lookervault --version`)
   - Looker instance version
   - Configuration (redact sensitive information)
   - Steps to reproduce the error

5. **Check documentation**:
   - README.md: [README](README.md)
   - Spec documents: `specs/*/quickstart.md`
   - GitHub Issues: [Report issues here](https://github.com/yourusername/lookervault/issues)
