# Implementation Plan: YAML Export/Import for Looker Content

**Branch**: `006-yaml-export-import` | **Date**: 2025-12-14 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/006-yaml-export-import/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

This feature adds `unpack` and `pack` CLI commands to LookerVault, enabling bidirectional conversion between SQLite binary MessagePack storage and human-editable YAML files. Users can export content to YAML, apply bulk modifications using standard text processing tools (sed, awk, Python scripts), and reimport changes back into the database for restoration to Looker. Two unpacking strategies are supported: (1) full export organizing all content by type, and (2) folder-based export mirroring Looker's folder hierarchy for dashboards and looks.

**Primary Use Case**: Extract Looker content snapshots to YAML → Modify YAML files in bulk using scripts → Repack to SQLite → Restore to Looker via existing `lookervault restore` command.

**Technical Approach**: Extend existing serialization layer (msgspec msgpack) to support YAML serialization/deserialization via PyYAML. Implement directory-based export/import workflows with metadata tracking for round-trip fidelity. Leverage existing repository pattern for database operations and content type abstractions.

## Technical Context

**Language/Version**: Python 3.13 (per pyproject.toml)
**Primary Dependencies**: msgspec (msgpack), PyYAML (new - YAML serialization), typer (CLI), pydantic (validation), rich (progress/output)
**Storage**: SQLite database with content_items table (existing schema), YAML files on filesystem (new)
**Testing**: pytest, pytest-cov, pytest-mock (existing test infrastructure)
**Target Platform**: Cross-platform CLI (Linux, macOS, Windows)
**Project Type**: Single CLI project (existing structure in `src/lookervault/`)
**Performance Goals**:
- Unpack 10,000 items in <5 minutes
- Pack 10,000 items in <10 minutes
- 100% round-trip fidelity (byte-for-byte identical after unpack → pack without modifications)
**Constraints**:
- Filesystem path limits (255 chars for folder names)
- YAML parsing performance (slower than msgpack, acceptable for batch operations)
- Memory usage must remain constant regardless of dataset size (streaming I/O)
**Scale/Scope**:
- Supports all 12 ContentType variants (dashboards, looks, users, groups, folders, boards, models, etc.)
- Handles databases with 10,000+ content items
- Supports folder hierarchies up to 50 nested levels

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Backup Integrity (NON-NEGOTIABLE)

| Check | Status | Justification |
|-------|--------|---------------|
| Round-trip fidelity preserved | ✅ PASS | FR-017 requires preservation of timestamps/metadata; SC-003 mandates 100% byte-for-byte fidelity for unmodified content |
| Validation before database writes | ✅ PASS | FR-009 requires YAML schema validation before pack operations; FR-014 provides dry-run mode |
| Atomic operations | ✅ PASS | FR-018 requires database transactions for pack operations; FR-019 detects concurrent modifications |
| Failed operations rolled back | ✅ PASS | Transaction-based pack (FR-018) ensures all-or-nothing updates; partial failures do not corrupt database |

### II. CLI-First Interface

| Check | Status | Justification |
|-------|--------|---------------|
| All features accessible via CLI | ✅ PASS | FR-001 (unpack command), FR-005 (pack command) expose all functionality via CLI |
| Machine-parseable output | ✅ PASS | Existing typer infrastructure supports --json flag; metadata.json provides structured export manifest |
| Scriptable without interaction | ✅ PASS | FR-014 dry-run mode; FR-015 progress indicators; no interactive prompts required |
| Standard exit codes | ✅ PASS | Existing CLI infrastructure (typer) follows standard conventions; errors propagate correctly |

### III. Cloud-First Architecture

| Check | Status | Justification |
|-------|--------|---------------|
| Cloud storage integration | ⚠️ INDIRECT | This feature operates on local SQLite databases (exported from cloud via existing snapshot commands); YAML exports are local ephemeral files for editing |
| Local disk is ephemeral | ✅ PASS | YAML exports are temporary working directories for bulk modifications, not permanent storage |
| Cloud credentials | N/A | Feature does not directly interact with cloud APIs (uses existing snapshot/restore for cloud integration) |
| Cloud failure handling | N/A | No direct cloud operations in this feature |

**Constitution Compliance Summary**: ✅ **PASSED**

All NON-NEGOTIABLE principles satisfied. Cloud-First Architecture is indirectly upheld since this feature operates on databases already managed via cloud snapshot workflows (005-cloud-snapshot-storage).

## Project Structure

### Documentation (this feature)

