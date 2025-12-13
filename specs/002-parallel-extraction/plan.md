# Implementation Plan: Parallel Content Extraction

**Branch**: `002-parallel-extraction` | **Date**: 2025-12-13 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-parallel-extraction/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

Add configurable parallelism to Looker content extraction to handle tens of thousands of items efficiently. The system will support configurable thread pool size, distribute work across worker threads, handle API rate limiting coordination, and provide thread-safe checkpoint management. Target performance: extract 50,000 items in under 15 minutes with linear scaling up to 8 workers.

## Technical Context

**Language/Version**: Python 3.13
**Primary Dependencies**: looker-sdk, typer, pydantic, tenacity, concurrent.futures (stdlib)
**Storage**: SQLite (existing repository pattern)
**Testing**: pytest with pytest-cov, pytest-mock
**Target Platform**: Linux/macOS CLI (server/desktop environments)
**Project Type**: Single project (CLI tool)
**Performance Goals**:
- Extract 50,000 items in <15 minutes (10 workers)
- Linear scaling up to 8 workers
- 500+ items/second write throughput
- 80%+ thread pool utilization

**Constraints**:
- Memory usage <2GB regardless of thread pool size
- Thread-safe database writes (SQLite concurrency)
- API rate limit compliance with coordinated backoff
- Maintain existing checkpoint/resume functionality

**Scale/Scope**:
- Support 1-50 worker threads (configurable)
- Handle datasets of 100k+ items
- Coordinate multiple content types in parallel
- Thread-safe progress tracking across workers

**Technical Decisions (Resolved in Phase 0 Research)**:
- ✅ Threading model: **ThreadPoolExecutor** - I/O-bound tasks, native looker-sdk support, low memory overhead
- ✅ Work distribution: **Producer-Consumer Queue** - Best load balancing, checkpoint-compatible, moderate complexity
- ✅ Database concurrency: **Thread-local connections + WAL + BEGIN IMMEDIATE** - Prevents deadlocks, 500+ items/sec throughput
- ✅ Rate limiting: **Token Bucket (pyrate-limiter)** - Burst handling, thread-safe, adaptive backoff on HTTP 429
- ✅ Progress tracking: **threading.Lock + Rich multi-task Progress** - Low overhead, clear UI, thread-safe by design

See [research.md](./research.md) for detailed rationale and alternatives considered.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Backup Integrity (NON-NEGOTIABLE)

- ✅ **Data Fidelity**: Parallel extraction maintains existing integrity mechanisms (checksum validation, atomic operations)
- ✅ **No Data Loss**: Thread-safe writes ensure no corruption or race conditions during concurrent operations
- ✅ **Atomic Operations**: Failed parallel operations must roll back or clearly mark incomplete state (existing checkpoint system)
- ✅ **Reversibility**: Parallelism is an optimization layer - does not change data transformation logic

**Status**: PASS - Parallel extraction enhances performance without compromising existing integrity guarantees.

### II. CLI-First Interface

- ✅ **CLI Accessibility**: Thread pool size configurable via CLI option (e.g., `--workers N`)
- ✅ **Scriptable**: All parallel operations automatable without user interaction
- ✅ **Output Formats**: Maintains existing JSON/table output support with parallel progress reporting
- ✅ **Exit Codes**: Preserves standard exit code conventions (0 = success, non-zero = failure)
- ✅ **Text I/O**: Configuration via args, results to stdout, errors to stderr (no change to I/O protocol)

**Status**: PASS - Parallelism is configured via standard CLI patterns, fully scriptable.

### III. Cloud-First Architecture

- ✅ **Cloud Storage**: Parallel extraction writes to SQLite which backs up to cloud (no change to storage architecture)
- ✅ **Local Ephemeral**: Local SQLite staging remains ephemeral - cloud is source of truth
- ✅ **Failure Handling**: Existing retry logic and checkpoint/resume compatible with parallel workers
- ✅ **Compression**: Parallelism happens during extraction phase - compression before upload unchanged

**Status**: PASS - Parallel extraction optimizes the extraction phase before cloud upload, preserving cloud-first design.

### Performance Standards

- ✅ **Backup Operations**: Target <10 minutes for 1000 dashboards → parallelism directly supports this
- ✅ **Incremental Support**: Existing incremental mode compatible with parallel workers
- ✅ **Resource Constraints**: Memory scaling constraint explicitly addressed (<2GB regardless of workers)
- ✅ **Compression Ratio**: No change to compression (happens post-extraction)

**Status**: PASS - Parallel extraction enhances performance to meet constitution goals.

### Security Requirements

- ✅ **Credential Management**: No change to existing credential handling (workers share same authentication)
- ✅ **TLS/HTTPS**: API calls remain over HTTPS (no security model changes)
- ✅ **Encryption**: No change to encryption at rest or in transit

**Status**: PASS - Security model unchanged, parallelism is transparent to authentication/encryption.

### Overall Gate Status: ✅ PASS

All constitutional principles satisfied. Parallel extraction is an optimization layer that:
1. Preserves all integrity guarantees (atomic operations, checksums)
2. Maintains CLI-first interface (scriptable, standard I/O)
3. Respects cloud-first architecture (local staging → cloud backup)
4. Enhances performance to meet constitutional standards
5. Maintains existing security model

