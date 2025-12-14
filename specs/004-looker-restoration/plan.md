# Implementation Plan: Looker Content Restoration

**Branch**: `004-looker-restoration` | **Date**: 2025-12-13 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/004-looker-restoration/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

This feature enables restoration of Looker content from SQLite backups to Looker instances via API update/create operations. The system deserializes stored content, validates dependencies, issues PATCH (update) or POST (create) requests to the Looker API, and handles errors through retry logic and dead letter queue mechanisms. Restoration supports single-item testing for production safety, parallel bulk operations for performance, dependency-aware ordering, and cross-instance ID mapping for migration scenarios.

## Technical Context

**Language/Version**: Python 3.13
**Primary Dependencies**: looker-sdk (24.0.0+), typer, pydantic, tenacity, rich, msgspec
**Storage**: SQLite database (existing repository pattern with thread-local connections, BEGIN IMMEDIATE transactions)
**Testing**: pytest with coverage, pytest-mock for unit tests
**Target Platform**: CLI tool for Linux/macOS/Windows (cross-platform Python)
**Project Type**: Single project (CLI application)
**Performance Goals**: 100+ items/second restoration throughput with 8 parallel workers, <10 seconds for single-item restore
**Constraints**: API rate limiting (adaptive rate limiter coordination), thread-safe SQLite operations, memory-efficient streaming for large datasets
**Scale/Scope**: 50,000+ content items per restoration session, support for all 12 Looker content types, production-safe with granular testing interface

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Backup Integrity (NON-NEGOTIABLE)

| Requirement | Status | Implementation Notes |
|-------------|--------|---------------------|
| SQLite snapshots validated via checksum | ✅ PASS | Restoration reads from existing validated snapshots; no new checksum validation required for restore operation |
| Restore operations verify snapshot integrity | ✅ PASS | Deserialization from SQLite will validate data integrity; corrupted data triggers errors and skips |
| Data transformations reversible without loss | ✅ PASS | Deserialization reverses serialization (binary blob → Looker SDK objects); uses existing serializer.py |
| Failed operations atomic/clearly marked | ✅ PASS | Dead letter queue captures failures; checkpoints track completion; transactions ensure atomicity |

**Assessment**: ✅ COMPLIANT - All integrity requirements satisfied through existing infrastructure and new error handling.

### II. CLI-First Interface

| Requirement | Status | Implementation Notes |
|-------------|--------|---------------------|
| All operations exposed as CLI commands | ✅ PASS | `lookervault restore` command with subcommands for single/bulk/filtered restoration |
| Text-based I/O protocol | ✅ PASS | Args/stdin for input, stdout for results, stderr for errors (existing pattern) |
| Human-readable + JSON output formats | ✅ PASS | Rich library for human output, `--json` flag for machine-parseable format |
| Standard exit codes | ✅ PASS | 0 for success, non-zero for failures with meaningful error codes |
| Scriptable without user interaction | ✅ PASS | All operations non-interactive; confirmation flags for destructive operations |

**Assessment**: ✅ COMPLIANT - Follows existing CLI patterns established in extraction commands.

### III. Cloud-First Architecture

| Requirement | Status | Implementation Notes |
|-------------|--------|---------------------|
| Support for major cloud storage providers | ⚠️ NOT APPLICABLE | Restoration reads from local SQLite (already downloaded from cloud); cloud operations handled by separate backup/download features |
| Local disk operations ephemeral | ⚠️ NOT APPLICABLE | This feature operates on SQLite snapshots already staged locally; cloud download is separate concern |
| Cloud-native authentication | ⚠️ NOT APPLICABLE | This feature only interacts with Looker API (existing OAuth2); cloud auth handled by download/backup features |
| Handle cloud failures gracefully | ⚠️ NOT APPLICABLE | No direct cloud operations in restoration; API failures handled via retry/dead letter queue |
| Minimize storage costs via compression | ⚠️ NOT APPLICABLE | Restoration reads compressed data created by extraction; no new compression logic needed |

**Assessment**: ⚠️ NOT APPLICABLE - This feature focuses on Looker API restoration from local SQLite snapshots. Cloud storage operations are handled by separate features (backup/download). No cloud-first principle violations.

### Security Requirements

| Requirement | Status | Implementation Notes |
|-------------|--------|---------------------|
| No credentials in code/config files | ✅ PASS | Uses existing LookerClient credential handling (environment variables, credential files) |
| Support environment variables + IAM | ✅ PASS | Inherits existing Looker API credential patterns |
| Sensitive data in transit uses TLS/HTTPS | ✅ PASS | Looker SDK enforces HTTPS for all API calls |
| Looker API credentials handled securely | ✅ PASS | Uses existing config/validator.py patterns |
| Audit logging for operations | ⚠️ DEFERRED | Restoration sessions logged via ExtractionSession model; full audit logging to be added in future enhancement |