```text
specs/006-yaml-export-import/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output: YAML library evaluation, folder hierarchy algorithms
├── data-model.md        # Phase 1 output: Export metadata schema, YAML content structure
├── quickstart.md        # Phase 1 output: Common usage patterns and examples
├── contracts/           # Phase 1 output: YAML schema definitions, metadata format
│   ├── metadata-schema.yaml     # JSON schema for metadata.json
│   └── content-item-schema.yaml # YAML structure for content items
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/lookervault/
├── cli/
│   ├── commands/
│   │   ├── unpack.py         # NEW: Unpack command implementation
│   │   └── pack.py           # NEW: Pack command implementation
│   └── output.py             # EXISTING: Rich output formatting
├── export/                   # NEW: Export/import module
│   ├── __init__.py
│   ├── yaml_serializer.py    # NEW: YAML serialization/deserialization
│   ├── unpacker.py           # NEW: SQLite → YAML export logic
│   ├── packer.py             # NEW: YAML → SQLite import logic
│   ├── metadata.py           # NEW: Metadata file generation/parsing
│   ├── folder_tree.py        # NEW: Folder hierarchy construction
│   ├── validator.py          # NEW: YAML schema validation
│   └── query_remapper.py     # NEW: Dashboard query ID remapping
├── storage/
│   ├── repository.py         # EXISTING: Database operations (read/write)
│   ├── serializer.py         # EXISTING: Msgpack serialization
│   ├── models.py             # EXISTING: ContentItem, ContentType
│   └── schema.py             # EXISTING: SQLite schema
└── folder/
    └── hierarchy.py          # EXISTING: Folder hierarchy utilities

tests/
├── export/                   # NEW: Export/import tests
│   ├── test_yaml_serializer.py
│   ├── test_unpacker.py
│   ├── test_packer.py
│   ├── test_metadata.py
│   ├── test_folder_tree.py
│   ├── test_validator.py
│   └── test_query_remapper.py
├── integration/
│   ├── test_unpack_pack_roundtrip.py  # NEW: End-to-end round-trip tests
│   └── test_folder_hierarchy.py       # NEW: Folder strategy integration tests
└── fixtures/
    └── yaml_samples/         # NEW: Sample YAML files for testing
```

**Structure Decision**: Single CLI project structure (Option 1). New `export/` module added to `src/lookervault/` for all YAML export/import functionality. This follows existing patterns (e.g., `extraction/`, `restoration/`, `snapshot/` modules) and maintains separation of concerns. CLI commands in `cli/commands/` follow established conventions (e.g., `extract.py`, `restore.py`, `snapshot.py`).

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

*No violations detected - table omitted per instructions.*

## Phase 0: Research & Technical Investigation

**Objective**: Resolve technical unknowns and establish implementation patterns before detailed design.

### Research Questions

1. **YAML Library Selection**: Which Python YAML library provides best balance of performance, safety, and features?
   - **Options**: PyYAML (standard), ruamel.yaml (preserves formatting), strictyaml (schema validation)
   - **Criteria**: Round-trip fidelity, performance with large files, schema validation support, ecosystem maturity

2. **Folder Hierarchy Algorithm**: How to efficiently construct nested directory structure from flat folder ID relationships?
   - **Investigate**: Tree traversal algorithms, circular reference detection, orphaned item handling
   - **Performance**: Time complexity for 10,000 folders with 50-level nesting

3. **Query Remapping Strategy**: How to detect modified queries in YAML and generate new query IDs during pack?
   - **Approach**: Hash-based change detection vs. field-level comparison vs. YAML metadata tracking
   - **Challenge**: Shared queries across multiple dashboard elements

4. **YAML Schema Validation**: How to validate YAML against Looker SDK object schemas before database import?
   - **Options**: JSON Schema validation, Pydantic model validation, custom validators
   - **Integration**: Leverage existing Looker SDK type definitions

5. **Filesystem Sanitization**: How to handle special characters and path length limits in folder names?
   - **Investigate**: Cross-platform path sanitization (Windows vs Unix), collision handling, unicode support
   - **Edge Cases**: Folders with same name at different hierarchy levels

### Research Tasks

1. **Evaluate YAML libraries** (PyYAML vs ruamel.yaml vs strictyaml)
   - Benchmark serialization/deserialization performance on sample Looker dashboard JSON
   - Test round-trip fidelity for complex nested structures
   - Assess schema validation capabilities
   - **Deliverable**: Library recommendation with performance metrics

2. **Design folder hierarchy construction algorithm**
   - Implement tree builder from parent_id relationships (existing `folder/hierarchy.py`)
   - Add circular reference detection
   - Add orphaned item handling (items with missing parent_id)
   - Benchmark performance on 10,000 folder dataset
   - **Deliverable**: Algorithm pseudocode and complexity analysis

