# Implementation Plan: Base CLI with Looker Connectivity

**Branch**: `001-cli-baseline` | **Date**: 2025-12-13 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/001-cli-baseline/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

Build a foundational CLI tool that establishes LookerVault's baseline functionality: installation verification, configuration management, and Looker API connectivity validation. The CLI will provide help/version commands, readiness checks, and the ability to connect to a Looker instance to display basic instance information. This baseline enables all future backup/restore operations while ensuring adherence to the CLI-First Interface principle.

## Technical Context

**Language/Version**: Python 3.11+ (modern Python with async support)
**Package Manager**: uv (fast Rust-based package manager - replaces pip/poetry/virtualenv)
**Primary Dependencies**: Typer (CLI framework), looker-sdk (official Looker Python SDK), Pydantic (configuration validation), tomli-w (TOML writing)
**Storage**: Configuration files on disk (TOML format), no database required for baseline
**Testing**: pytest with pytest-mock for unit tests, pytest-httpx for API mocking
**Target Platform**: Cross-platform CLI (macOS, Linux, Windows) via Python
**Project Type**: Single project (CLI application)
**Performance Goals**: CLI commands respond in <1 second (excluding network I/O), Looker API connection attempts complete in <10 seconds
**Constraints**: No external dependencies beyond Python runtime, must work in restricted corporate environments (proxy-aware), memory footprint <50MB for baseline operations
**Scale/Scope**: Single-user CLI tool, supports multiple Looker instances via configuration profiles

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Backup Integrity (NON-NEGOTIABLE)
**Status**: ✅ NOT APPLICABLE (Baseline feature - no backup/restore operations)
**Notes**: This feature establishes CLI foundation only. Backup integrity will be enforced in future backup/restore features.

### II. CLI-First Interface
**Status**: ✅ PASS
**Compliance**:
- All operations exposed as CLI commands (help, version, check, info) ✅
- Text-based I/O: args/stdin input, stdout for results, stderr for errors (FR-014) ✅
- JSON output format supported (FR-013) ✅
- Standard exit codes (FR-007) ✅
- Fully scriptable and automatable ✅

### III. Cloud-First Architecture
**Status**: ✅ NOT APPLICABLE (Baseline feature - no cloud storage operations)
**Notes**: This feature only validates Looker connectivity. Cloud storage will be implemented in future backup/upload features.

### Security Requirements

**Credential Management**: ✅ PASS
- No credentials in code/version control (environment variables + config file) ✅
- Supports env vars (FR-004) and config files (FR-005) ✅
- TLS/HTTPS for Looker API connections (looker-sdk handles this) ✅

**Encryption**: ✅ NOT APPLICABLE (no data storage in baseline)

**Access Control**: ✅ NOT APPLICABLE (no sensitive operations in baseline)

### Performance Standards

**Backup Operations**: ✅ NOT APPLICABLE (no backups in baseline)

**Restore Operations**: ✅ NOT APPLICABLE (no restores in baseline)

**Resource Constraints**: ✅ PASS
- Memory usage <50MB (constraint documented in Technical Context) ✅
- Network bandwidth configurable via timeout settings ✅

### Gate Result: ✅ PASSED

All applicable constitutional requirements are satisfied. This feature is approved to proceed to Phase 0 research.

---

### Post-Design Re-Evaluation (After Phase 1)

**Date**: 2025-12-13

After completing Phase 1 design (data-model.md, contracts/, quickstart.md), the constitution compliance remains valid with the following confirmations:

**CLI-First Interface**:
- ✅ All commands defined in contracts/cli-commands.md follow text-based I/O protocol
- ✅ Both table and JSON output formats fully specified
- ✅ Exit codes documented and follow standard conventions (0, 1, 2, 3, 130)
- ✅ No GUI dependencies introduced
- ✅ Fully automatable via environment variables and JSON output

**Security Requirements - Credential Management**:
- ✅ Configuration model (data-model.md) shows credentials come from env vars or config file
- ✅ Config file example shows empty strings for secrets (must come from env vars)
- ✅ No credential defaults or hardcoded values in design
- ✅ Looker SDK configured to use TLS/HTTPS by default (verify_ssl=true)

**Performance Standards - Resource Constraints**:
- ✅ Design uses lazy-loading for Looker SDK (initialized on first use)
- ✅ Configuration loaded once and cached
- ✅ No large data structures in baseline feature
- ✅ Timeout configurations specified in data model (5-300 seconds)

**No New Violations Introduced**: The detailed design maintains all constitutional principles. The feature remains a minimal baseline with no complexity that would require justification.

**Final Gate Status**: ✅ PASSED - Ready for task generation and implementation

## Project Structure

### Documentation (this feature)

```text
specs/001-cli-baseline/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   └── cli-commands.md  # CLI command specifications
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/lookervault/
├── __init__.py
├── __main__.py          # Entry point for 'python -m lookervault'
├── cli/
│   ├── __init__.py
│   ├── main.py          # Typer app definition
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── info.py      # 'lookervault info' command
│   │   └── check.py     # 'lookervault check' command
│   └── output.py        # Output formatting (human-readable + JSON)
├── config/
│   ├── __init__.py
│   ├── models.py        # Pydantic config models
│   ├── loader.py        # Config loading (env vars + file)
│   └── validator.py     # Config validation logic
├── looker/
│   ├── __init__.py
│   ├── client.py        # Looker SDK client wrapper
│   └── connection.py    # Connection testing and status
└── exceptions.py        # Custom exception classes

tests/
├── unit/
│   ├── test_config_loader.py
│   ├── test_config_validator.py
│   ├── test_output_formatting.py
│   └── test_looker_client.py
├── integration/
│   ├── test_cli_commands.py
│   └── test_looker_connection.py
└── fixtures/
    ├── sample_config.toml
    └── mock_responses.py

pyproject.toml           # Project metadata and dependencies
uv.lock                  # Dependency lockfile (managed by uv)
README.md                # Installation and usage
.env.example             # Example environment variables
```

**Structure Decision**: Single project structure selected. LookerVault is a CLI application with no separate frontend/backend. The `src/lookervault/` directory follows modern Python packaging conventions with clear separation of concerns: CLI layer (commands, output), configuration layer (loading, validation), and Looker integration layer (client wrapper, connection testing).

**Package Management**: This project exclusively uses `uv` for all Python package operations (installation, dependency management, virtual environments). Do not use pip, poetry, or virtualenv.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations. This section is not needed.
