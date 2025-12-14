# Implementation Plan: Cloud Snapshot Storage & Management

**Branch**: `005-cloud-snapshot-storage` | **Date**: 2025-12-13 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/005-cloud-snapshot-storage/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

This feature adds cloud-based snapshot management for LookerVault, enabling users to upload SQLite database snapshots to Google Cloud Storage with timestamped filenames, list and browse available snapshots, download snapshots for local restoration, and perform direct restoration from cloud snapshots. The implementation includes automatic retention policy enforcement to control storage costs and an optional interactive terminal UI for snapshot selection. The system ensures data integrity through checksum validation, provides robust error handling with retry logic, and integrates seamlessly with existing extraction and restoration workflows.

## Technical Context

**Language/Version**: Python 3.13
**Primary Dependencies**: google-cloud-storage (GCS SDK), typer (CLI), rich (UI/progress), tenacity (retry logic), pydantic (config validation)
**Storage**: Google Cloud Storage (GCS) buckets for snapshot storage; existing SQLite database for local operations
**Testing**: pytest with pytest-mock for mocking GCS operations, contract tests for GCS integration
**Target Platform**: Cross-platform CLI (Linux, macOS, Windows)
**Project Type**: Single project (CLI tool extending existing LookerVault codebase)
**Performance Goals**: Upload 100MB snapshot in <30s on standard broadband; list 100+ snapshots in <3s; download/restore in <5min for 100MB files
**Constraints**: Memory usage should scale with concurrent operations not data size; support compression (gzip) for cost reduction; handle network failures gracefully with retry logic
**Scale/Scope**: Support 100+ snapshots per bucket; handle database files up to 10GB; retention policies managing dozens of snapshots automatically

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Principle I: Backup Integrity (NON-NEGOTIABLE)

- ✅ **Checksum validation**: FR-003 requires file integrity verification after upload using checksums/ETags; FR-013 requires download integrity verification
- ✅ **Pre-restore validation**: FR-020 requires snapshot validation before beginning restore operations
- ✅ **Atomic operations**: FR-018 requires cleanup of temporary files; error handling with retry ensures partial operations don't corrupt state
- ✅ **Reversible transformations**: Compression (gzip) specified in constitution is lossless and reversible

**Status**: ✅ PASS - All backup integrity requirements satisfied

### Principle II: CLI-First Interface

- ✅ **CLI commands**: All operations exposed as CLI commands (upload, list, download, restore --from-snapshot)
- ✅ **Machine-parseable output**: FR-008 requires metadata display; can extend with --json flag for automation
- ✅ **Scriptable operations**: All operations automatable without user interaction except confirmation prompts (FR-014)
- ✅ **Exit codes**: Standard error handling with meaningful error messages (FR-004 retry logic, clear error reporting)

**Status**: ✅ PASS - CLI-first design maintained

### Principle III: Cloud-First Architecture

- ✅ **GCS support**: FR-002 specifies Google Cloud Storage as primary provider with extensible architecture
- ⚠️ **Multi-provider support**: Constitution requires S3/GCS/Azure support; current spec is GCS-only with future extensibility
- ✅ **Cloud as source of truth**: Local disk operations are ephemeral (FR-018 temporary files); cloud is primary storage
- ✅ **Native authentication**: FR-030 uses GOOGLE_APPLICATION_CREDENTIALS (GCS-native service account authentication)
- ✅ **Failure handling**: FR-004 requires retry logic with exponential backoff; FR-020 validates before operations
- ✅ **Compression for cost**: Constitution requires gzip compression; aligns with cost reduction goals (SC-008)

**Status**: ⚠️ PARTIAL - GCS-only implementation requires justification (see Complexity Tracking)

### Security Requirements

- ✅ **Credential management**: FR-030 uses environment variables (GOOGLE_APPLICATION_CREDENTIALS), no hardcoded credentials
- ✅ **Encryption at rest**: FR-033 requires using cloud provider's encryption features (GCS server-side encryption)
- ✅ **TLS/HTTPS**: GCS SDK uses HTTPS by default for all operations
- ✅ **Access control**: FR-034 validates cloud storage permissions before operations
- ✅ **Confirmation for destructive ops**: FR-014 requires confirmation before overwriting; retention policy has safety mechanism (FR-023)

**Status**: ✅ PASS - All security requirements satisfied

### Performance Standards

- ✅ **Backup time**: SC-001 targets <30s for 100MB upload (reasonable for typical broadband)
- ✅ **Validation time**: SC-002 targets <3s for listing 100+ snapshots (well under 30s requirement)
- ✅ **Resumable operations**: FR-004 retry logic provides resilience; SC-007 targets 80% automatic recovery
- ✅ **Memory scaling**: Constraint specified: memory scales with concurrent operations not data size
- ✅ **Resource constraints**: Upload/download progress feedback (FR-005, FR-015) for large files

**Status**: ✅ PASS - Performance standards met or exceeded

### Overall Gate Status

**Pre-Phase 0**: ⚠️ CONDITIONAL PASS - Requires justification for GCS-only implementation in Complexity Tracking

**Post-Phase 1**: ✅ PASS - Architecture designed for extensibility; GCS-only implementation justified for MVP