3. **Prototype query modification detection**
   - Implement hash-based change detection for query definitions
   - Handle shared query deduplication (multiple elements → same query)
   - Design query ID remapping table structure
   - **Deliverable**: Prototype code and test cases

4. **Establish YAML validation patterns**
   - Survey Looker SDK type definitions (looker_sdk.models)
   - Design Pydantic model wrappers for validation
   - Create validation pipeline (syntax → schema → business rules)
   - **Deliverable**: Validation architecture diagram

5. **Research filesystem path handling**
   - Survey cross-platform path sanitization libraries (pathvalidate, pathlib)
   - Define collision resolution strategy (append numeric suffix)
   - Test unicode handling on Windows/macOS/Linux
   - **Deliverable**: Sanitization function specification

**Output**: `research.md` with all findings and decisions documented.

## Phase 1: Design & Contracts

**Prerequisites**: `research.md` complete with library choices and algorithm decisions.

### 1.1 Data Model Design

**Task**: Define data structures for export metadata and YAML content format.

**Entities** (from spec.md):
- **Export Directory Structure**: Root + subdirectories + metadata.json
- **Metadata File**: Export manifest with schema version, timestamps, folder map
- **YAML Content File**: Individual content item with Looker SDK fields + internal metadata
- **Folder Hierarchy Map**: Folder ID → name/parent relationships
- **Query ID Remapping Table**: Old query ID → new query ID mapping

**Deliverable**: `data-model.md` with:
- Metadata file JSON schema (version, strategy, content_type_counts, folder_map, export_timestamp)
- YAML content file structure (SDK fields + `_metadata` section with db_id, content_type, exported_at)
- Query remapping table schema (in-memory during pack, optionally persisted)
- Folder tree node structure (id, name, parent_id, children, depth)

### 1.2 API Contracts

**Task**: Define CLI interfaces and data formats for unpack/pack commands.

**Deliverable**: `contracts/` directory with:

1. **CLI Command Schemas** (`cli-contracts.yaml`):
   ```yaml
   unpack:
     synopsis: "Extract binary MessagePack content to YAML files"
     options:
       --db-path: "Path to SQLite database (default: looker.db)"
       --output-dir: "Export directory path (required)"
       --strategy: "Export strategy: full | folder (default: full)"
       --content-types: "Filter by content types (comma-separated, optional)"
       --overwrite: "Overwrite existing export directory (default: false)"
       --json: "JSON output format (default: false)"

   pack:
     synopsis: "Import YAML files to binary MessagePack in SQLite"
     options:
       --input-dir: "Export directory path (required)"
       --db-path: "Path to SQLite database (required)"
       --dry-run: "Validate without writing to database (default: false)"
       --force: "Skip confirmation prompts (default: false)"
       --json: "JSON output format (default: false)"
   ```

2. **Metadata File Schema** (`metadata-schema.json`):
   ```json
   {
     "$schema": "http://json-schema.org/draft-07/schema#",
     "type": "object",
     "required": ["version", "export_timestamp", "strategy", "database_schema_version"],
     "properties": {
       "version": {"type": "string", "description": "Metadata format version (1.0.0)"},
       "export_timestamp": {"type": "string", "format": "date-time"},
       "strategy": {"enum": ["full", "folder"]},
       "database_schema_version": {"type": "integer"},
       "content_type_counts": {
         "type": "object",
         "patternProperties": {
           "^[A-Z_]+$": {"type": "integer"}
         }
       },
       "folder_map": {
         "type": "object",
         "description": "Only present for folder strategy",
         "patternProperties": {
           "^[0-9]+$": {
             "type": "object",
             "properties": {
               "id": {"type": "string"},
               "name": {"type": "string"},
               "parent_id": {"type": ["string", "null"]}
             }
           }
         }
       }
     }
   }
   ```

3. **YAML Content Item Schema** (`content-item-schema.yaml`):
   ```yaml
   # Example structure for dashboard YAML
   _metadata:
     db_id: "abc123"                  # Original database row ID
     content_type: "DASHBOARD"        # ContentType enum name
     exported_at: "2025-12-14T10:30:00Z"
     folder_path: "Sales/Regional/West"  # Only for folder strategy

   # Looker SDK fields (from Dashboard model)
   id: "42"
   title: "Sales Performance Dashboard"
   description: "Q4 sales metrics by region"
   user_id: "123"
   created_at: "2024-01-15T08:00:00Z"
   updated_at: "2025-12-10T14:22:00Z"
   folder_id: "789"
   dashboard_elements:
     - id: "elem1"
       query_id: "456"
       query:  # Embedded query definition
         model: "sales_model"
         view: "orders"
         fields: ["orders.count", "orders.total_revenue"]
         filters: {"orders.created_date": "30 days"}
   ```

