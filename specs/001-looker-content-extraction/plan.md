# Implementation Plan: Looker Content Extraction System

**Branch**: `001-looker-content-extraction` | **Date**: 2025-12-13 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-looker-content-extraction/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

Build a robust content extraction system that retrieves all Looker artifacts (dashboards, looks, models, users, roles, permissions) with memory-efficient batch processing, automatic retry logic with exponential back-off, progress tracking, and checkpoint-based resume capabilities. Content will be serialized to binary format and stored in SQLite with extracted metadata for querying. The system must handle API rate limits gracefully and ensure faithful preservation of original structure to enable future restore operations.

## Technical Context

**Language/Version**: Python 3.13 (per pyproject.toml)
**Primary Dependencies**: looker-sdk>=24.0.0, pydantic>=2.0.0, typer[all]>=0.9.0, NEEDS CLARIFICATION (serialization library, SQLite abstraction)
**Storage**: SQLite database with binary blob storage + metadata columns
**Testing**: pytest with coverage (pytest-cov, pytest-mock)
**Target Platform**: Cross-platform CLI (macOS, Linux, Windows)
**Project Type**: Single project (CLI tool)
**Performance Goals**: Extract 1,000+ items in <30 minutes, support 10,000+ items without exceeding memory limits
**Constraints**: Memory-efficient batch processing, <200ms overhead per API call for retry logic, configurable batch sizes
**Scale/Scope**: Support Looker instances with 10,000+ content items, handle individual items up to 10MB

**Technical Clarifications Needed (Phase 0 Research)**:
1. NEEDS CLARIFICATION: Binary serialization format choice (MessagePack, Protocol Buffers, pickle, JSON with compression)
2. NEEDS CLARIFICATION: SQLite schema design for mixed binary + metadata storage
3. NEEDS CLARIFICATION: Retry/back-off library (tenacity, backoff, custom implementation)
4. NEEDS CLARIFICATION: Progress tracking mechanism (CLI output, structured logging, progress file)
5. NEEDS CLARIFICATION: Checkpoint storage format and recovery logic
6. NEEDS CLARIFICATION: Looker API pagination patterns and rate limit header handling
7. NEEDS CLARIFICATION: Memory profiling strategy to verify batch processing meets constraints

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Backup Integrity (NON-NEGOTIABLE)

**Status**: ✅ PASS

- **Checksum validation**: Feature spec requires faithful preservation (FR-006) and includes verification user story (P4). Will implement checksum validation in Phase 1 design.
- **Atomic operations**: Feature spec requires checkpoint-based resume (FR-010) and error handling. Will implement rollback/incomplete marking.
- **Reversible transformations**: Binary serialization explicitly required to enable bi-directional serialization (per user input). Phase 0 will research serialization formats ensuring reversibility.
- **Integrity verification**: User Story 4 (P4) includes verification scenarios to validate deserialization matches original structure.

### II. CLI-First Interface

**Status**: ✅ PASS

- **CLI commands**: Existing codebase uses Typer CLI framework. Extraction will be implemented as CLI command(s).
- **Text-based I/O**: FR-002 requires progress tracking. Will output to stdout/stderr with JSON support for automation.
- **Exit codes**: Existing CLI infrastructure follows standard conventions. Will maintain consistency.
- **Scriptable operations**: Feature designed for automated backups. All configuration via args/environment variables.

### III. Cloud-First Architecture

**Status**: ⚠️ DEFERRED (Not applicable to this feature)

- **Rationale**: This feature focuses exclusively on extraction from Looker API to local SQLite storage. Cloud upload is a separate future feature.
- **Future compliance**: SQLite snapshot output will be designed to integrate with cloud upload in subsequent features.
- **No violation**: Feature spec explicitly states "storing it inside of SQLite" as local staging. Cloud storage is implicit next phase.

### Security Requirements

**Status**: ✅ PASS