**Post-Phase 1 Re-evaluation**:
- ✅ **Backup Integrity**: Data model includes CRC32C checksum validation; contracts specify checksum verification for all operations
- ✅ **CLI-First Interface**: Complete CLI contract defined with JSON output, exit codes, and scriptability
- ✅ **Cloud-First**: GCS as primary backend with abstraction layer (`GCSStorageProvider`) allowing future multi-provider support
- ✅ **Security**: Encryption at rest via GCS, secure credential management via ADC, audit logging specified
- ✅ **Performance**: Compression, caching, and resumable uploads designed to meet performance targets

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
├── snapshot/                    # New: Cloud snapshot management module
│   ├── __init__.py
│   ├── client.py               # GCS client abstraction with retry logic
│   ├── uploader.py             # Snapshot upload with compression & checksum
│   ├── downloader.py           # Snapshot download with integrity verification
│   ├── lister.py               # List snapshots with caching & sequential indexing
│   ├── retention.py            # Retention policy enforcement (cleanup)
│   ├── models.py               # Pydantic models (SnapshotMetadata, RetentionPolicy, etc.)
│   └── ui.py                   # Interactive terminal UI (optional, P3)
├── cli/
│   ├── commands/
│   │   ├── snapshot.py         # New: CLI commands (upload, list, download, etc.)
│   │   ├── extract.py          # Existing
│   │   └── restore.py          # Modified: Add --from-snapshot flag
│   └── main.py                 # Register new snapshot command group
├── config/
│   └── models.py               # Modified: Add SnapshotConfig section
└── storage/
    └── repository.py           # Modified: Add methods for temporary snapshot operations

tests/
├── unit/
│   └── snapshot/               # New: Unit tests for snapshot module
│       ├── test_client.py
│       ├── test_uploader.py
│       ├── test_downloader.py
│       ├── test_lister.py
│       └── test_retention.py
├── integration/
│   └── test_snapshot_integration.py  # New: E2E tests with GCS emulator
└── contract/
    └── test_gcs_contract.py    # New: Contract tests for GCS integration
```

**Structure Decision**: Single project structure extending existing LookerVault CLI. New `snapshot/` module contains all cloud snapshot management logic. CLI commands added to existing `cli/commands/` directory. Integration with existing `restoration` module via `--from-snapshot` flag in restore command.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| GCS-only support (violates Constitution Principle III multi-provider requirement) | Faster initial delivery; user explicitly requested GCS; architecture designed for extensibility | Implementing all three providers (S3/GCS/Azure) simultaneously would delay MVP by 3-4x; abstract provider interface ensures adding S3/Azure is straightforward in future iterations; current user base uses GCP infrastructure |

## Phase Completion Summary

### Phase 0: Research ✅ COMPLETE

**Deliverables**:
- `research.md` - Comprehensive research findings covering:
  - Google Cloud Storage SDK integration patterns
  - Retention policy and cleanup strategies
  - Interactive terminal UI best practices

**Key Decisions**:
- Authentication: Application Default Credentials (ADC)
- Upload Strategy: Automatic resumable upload + gzip compression
- Integrity: CRC32C checksums for all operations
- Retention: GCS Lifecycle Management + Application-Level Enforcement
- UI Library: Rich (existing) + rich-menu for simple interactive selections

### Phase 1: Design & Contracts ✅ COMPLETE

**Deliverables**:
- `data-model.md` - Complete entity definitions:
  - SnapshotMetadata
  - RetentionPolicy
  - GCSStorageProvider
  - SnapshotConfig
- `contracts/cli-commands.md` - Full CLI interface specification:
  - 5 new snapshot commands (upload, list, download, delete, cleanup)
  - Modified restore command (--from-snapshot flag)
  - Error handling patterns
  - Exit code conventions
- `quickstart.md` - User-facing documentation:
  - 5-minute quick start
  - 5 common workflows
  - Troubleshooting guide
  - Best practices

**Architecture Highlights**:
- Extensible design with `GCSStorageProvider` abstraction
- Pydantic models for configuration validation
- Thread-safe operations aligned with existing extraction/restoration patterns
- Consistent CLI patterns matching existing LookerVault commands

### Constitution Compliance

**Pre-Phase 0 Status**: ⚠️ CONDITIONAL PASS
- Violation: GCS-only implementation (Constitution requires S3/GCS/Azure)
- Justification: Faster MVP delivery; architecture designed for extensibility

**Post-Phase 1 Status**: ✅ PASS
- All non-negotiable principles satisfied
- GCS-only implementation justified in Complexity Tracking
- Architecture allows adding S3/Azure in future iterations

### Next Steps

**Phase 2**: Generate `tasks.md` via `/speckit.tasks` command
- Break down implementation into dependency-ordered tasks
- Assign tasks to development phases (P1, P2, P3)
- Estimate complexity and identify dependencies

**Implementation**: Execute tasks via `/speckit.implement` command
- Implement P1 features (upload, list, download, restore from snapshot)
- Implement P2 features (retention policy enforcement, audit logging)
- Implement P3 features (interactive UI, advanced cleanup)

---

## References

- **Feature Specification**: [spec.md](./spec.md)
- **Research Findings**: [research.md](./research.md)
- **Data Model**: [data-model.md](./data-model.md)
- **CLI Contracts**: [contracts/cli-commands.md](./contracts/cli-commands.md)
- **Quickstart Guide**: [quickstart.md](./quickstart.md)
- **Constitution**: [../../.specify/memory/constitution.md](../../.specify/memory/constitution.md)