**No violations requiring justification in Complexity Tracking.**

## Project Structure

### Documentation (this feature)

```text
specs/002-parallel-extraction/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   └── parallel_config.schema.json  # CLI configuration schema
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/lookervault/
├── cli/
│   ├── commands/
│   │   └── extract.py           # [MODIFY] Add --workers option
│   └── output.py                # [MODIFY] Parallel progress display
├── extraction/
│   ├── orchestrator.py          # [MODIFY] Add parallel execution support
│   ├── batch_processor.py       # [EXISTING] Memory-aware batching
│   ├── progress.py              # [MODIFY] Thread-safe progress aggregation
│   ├── retry.py                 # [EXISTING] Retry logic
│   ├── parallel.py              # [NEW] Thread pool manager
│   ├── rate_limiter.py          # [NEW] Shared rate limiter
│   └── work_queue.py            # [NEW] Work distribution
├── storage/
│   └── repository.py            # [MODIFY] Thread-safe database operations
└── config/
    └── models.py                # [MODIFY] Add ParallelConfig

tests/
├── unit/
│   ├── extraction/
│   │   ├── test_parallel.py              # [NEW] Thread pool tests
│   │   ├── test_rate_limiter.py          # [NEW] Rate limiting tests
│   │   ├── test_work_queue.py            # [NEW] Work distribution tests
│   │   └── test_orchestrator_parallel.py # [NEW] Parallel orchestration tests
│   └── storage/
│       └── test_repository_concurrency.py # [NEW] Thread-safety tests
└── integration/
    └── test_parallel_extraction.py        # [NEW] End-to-end parallel tests
```

**Structure Decision**: Single project structure (Option 1). LookerVault is a CLI tool with a clear layered architecture:
- `cli/` - Command-line interface and user interaction
- `extraction/` - Core extraction logic (where parallelism is implemented)
- `storage/` - Data persistence layer (needs thread-safety enhancements)
- `config/` - Configuration models (add parallel config)

New modules in `extraction/` package:
- `parallel.py` - Thread pool lifecycle management
- `rate_limiter.py` - Coordinated API rate limiting across workers
- `work_queue.py` - Work distribution and load balancing

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations - all constitutional principles satisfied.

---

## Re-Evaluation After Phase 1 Design

**Date**: 2025-12-13
**Status**: ✅ PASS (Re-confirmed)

### Constitution Check Re-Validation

After completing Phase 0 (Research) and Phase 1 (Design), the parallel extraction feature continues to satisfy all constitutional principles:

**I. Backup Integrity (NON-NEGOTIABLE)** - ✅ PASS
- Thread-local SQLite connections with BEGIN IMMEDIATE prevent data corruption
- Existing checkpoint system preserved (content-type level granularity)
- Atomic operations maintained via transaction control
- No changes to serialization or data transformation logic

**II. CLI-First Interface** - ✅ PASS
- `--workers` CLI option for parallel configuration (validates range [1-50])
- Maintains scriptable automation (no interactive prompts)
- Preserves JSON/table output formats
- Standard exit codes (0 = success, non-zero = failure)

**III. Cloud-First Architecture** - ✅ PASS
- Parallel extraction optimizes local extraction phase only
- Cloud backup workflow unchanged (SQLite → compression → cloud upload)
- Local SQLite remains ephemeral staging
- No impact on cloud storage integration

**Performance Standards** - ✅ PASS
- Target: Extract 1000 dashboards in <10 minutes (parallelism achieves this)
- Memory constraint: <2GB with 10 workers (validated in design: ~1.1GB worst-case)
- Incremental mode supported (producer-consumer pattern compatible)

**Security Requirements** - ✅ PASS
- No changes to credential handling
- Workers share same authenticated Looker client
- TLS/HTTPS maintained for API calls
- Encryption at rest/in transit unchanged

### Design Validation

**Architecture Decisions Aligned with Constitution**:

1. **ThreadPoolExecutor** (not ProcessPoolExecutor):
   - Preserves single-process architecture (simpler, safer)
   - Thread-local SQLite connections maintain integrity
   - Low memory overhead supports <2GB constraint

2. **Producer-Consumer Pattern**:
   - Maintains existing checkpoint semantics (CLI-friendly resume)
   - Bounded queue prevents memory exhaustion (performance standard compliance)
   - Sequential API fetching respects rate limits (integrity preservation)

3. **Token Bucket Rate Limiting** (pyrate-limiter):
   - Prevents API abuse (security requirement)
   - Transparent to user (CLI-first: no manual intervention)
   - Adaptive backoff preserves extraction integrity

4. **Thread-Local Database Connections**:
   - Eliminates race conditions (backup integrity)
   - WAL mode already enabled (performance standard)
   - BEGIN IMMEDIATE prevents deadlocks (integrity guarantee)

**No New Constitutional Risks Introduced**: The parallel extraction layer is purely an optimization that:
- Operates below the CLI interface (transparent to users/scripts)
- Writes to same local SQLite staging (cloud-first architecture intact)
- Maintains all integrity checks (checksums, atomicity)
- Preserves security model (shared credentials, TLS)

### Final Gate Status: ✅ APPROVED FOR IMPLEMENTATION

All constitutional gates passed. Ready to proceed with `/speckit.tasks` to generate implementation tasks.