### 1.3 Quickstart Guide

**Deliverable**: `quickstart.md` with:
- **Basic Workflow**: Extract → Modify → Repack → Restore
- **Example 1**: Full export/import with title modifications
- **Example 2**: Folder-based export with sed script
- **Example 3**: Query modification with Python script
- **Common Patterns**: Backup before pack, dry-run validation, folder filtering

### 1.4 Agent Context Update

**Task**: Run `.specify/scripts/bash/update-agent-context.sh claude` to update CLAUDE.md with new technologies.

**New Technologies to Add**:
- PyYAML (YAML serialization library)
- Export/import workflows (unpack/pack commands)
- Folder hierarchy mirroring

**Deliverable**: Updated `.claude/context.md` or `CLAUDE.md` with export/import module documentation.

## Phase 2: Implementation Tasks (Generated by /speckit.tasks)

*This section is intentionally left incomplete. The `/speckit.tasks` command will generate detailed implementation tasks in `tasks.md` based on this plan and the feature specification.*

**Expected Task Categories**:
1. **Phase 2.1**: YAML serialization infrastructure (yaml_serializer.py, validator.py)
2. **Phase 2.2**: Unpacker implementation (unpacker.py, metadata.py, folder_tree.py)
3. **Phase 2.3**: Packer implementation (packer.py, query_remapper.py)
4. **Phase 2.4**: CLI commands (unpack.py, pack.py)
5. **Phase 2.5**: Integration tests and documentation

## Integration Points

### Existing Components

1. **Storage Repository** (`storage/repository.py`):
   - **Reads**: `list_content()` for unpack - fetch all content by type
   - **Writes**: `save_content()` for pack - write modified content back
   - **Integration**: Unpacker reads from repository, Packer writes via repository

2. **Serialization Layer** (`storage/serializer.py`):
   - **Current**: MsgpackSerializer handles binary msgpack ↔ Python dict
   - **Extension**: New YamlSerializer mirrors interface for YAML ↔ Python dict
   - **Integration**: Unpacker uses both serializers (msgpack → dict → YAML), Packer reverses (YAML → dict → msgpack)

3. **Content Models** (`storage/models.py`):
   - **Use**: ContentType enum, ContentItem dataclass
   - **Integration**: YAML metadata references ContentType names; ContentItem structure informs YAML schema

4. **Folder Hierarchy** (`folder/hierarchy.py`):
   - **Existing**: Functions for building folder trees from parent_id relationships
   - **Integration**: Folder strategy unpacker uses hierarchy builder to construct directory tree

5. **CLI Infrastructure** (`cli/main.py`, `cli/output.py`):
   - **Existing**: Typer app registration, rich output formatting
   - **Integration**: Register new `unpack` and `pack` commands; use existing progress indicators

### New Component Interfaces

1. **YamlSerializer** (`export/yaml_serializer.py`):
   ```python
   class YamlSerializer:
       def serialize(self, data: dict[str, Any]) -> str:
           """Convert Python dict to YAML string."""

       def deserialize(self, yaml_str: str) -> dict[str, Any]:
           """Convert YAML string to Python dict."""

       def validate(self, yaml_str: str) -> bool:
           """Validate YAML syntax."""
   ```

2. **Unpacker** (`export/unpacker.py`):
   ```python
   class ContentUnpacker:
       def unpack_full(self, db_path: Path, output_dir: Path) -> ExportManifest:
           """Export all content organized by type."""

       def unpack_folder(self, db_path: Path, output_dir: Path) -> ExportManifest:
           """Export dashboards/looks in folder hierarchy."""
   ```

3. **Packer** (`export/packer.py`):
   ```python
   class ContentPacker:
       def pack(self, input_dir: Path, db_path: Path, dry_run: bool = False) -> PackResult:
           """Import YAML files to SQLite database."""

       def validate_export(self, input_dir: Path) -> ValidationResult:
           """Validate export directory structure and YAML files."""
   ```

4. **MetadataManager** (`export/metadata.py`):
   ```python
   class MetadataManager:
       def generate_metadata(self, strategy: str, content_counts: dict, folder_map: dict | None) -> dict:
           """Generate metadata.json content."""

       def load_metadata(self, export_dir: Path) -> ExportMetadata:
           """Load and parse metadata.json."""
   ```