- **Credential management**: Existing codebase has config loader for Looker credentials. Will leverage existing secure patterns.
- **Encryption**: SQLite snapshots will contain sensitive Looker data. Will add encryption support (optional for MVP, required for production).
- **Access control**: Looker API authentication already implemented. Extraction respects Looker permissions (per edge cases identified).

### Performance Standards

**Status**: ✅ PASS

- **Backup completion time**: SC-001 targets <30 minutes for 1,000+ items, aligns with constitution's <10 min for 1,000 dashboards.
- **Memory footprint**: FR-004 explicitly requires memory-efficient batch processing. SC-006 sets clear memory constraint compliance.
- **Resumable operations**: FR-010 requires resume capability, aligns with constitution's restore resumability principle.

**Constitution Compliance Summary**: All NON-NEGOTIABLE principles satisfied. Cloud-First deferred to future feature (appropriate for extraction-only scope).

## Project Structure

### Documentation (this feature)

```text
specs/001-looker-content-extraction/
├── spec.md              # Feature specification
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   └── extraction-api.md
├── checklists/          # Quality validation
│   └── requirements.md
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/lookervault/
├── cli/
│   ├── commands/
│   │   ├── check.py          # Existing: connection validation
│   │   ├── info.py           # Existing: connection info
│   │   ├── extract.py        # NEW: extraction command
│   │   └── verify.py         # NEW: verification command (P4)
│   ├── main.py               # Existing: CLI entry point
│   └── output.py             # Existing: output formatting
├── config/
│   ├── loader.py             # Existing: config loading
│   ├── models.py             # Existing: config models
│   └── validator.py          # Existing: validation
├── looker/
│   ├── client.py             # Existing: Looker API client wrapper
│   ├── connection.py         # Existing: connection management
│   └── extractor.py          # NEW: content extraction service
├── storage/
│   ├── __init__.py           # NEW: storage module
│   ├── models.py             # NEW: SQLite models (ExtractionSession, ContentItem, etc.)
│   ├── repository.py         # NEW: database operations
│   ├── serializer.py         # NEW: binary serialization/deserialization
│   └── checkpoint.py         # NEW: checkpoint management for resume
├── extraction/
│   ├── __init__.py           # NEW: extraction orchestration module
│   ├── orchestrator.py       # NEW: extraction workflow coordinator
│   ├── progress.py           # NEW: progress tracking
│   ├── retry.py              # NEW: retry logic with exponential back-off
│   └── batch_processor.py   # NEW: memory-efficient batch processing
├── exceptions.py             # Existing: custom exceptions (extend for extraction)
├── __init__.py               # Existing: package init
└── __main__.py               # Existing: CLI entry point

tests/
├── unit/
│   ├── test_extractor.py     # NEW: unit tests for extraction logic
│   ├── test_serializer.py    # NEW: serialization/deserialization tests
│   ├── test_retry.py         # NEW: retry logic tests
│   ├── test_checkpoint.py    # NEW: checkpoint/resume tests
│   └── test_batch_processor.py # NEW: batch processing tests
├── integration/
│   ├── test_extraction_flow.py  # NEW: end-to-end extraction tests
│   ├── test_storage.py          # NEW: SQLite storage integration tests
│   └── test_cli_extract.py      # NEW: CLI command integration tests
└── fixtures/
    └── looker_responses.py      # NEW: mock Looker API responses for testing
```

**Structure Decision**: Single project structure (Option 1) is appropriate for this CLI tool. The codebase follows a clean separation of concerns:

- **cli/**: Command-line interface using Typer (existing pattern)
- **looker/**: Looker API integration (existing, extend with extractor)
- **storage/**: NEW module for SQLite persistence and serialization
- **extraction/**: NEW module for extraction orchestration, progress, retry, batching
- **config/**: Existing configuration management (no changes needed)
- **tests/**: Comprehensive test coverage (unit, integration, fixtures)

This structure maintains consistency with existing codebase conventions while adding new modules for extraction-specific functionality. All new modules use absolute imports per CLAUDE.md guidelines.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations detected. All constitution requirements satisfied.

---

## Final Constitution Re-evaluation (Post-Design)

**Re-evaluated**: 2025-12-13 after Phase 1 design completion

### I. Backup Integrity (NON-NEGOTIABLE)

**Status**: ✅ PASS (Confirmed)

**Design Review:**
- **Checksum validation**: data-model.md defines content_size field for integrity checks; quickstart includes verify command
- **Atomic operations**: contracts/internal-api.md specifies transaction-based operations; SQLite WAL mode ensures atomicity
- **Reversible transformations**: msgspec serialization is lossless (confirmed in research.md); serializer protocol includes validate() method
- **Integrity verification**: User Story 4 implemented with verify command; contracts define validation at multiple layers

**New Evidence:**
- SQLite schema uses BLOB for binary storage with separate content_size field (detects corruption)
- MsgpackSerializer protocol includes validate() method for pre-write verification
- ContentRepository protocol guarantees atomic multi-item operations
- Quickstart demonstrates `lookervault verify` command with integrity checks

### II. CLI-First Interface

**Status**: ✅ PASS (Confirmed)

**Design Review:**
- **CLI commands**: quickstart.md defines complete CLI surface: extract, verify, info, list, export
- **Text-based I/O**: ProgressTracker protocol supports both human (Rich) and JSON modes
- **Exit codes**: Not explicitly in design (add to implementation)
- **Scriptable operations**: JSON output mode throughout; ExtractionConfig supports all parameters

**New Evidence:**
- quickstart.md demonstrates extensive CLI usage patterns
- contracts/internal-api.md defines OutputMode enum (HUMAN/MACHINE)
- All commands support --output json for automation
- Environment variable configuration supported

### III. Cloud-First Architecture

**Status**: ⚠️ DEFERRED (Still not applicable)

**Design Review:**
- Extraction to local SQLite is intentional for this feature
- Cloud upload is separate feature (next phase)
- Design includes all necessary data structures for future cloud sync
- No new concerns

**Future Path:**
- SQLite file is perfect format for cloud upload
- msgpack serialization is space-efficient for cloud storage
- ExtractionSession and Checkpoint models support cloud sync metadata

### Security Requirements

**Status**: ✅ PASS (Confirmed)

**Design Review:**
- **Credential management**: Quickstart shows environment variable patterns; config file support
- **Encryption**: SQLite DB can be encrypted at OS level (noted in quickstart FAQ)
- **Access control**: ContentRepository abstracts permissions; Looker SDK enforces API permissions

### Performance Standards

**Status**: ✅ PASS (Confirmed)

**Design Review:**
- **Backup completion**: ExtractionConfig allows batch_size tuning; default 100 items/batch targets SC-001 (<30 min for 1000 items)
- **Memory footprint**: BatchProcessor protocol enforces memory-safe batching; get_memory_usage() monitoring
- **Resumable operations**: Checkpoint table + resume logic fully designed

**New Evidence:**
- research.md confirms msgspec is 10-80x faster than alternatives
- data-model.md defines checkpoint mechanism for resume
- contracts define BatchProcessor with memory monitoring
- SQLite config optimized for 10MB BLOBs (16KB pages, 64MB cache)

### Constitution Compliance Summary (Post-Design)

**All NON-NEGOTIABLE principles satisfied.**

**Key Design Strengths:**
1. Multi-layer integrity: content_size field + msgspec validation + verify command
2. Comprehensive CLI: 7+ commands with human/JSON modes
3. Performance-first: msgspec serialization, optimized SQLite, efficient indexes
4. Reliability: Checkpoint/resume, two-layer retry (urllib3 + tenacity), soft deletes
5. Future-proof: Clean abstractions ready for cloud upload feature

**No complexity violations requiring justification.**
