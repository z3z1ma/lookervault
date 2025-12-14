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

### Restoration Configuration

**Command-line options**:
- `--workers N` - Number of parallel workers (default: 8, max: 50)
- `--rate-limit-per-minute N` - API rate limit (default: 120 req/min)
- `--rate-limit-per-second N` - Burst rate limit (default: 10 req/sec)
- `--checkpoint-interval N` - Save checkpoint every N items (default: 100)
- `--max-retries N` - Max retry attempts for transient errors (default: 5)
- `--dry-run` - Validate without making changes
- `--json` - JSON output for scripting

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

## Roadmap

### Current Features (v0.1.0)
- ✅ CLI baseline with Looker connectivity
- ✅ Content extraction (all types)
- ✅ Parallel extraction (8-10x speedup)
- ✅ Content restoration with dependency ordering
- ✅ Parallel restoration with DLQ and error recovery
- ✅ Resume capability for extraction and restoration
- ✅ Dead Letter Queue for failed items

### Future Features (Not Yet Implemented)

- 🌩 **Cloud Storage Integration**: Upload backups to S3, GCS, or Azure Blob Storage
- 🔄 **Cross-Instance Migration**: Restore content to different Looker instance with ID remapping
- 📊 **Backup Management**: List, compare, and manage backup snapshots over time
- 🔍 **Content Diff**: Compare backups and show changes between versions
- 🛡 **Automated Disaster Recovery**: Scheduled backups with automatic cloud upload
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