## Testing Strategy

### Unit Tests

1. **YAML Serialization** (`test_yaml_serializer.py`):
   - Round-trip fidelity for complex nested structures
   - Unicode handling, special characters
   - Invalid YAML syntax handling
   - Large file performance (10MB+ YAML)

2. **Unpacker** (`test_unpacker.py`):
   - Full strategy: content organized by type
   - Folder strategy: nested directories match folder hierarchy
   - Metadata generation correctness
   - Edge cases: empty database, single item, 10,000 items

3. **Packer** (`test_packer.py`):
   - Full import: all content types
   - Partial import: folder strategy subset
   - Validation errors: invalid YAML, missing metadata
   - Dry-run mode: no database modifications

4. **Query Remapping** (`test_query_remapper.py`):
   - Modified query detection (hash-based)
   - New query ID generation
   - Shared query deduplication
   - Dashboard element reference updates

### Integration Tests

1. **Round-Trip Fidelity** (`test_unpack_pack_roundtrip.py`):
   - Export → Import without modifications = byte-for-byte identical
   - Test all 12 content types
   - Test 1,000+ item dataset
   - Measure performance (must meet <5min unpack, <10min pack targets)

2. **Folder Hierarchy** (`test_folder_hierarchy.py`):
   - Nested folders (50 levels)
   - Circular references detected
   - Orphaned items handled
   - Folder name sanitization (special chars, path limits)

3. **Bulk Modification Workflows** (`test_bulk_modifications.py`):
   - Sed script modification (title changes)
   - Python script modification (query filters)
   - Query remapping after modification
   - Validation after bulk changes

### Performance Benchmarks

- **10,000 items unpack**: <5 minutes
- **10,000 items pack**: <10 minutes
- **Memory usage**: <500MB constant regardless of dataset size
- **Folder hierarchy construction**: <30 seconds for 10,000 folders

## Risk Analysis

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| YAML parsing performance slower than msgpack | High | Medium | Acceptable for batch operations; document performance expectations; consider streaming for large files |
| Folder name collisions after sanitization | Medium | Medium | Append numeric suffix (folder_name_1, folder_name_2); preserve original names in metadata |
| Query remapping complexity with shared queries | Medium | High | Implement robust hash-based detection; extensive test coverage for edge cases; clear error messages |
| Filesystem path limits (255 chars) exceeded | Low | Medium | Truncate folder names with hash suffix to ensure uniqueness; warn user |
| Round-trip fidelity breaks with YAML formatting | Medium | High | Use consistent YAML formatting; avoid manual YAML edits to internal metadata; validation catches issues |
| Concurrent pack operations corrupt database | Low | High | Use database transactions (FR-018); detect concurrent modifications (FR-019); lock-based protection |

## Success Metrics (from Spec)

- **SC-001**: Users can unpack 10,000 items in <5 minutes ✅ Performance target
- **SC-002**: Users can pack 10,000 items in <10 minutes ✅ Performance target
- **SC-003**: Round-trip fidelity is 100% ✅ Integration test coverage
- **SC-004**: Bulk modifications (500+ dashboards) work correctly ✅ Integration test scenario
- **SC-005**: Folder hierarchy matches Looker 100% ✅ Folder strategy test
- **SC-006**: Validation errors are specific and actionable ✅ Error message quality
- **SC-007**: Query remapping succeeds 100% for valid modifications ✅ Unit test coverage
- **SC-008**: Typical workflow completes in <30 minutes ✅ End-to-end benchmark
- **SC-009**: Partial folder exports don't affect other content ✅ Integration test
- **SC-010**: Edge cases handled gracefully 100% ✅ Edge case test coverage

## Open Questions

*To be resolved during Phase 0 research:*

1. Should we support YAML → JSON conversion for compatibility with other tools?
2. Should metadata file be YAML or JSON? (Leaning JSON for machine-parseability)
3. Should we support incremental pack (only modified files) or always full rebuild?
4. Should folder strategy include non-folder content (users, groups) in a separate directory?
5. Should we add `--validate` subcommand for standalone YAML validation without pack?

## Next Steps

1. ✅ Complete this plan document
2. Run `/speckit.plan` Phase 0 to generate `research.md`
3. Resolve all research questions and finalize library choices
4. Run Phase 1 to generate `data-model.md`, `contracts/`, and `quickstart.md`
5. Update agent context with new export/import module documentation
6. Run `/speckit.tasks` to generate detailed implementation task breakdown in `tasks.md`
7. Begin Phase 2 implementation following task order in `tasks.md`