**Assessment**: ✅ COMPLIANT - Leverages existing secure credential handling. Audit logging partially satisfied via session tracking.

### Performance Standards

| Requirement | Status | Implementation Notes |
|-------------|--------|---------------------|
| Reasonable completion times | ✅ PASS | 50K items in <10 minutes (spec SC-008); single item <10 seconds (spec SC-001) |
| Incremental metadata collection | ⚠️ NOT APPLICABLE | Restoration operates on existing snapshots; incremental extraction is separate feature |
| Compression ratio targets | ⚠️ NOT APPLICABLE | Restoration reads existing compressed data; compression handled by extraction |
| Snapshot validation <30 seconds | ⚠️ NOT APPLICABLE | Validation occurs during download/backup; restoration assumes valid snapshot |
| Streaming to minimize memory | ✅ PASS | Content items processed one-at-a-time or in batches; no full dataset loaded into memory |
| Restore resumable after failures | ✅ PASS | Checkpoint-based resumption (spec FR-024) |
| Memory scales linearly with operations | ✅ PASS | Thread pool with bounded queue; memory footprint bounded by worker count, not dataset size |
| Disk space configurable | ⚠️ NOT APPLICABLE | Restoration operates on existing SQLite snapshots; disk space requirements same as extraction |
| Network bandwidth configurable | ✅ PASS | Adaptive rate limiting (existing) controls API request rate; configurable limits via CLI flags |

**Assessment**: ✅ COMPLIANT - Performance targets clearly defined and achievable with parallel architecture. Memory-efficient design using existing patterns.

### Overall Gate Status: ✅ PASS

**Summary**: This feature is fully compliant with LookerVault constitution. It operates on locally-staged SQLite snapshots (already validated by download/backup features), maintains data integrity through deserialization validation and atomicity, provides comprehensive CLI interface, and achieves performance targets through parallel execution. Cloud-first requirements are not applicable as this feature focuses on Looker API restoration rather than cloud storage operations.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/lookervault/
├── cli/
│   ├── commands/
│   │   └── restore.py              # NEW: CLI commands for restoration
│   ├── main.py                      # MODIFY: Register restore command
│   └── output.py                    # REUSE: Rich output formatting
│
├── restoration/                     # NEW: Restoration-specific logic
│   ├── __init__.py
│   ├── deserializer.py             # NEW: SQLite blob → Looker SDK objects
│   ├── restorer.py                 # NEW: Core restoration logic (update/create)
│   ├── dependency_graph.py         # NEW: Dependency ordering & validation
│   ├── id_mapper.py                # NEW: Source ID → Destination ID mapping
│   ├── dead_letter_queue.py        # NEW: Failed restoration tracking
│   ├── parallel_orchestrator.py    # NEW: Parallel restoration coordination
│   └── validation.py               # NEW: Pre-restoration validation
│
├── storage/
│   ├── models.py                   # MODIFY: Add RestorationSession, IDMapping, DeadLetterItem
│   ├── repository.py               # MODIFY: Add restoration-specific queries
│   └── schema.py                   # MODIFY: Add restoration tables
│
├── looker/
│   ├── client.py                   # REUSE: Existing Looker API client
│   └── extractor.py                # REUSE: For reference/comparison
│
├── extraction/                     # REUSE: Existing parallel infrastructure
│   ├── rate_limiter.py             # REUSE: Adaptive rate limiting
│   ├── metrics.py                  # REUSE: Thread-safe metrics
│   ├── retry.py                    # REUSE: Retry decorators
│   └── progress.py                 # REUSE: Progress tracking
│
└── exceptions.py                    # MODIFY: Add restoration-specific exceptions

tests/
├── unit/
│   ├── test_deserializer.py       # NEW: Deserialization unit tests
│   ├── test_restorer.py            # NEW: Restoration logic tests
│   ├── test_dependency_graph.py    # NEW: Dependency ordering tests
│   ├── test_id_mapper.py           # NEW: ID mapping tests
│   └── test_validation.py          # NEW: Validation tests
│
├── integration/
│   ├── test_single_restore.py      # NEW: Single-item restoration (P1)
│   ├── test_bulk_restore.py        # NEW: Bulk restoration (P2)
│   ├── test_parallel_restore.py    # NEW: Parallel restoration (P2)
│   └── test_id_mapping.py          # NEW: Cross-instance migration (P3)
│
└── fixtures/
    └── sample_content.py            # NEW: Sample Looker content for testing
```

**Structure Decision**: Single project structure following existing lookervault pattern. New `restoration/` module contains all restoration-specific logic, mirroring the `extraction/` module organization. Existing infrastructure (rate limiting, metrics, retry, SQLite repository) is reused. Tests organized by type (unit, integration) matching existing test patterns.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No constitution violations detected. All requirements satisfied through existing patterns and infrastructure.
