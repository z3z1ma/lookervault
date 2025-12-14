**Note**: This project uses [bd (beads)](https://github.com/steveyegge/beads) for issue tracking. Use `bd` commands instead of markdown TODOs. See AGENTS.md for workflow details.

## Package Management

**IMPORTANT**: This project uses `uv` for all Python package management operations.

- **DO NOT** use `pip install`, `pip freeze`, `virtualenv`, `poetry`, or similar tools
- **DO NOT** manually edit `[project]`, `[project.optional-dependencies]`, `[project.scripts]`, or `[build-system]` in pyproject.toml
- **DO** use `uv` commands exclusively:
  - `uv venv` - Create virtual environment
  - `uv add <package>` - Add dependency (manages pyproject.toml and uv.lock automatically)
  - `uv add --dev <package>` - Add dev dependency
  - `uv lock` - Update lockfile
  - `uv sync` - Sync environment with lockfile

**pyproject.toml**: Only manually edit `[tool.*]` sections (pytest, mypy, ruff, etc.). All dependencies and project metadata are managed by `uv add` commands.

## Code Conventions

### Absolute Imports

**IMPORTANT**: This project uses absolute imports exclusively.

- **DO** use absolute imports: `from lookervault.config.models import Configuration`
- **DO NOT** use relative imports: `from ..config.models import Configuration`

All imports should reference the full module path starting from the package root (`lookervault`). This improves code readability, makes refactoring easier, and prevents import errors when files are moved.

**Examples:**
```python
# Good - Absolute imports
from lookervault.config.models import Configuration, ConnectionStatus
from lookervault.looker.client import LookerClient
from lookervault.exceptions import ConfigError

# Bad - Relative imports (DO NOT USE)
from ..config.models import Configuration
from .client import LookerClient
from ...exceptions import ConfigError
```

## Code Quality Tools

This project uses modern Rust-based tools from [Astral](https://astral.sh) for code quality:

### Ruff - Linting and Formatting

**Ruff** is an extremely fast Python linter and code formatter written in Rust. It replaces multiple tools (Black, Flake8, isort, pylint, etc.) with a single, high-performance tool.

**Basic Commands:**
```bash
# Linting
ruff check                    # Lint all files in current directory
ruff check path/to/file.py    # Lint specific file
ruff check --fix              # Lint and auto-fix violations

# Formatting
ruff format                   # Format all files in current directory
ruff format path/to/file.py   # Format specific file
ruff format --check           # Check formatting without modifying files
ruff format --diff            # Show what would be formatted

# Using uvx (no installation required)
uvx ruff check
uvx ruff format
```

**Configuration:** Ruff is configured in `pyproject.toml` under `[tool.ruff]`, `[tool.ruff.lint]`, and `[tool.ruff.format]` sections.

**Key Features:**
- 10-100x faster than traditional Python linters
- Black-compatible code formatting
- 800+ lint rules with auto-fix support
- Native Jupyter Notebook support
- Drop-in replacement for Flake8, isort, and Black

### Ty - Type Checking

**Ty** is an extremely fast Python type checker and language server written in Rust, designed as a modern alternative to mypy.

**Basic Commands:**
```bash
# Type checking
ty check                      # Check entire project (auto-discovers pyproject.toml)
ty check path/to/file.py      # Check specific file
ty check src/ tests/          # Check specific directories
ty check --watch              # Watch mode (recheck on file changes)

# Output formats
ty check --output-format concise    # Concise output
ty check --output-format github     # GitHub Actions annotations
ty check --output-format gitlab     # GitLab Code Quality JSON

# Configuration
ty check --python-version 3.11      # Target specific Python version
ty check --python .venv/bin/python3 # Specify Python environment
ty check -vv                        # Verbose output for debugging

# Using uvx (no installation required)
uvx ty check
```

**Configuration:** Ty is configured in `pyproject.toml` under `[tool.ty]` section.

**Key Features:**
- Significantly faster than mypy (written in Rust)
- Built-in language server for IDE integration
- Watch mode for continuous type checking
- Multiple output formats for CI/CD integration
- Compatible with existing Python type hints

### Workflow Integration

**Development Workflow:**
1. Write code
2. Run `ruff format` to auto-format
3. Run `ruff check --fix` to lint and auto-fix issues
4. Run `ty check` to verify types
5. Run `uv run pytest` to ensure tests pass
6. Commit changes

**Pre-commit Integration:** Both tools work well in pre-commit hooks to ensure code quality before commits.

**Note:** Line length and formatting rules should be consistent between ruff's formatter and linter. Ruff makes a best-effort attempt to wrap lines at the configured `line-length`, but may exceed it in some cases.

## Pre-Commit Requirements

**CRITICAL**: No changes should be committed without running ALL of the following checks:

```bash
# Format code
uvx ruff format

# Lint and auto-fix issues
uvx ruff check --fix

# Type check
uvx ty check

# Run tests
uv run pytest
```

All checks must pass before committing. If any check fails, fix the issues before proceeding with the commit.

## Active Technologies
- Python 3.13 (per pyproject.toml) (002-looker-content-extraction)
- SQLite database with binary blob storage + metadata columns (002-looker-content-extraction)
- Python 3.13 + looker-sdk, typer, pydantic, tenacity, concurrent.futures (stdlib) (003-parallel-extraction)
- SQLite (existing repository pattern) (003-parallel-extraction)
- Python 3.13 + looker-sdk (24.0.0+), typer, pydantic, tenacity, rich, msgspec (004-looker-restoration)
- SQLite database (existing repository pattern with thread-local connections, BEGIN IMMEDIATE transactions) (004-looker-restoration)

## Recent Changes
- 004-looker-restoration: Added Looker content restoration with dependency ordering, parallel workers, DLQ error recovery, and checkpoint-based resume
- 003-parallel-extraction: Added parallel content extraction with thread pool, adaptive rate limiting, and resume capability
- 003-parallel-api-fetching: Parallelized Looker API calls using dynamic work stealing for 8-10x throughput improvement

## Parallel Content Extraction

The project supports parallel content extraction using a **dynamic work stealing** pattern that parallelizes Looker API calls. This feature significantly reduces extraction time for large Looker instances (10k+ items), achieving 400-600 items/second vs. ~50 items/second sequential.

### Key Features

1. **Parallel API Fetching**: Workers fetch data directly from Looker API in parallel (not just database writes)
2. **Dynamic Work Stealing**: Workers atomically claim offset ranges from a shared coordinator
3. **Adaptive Rate Limiting**: Automatically detects HTTP 429 responses and adjusts request rate across all workers
4. **Resume Capability**: Checkpoint-based resumption allows interrupted extractions to continue from last completed content type
5. **Thread-Safe SQLite**: Thread-local connections with BEGIN IMMEDIATE transactions prevent write contention
6. **Strategy Routing**: Automatically selects parallel or sequential strategy based on content type

### Architecture

**Two extraction strategies** based on content type:

#### Parallel Fetch Strategy (Paginated Types)
For paginated content types (dashboards, looks, users, groups, roles) with workers > 1:
- **Workers** (thread pool): Claim offset ranges, fetch from Looker API in parallel, save to database
- **OffsetCoordinator**: Thread-safe coordinator that atomically assigns offset ranges (0-100, 100-200, etc.)
- **Shared Rate Limiter**: Coordinates API rate limiting across all workers using sliding window algorithm
- **Thread-Safe Metrics**: Aggregates statistics (items processed, errors, throughput) safely across threads

**Flow**: Worker claims range → Fetches from API → Saves to DB → Claims next range (repeat until end)

#### Sequential Strategy (Non-Paginated Types)
For non-paginated content types (models, folders, boards, etc.) or single-worker mode:
- **Single Thread**: Fetches from API sequentially, saves to database directly
- Same checkpointing and error handling as parallel mode

### New Components

- `src/lookervault/extraction/offset_coordinator.py`: Thread-safe offset range coordinator
- `src/lookervault/looker/extractor.py`: Added `extract_range(offset, limit)` for parallel workers
- `src/lookervault/extraction/parallel_orchestrator.py`: Updated with parallel fetch workers

### Usage

```bash
# Parallel extraction with 8 workers (default)
lookervault extract --workers 8 dashboards

# High-throughput extraction (16 workers)
lookervault extract --workers 16 dashboards looks

# With custom rate limits (100 req/min, 10 req/sec burst)
lookervault extract --workers 8 --rate-limit-per-minute 100 --rate-limit-per-second 10

# Sequential extraction (backward compatible)
lookervault extract --workers 1 dashboards

# Resume interrupted extraction
lookervault extract --workers 8 --resume
```

### Performance Guidelines

- **Optimal Workers**: 8-16 workers provides best throughput for most use cases
- **API-Bound Scaling**: With parallel API fetching, throughput scales near-linearly with worker count up to 8 workers
- **SQLite Limit**: Beyond 16 workers, SQLite write contention plateaus throughput gains
- **Memory Usage**: No intermediate queue needed for parallel fetch, memory stays low regardless of worker count
- **Expected Throughput**:
  - **8 workers**: ~400 items/second (8x speedup)
  - **16 workers**: ~600 items/second (12x speedup)
  - **Sequential (1 worker)**: ~50 items/second
- **Large Datasets**: 10,000 items in ~15-25 seconds with 8-16 workers (vs. 3-4 minutes sequential)

### Thread Safety Implementation

All parallel extraction code follows strict thread-safety patterns:

- **Thread-Local Connections**: Each worker thread gets its own SQLite connection (`threading.local()`)
- **BEGIN IMMEDIATE Transactions**: Acquires write lock immediately to prevent deadlocks
- **SQLITE_BUSY Retry Logic**: Exponential backoff with jitter handles write contention gracefully
- **Thread-Safe Metrics**: All metrics use `threading.Lock` for safe concurrent access
- **Bounded Queue**: `queue.Queue` with maxsize provides backpressure and prevents memory issues

### Configuration Files

- `src/lookervault/extraction/parallel_orchestrator.py`: Main parallel extraction engine
- `src/lookervault/extraction/work_queue.py`: Thread-safe work distribution
- `src/lookervault/extraction/metrics.py`: Thread-safe metrics aggregation
- `src/lookervault/extraction/rate_limiter.py`: Adaptive rate limiting
- `src/lookervault/extraction/performance.py`: Performance tuning utilities and recommendations
- `src/lookervault/config/models.py`: `ParallelConfig` Pydantic model with validation
- `src/lookervault/storage/repository.py`: Thread-safe repository with retry logic

### Performance Tuning

The `PerformanceTuner` class provides automatic configuration recommendations:

```python
from lookervault.extraction.performance import PerformanceTuner

tuner = PerformanceTuner()
profile = tuner.recommend_for_dataset(total_items=50000, avg_item_size_kb=5.0)

print(f"Recommended workers: {profile.workers}")
print(f"Expected throughput: {profile.expected_throughput:.1f} items/sec")
```

The CLI automatically validates configurations and provides recommendations in verbose mode:

```bash
lookervault extract --workers 20 --verbose dashboards
# Will warn: "Worker count 20 exceeds SQLite write limit (16)"
# Will suggest: "Recommended: 16 workers (expected throughput: 500 items/sec)"
```

### Troubleshooting

**High worker count warnings**: If you see warnings about SQLite write contention (workers > 16), reduce worker count to 8-16 for optimal throughput.

**SQLITE_BUSY errors**: These are automatically retried with exponential backoff. If errors persist, reduce worker count or check database lock contention.

**Rate limit errors (HTTP 429)**: Adaptive rate limiting automatically slows down all workers when 429 detected. Gradual recovery occurs after sustained success.

**Memory issues**: Increase queue size or reduce batch size if memory usage is high (queue_size defaults to workers * 100).

---

## Looker Content Restoration

The project supports restoring Looker content from SQLite backups back to Looker instances with **dependency-aware ordering**, **parallel workers**, and **robust error recovery**. This feature enables disaster recovery, content migration, and safe production testing of restoration workflows.

### Key Features

1. **Single-Item Restoration**: Restore individual content items (dashboards, looks, etc.) for safe testing before bulk operations
2. **Dependency-Aware Bulk Restoration**: Automatically respects dependency order (Users → Groups → Folders → Models → Explores → Looks → Dashboards → Boards)
3. **Parallel Restoration**: Multi-worker restoration with shared rate limiting for high-throughput operations
4. **Smart Update/Create Logic**: Automatically updates existing content (PATCH) or creates new content (POST) based on destination state
5. **Resume Capability**: Checkpoint-based resumption allows interrupted restorations to continue from last completed item
6. **Dead Letter Queue (DLQ)**: Captures unrecoverable failures with full error context for manual review and retry
7. **Adaptive Rate Limiting**: Automatically detects HTTP 429 responses and adjusts request rate across all workers
8. **Dry Run Mode**: Validate restoration plan without making actual changes

### Architecture Highlights

**Core Components**:
- **LookerContentRestorer**: Single-item restoration with update/create logic and retry handling
- **ParallelRestorationOrchestrator**: Multi-worker coordinator with checkpointing and DLQ integration
- **DeadLetterQueue**: Captures and manages failed restoration attempts with retry capability
- **ContentDeserializer**: Deserializes binary SQLite blobs back into Looker SDK objects
- **DependencyGraph**: Hardcoded dependency relationships ensure proper restoration order

**Thread Safety**: Same patterns as extraction - thread-local SQLite connections, BEGIN IMMEDIATE transactions, shared rate limiter with atomic operations.

**Error Handling**: Transient errors (rate limits, network issues) are retried with exponential backoff. After max retries (default: 5), items move to DLQ for manual intervention.

### CLI Commands

```bash
# Single-item restoration (production-safe testing)
lookervault restore single dashboard <dashboard_id>
lookervault restore single look <look_id> --dry-run

# Bulk restoration of content type
lookervault restore bulk dashboards
lookervault restore bulk looks --workers 8 --rate-limit-per-minute 120

# Bulk restoration with parallel workers (high-throughput)
lookervault restore bulk dashboards --workers 16 --checkpoint-interval 100

# Resume interrupted restoration
lookervault restore resume dashboards
lookervault restore resume looks --session-id <session_id>

# Dead letter queue management
lookervault restore dlq list                          # List failed items
lookervault restore dlq list --session-id <id>        # Filter by session
lookervault restore dlq show <dlq_id>                 # Show error details
lookervault restore dlq retry <dlq_id>                # Retry single failed item
lookervault restore dlq clear --session-id <id> --force  # Clear DLQ entries

# Restoration session status
lookervault restore status                            # Show latest session
lookervault restore status --session-id <id>          # Show specific session
lookervault restore status --all                      # List all sessions

# Common options
--dry-run                    # Validate without making changes
--json                       # JSON output for scripting
--workers N                  # Parallel workers (default: 8)
--rate-limit-per-minute N    # API rate limit (default: 120)
--rate-limit-per-second N    # Burst limit (default: 10)
--checkpoint-interval N      # Save checkpoint every N items (default: 100)
--max-retries N              # Max retry attempts (default: 5)
```

### Usage Examples

**Production Testing Workflow**:
```bash
# 1. Test single dashboard restoration (dry run)
lookervault restore single dashboard abc123 --dry-run

# 2. Restore single dashboard for real
lookervault restore single dashboard abc123

# 3. Verify dashboard in Looker UI
# 4. If successful, proceed to bulk restoration
```

**Bulk Restoration Workflow**:
```bash
# 1. Restore users and groups (dependencies for content ownership)
lookervault restore bulk users --workers 8
lookervault restore bulk groups --workers 8

# 2. Restore folders (dependencies for content location)
lookervault restore bulk folders --workers 8

# 3. Restore content (dashboards, looks)
lookervault restore bulk looks --workers 16
lookervault restore bulk dashboards --workers 16

# 4. Check for failures
lookervault restore dlq list

# 5. Retry failed items after fixing issues
lookervault restore dlq retry <dlq_id>
```

**Interrupted Restoration Recovery**:
```bash
# Restoration interrupted after 5,000 of 10,000 dashboards
# Ctrl+C or network failure

# Resume from last checkpoint
lookervault restore resume dashboards

# System skips already-completed items and continues from item 5,001
```

### Performance Characteristics

- **Single-Item Restoration**: <10 seconds including dependency validation
- **Bulk Throughput**: 100+ items/second with 8 workers (API-bound, scales with worker count)
- **Large Datasets**: 50,000 items in <10 minutes with 8 workers (~83 items/sec minimum)
- **Resume Overhead**: Minimal - checkpoint queries use indexed lookups
- **Memory Usage**: Low and constant regardless of dataset size (streaming architecture)

**Optimal Configuration**:
- **8 workers**: Best balance of throughput and SQLite write contention for most use cases
- **16 workers**: Higher throughput for large datasets (600+ items/sec) if SQLite can handle write load
- **Checkpoint interval 100**: Good balance of resume granularity vs. database write overhead

### Dependency Restoration Order

Content is restored in this order to respect Looker's dependency relationships:

1. **Users** - Content ownership, permissions
2. **Groups** - Group membership, role assignments
3. **Roles** - Access control
4. **Permission Sets** - Fine-grained permissions
5. **Folders** - Content organization
6. **LookML Models** - Data models
7. **Explores** - Data exploration definitions
8. **Looks** - Saved queries
9. **Dashboards** - Dashboard definitions (reference looks)
10. **Boards** - Board definitions (reference dashboards)
11. **Scheduled Plans** - Scheduled deliveries (reference dashboards/looks)

**Note**: Dependency validation is currently limited to content type ordering. Future enhancements may add item-level dependency analysis.

### Configuration Options

**RestorationConfig** (Pydantic model):
- `workers`: Number of parallel workers (default: 8)
- `rate_limit_per_minute`: API rate limit (default: 120 req/min)
- `rate_limit_per_second`: Burst rate limit (default: 10 req/sec)
- `checkpoint_interval`: Save checkpoint every N items (default: 100)
- `max_retries`: Max retry attempts for transient errors (default: 5)
- `dry_run`: Validate without making changes (default: False)
- `skip_if_modified`: Skip items modified in destination since backup (default: False)

**Environment Variables**:
- `LOOKERVAULT_CLIENT_ID`: Looker API client ID (required)
- `LOOKERVAULT_CLIENT_SECRET`: Looker API client secret (required)
- `LOOKERVAULT_DB_PATH`: Path to SQLite database (optional, default: looker.db)

### Troubleshooting

**Rate limit errors (HTTP 429)**: Adaptive rate limiting automatically slows down all workers. If persistent, reduce `--rate-limit-per-minute` or `--rate-limit-per-second`.

**Validation errors**: Content schema validation failures indicate corrupted backup data or API version incompatibility. Check DLQ for full error details (`lookervault restore dlq show <id>`).

**Dependency errors**: If content references missing dependencies, check if referenced items exist in backup. Restore dependencies first (e.g., restore folders before dashboards).

**Resume not working**: Verify checkpoint exists (`lookervault restore status --all`). If checkpoint corrupted, delete session and restart restoration.

**High DLQ count**: Review error types (`lookervault restore dlq list`). Common causes: missing dependencies, API validation changes, permission issues, network failures.

### Important Notes

- **Same-Instance Only**: This implementation only supports restoring to the same Looker instance (IDs remain consistent). Cross-instance migration with ID remapping is not implemented.
- **Destructive Operations**: Restoration updates existing content without confirmation. Always test with `--dry-run` first or restore single items before bulk operations.
- **API Compatibility**: Content must be compatible with destination Looker version. API schema changes between versions may cause validation errors.
- **Credentials Required**: All restore commands require valid Looker API credentials (`LOOKERVAULT_CLIENT_ID`, `LOOKERVAULT_CLIENT_SECRET`).

### Design Documentation

For detailed design specifications, see:
- **Feature Spec**: `specs/004-looker-restoration/spec.md` - User stories, requirements, success criteria
- **Implementation Plan**: `specs/004-looker-restoration/plan.md` - Architecture, component design, integration contracts
- **Task Breakdown**: `specs/004-looker-restoration/tasks.md` - Implementation tasks and dependencies

**Recent Updates** (2025-12-13):
- Phase 3 complete: Single-item restoration (User Story 1)
- Phase 4 complete: Bulk restoration with dependency ordering (User Story 2)
- Phase 5 complete: Parallel restoration with DLQ and error recovery (User Story 3)
- Phase 6 skipped: Cross-instance ID mapping (not required for current use cases)