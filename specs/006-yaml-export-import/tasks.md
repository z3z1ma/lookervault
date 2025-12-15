# Tasks: YAML Export/Import for Looker Content

**Input**: Design documents from `/specs/006-yaml-export-import/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: This feature does NOT explicitly request tests, so test tasks are OMITTED per template instructions.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `src/lookervault/`, `tests/` at repository root
- This project uses single CLI structure per plan.md

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and module structure for export/import functionality

- [X] T001 [P] Add PyYAML dependency to pyproject.toml using `uv add pyyaml`
- [X] T002 [P] Add ruamel.yaml dependency to pyproject.toml using `uv add ruamel.yaml` (per research.md decision)
- [X] T003 [P] Add pathvalidate dependency to pyproject.toml using `uv add pathvalidate` (for path sanitization)
- [X] T004 [P] Create export module directory structure: `src/lookervault/export/__init__.py`
- [X] T005 [P] Create test directory structure: `tests/export/`, `tests/integration/`
- [X] T006 [P] Create fixtures directory: `tests/fixtures/yaml_samples/`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core serialization and validation infrastructure that ALL user stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T007 [P] Implement YamlSerializer class in `src/lookervault/export/yaml_serializer.py` with serialize(), deserialize(), validate() methods using ruamel.yaml
- [X] T008 [P] Implement YamlContentMetadata dataclass in `src/lookervault/export/metadata.py` with fields: db_id, content_type, exported_at, content_size, checksum, folder_path
- [X] T009 [P] Implement ExportMetadata dataclass in `src/lookervault/export/metadata.py` with fields per metadata-schema.json
- [X] T010 [P] Implement MetadataManager class in `src/lookervault/export/metadata.py` with generate_metadata() and load_metadata() methods
- [X] T011 [P] Implement path sanitization utilities in `src/lookervault/export/path_utils.py` using pathvalidate with collision resolution (numeric suffixes)
- [X] T012 [P] Implement YamlValidator class in `src/lookervault/export/validator.py` with multi-stage validation pipeline (syntax → schema → SDK conversion)
- [X] T013 [P] Implement checksum utilities in `src/lookervault/export/checksum.py` with compute_export_checksum() using SHA-256
- [X] T014 Implement FolderTreeNode dataclass in `src/lookervault/export/folder_tree.py` with filesystem_path property and is_root method
- [X] T015 Implement FolderTreeBuilder class in `src/lookervault/export/folder_tree.py` with build_from_folders() method using BFS traversal with cycle detection (per research.md)

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Full Content Export/Import (Priority: P1) 🎯 MVP

**Goal**: Enable basic unpack/pack workflow for all content types organized by type, supporting bulk modifications and round-trip fidelity.

**Independent Test**: Extract database with mixed content types (dashboards, looks, users, folders), verify YAML files in type-based subdirectories, modify one YAML file, repack to new database, confirm modification persists.

### Implementation for User Story 1

#### Core Unpacker (Full Strategy)

- [X] T016 [P] [US1] Implement ContentUnpacker class skeleton in `src/lookervault/export/unpacker.py` with __init__ taking repository and yaml_serializer
- [X] T017 [US1] Implement ContentUnpacker.unpack_full() method in `src/lookervault/export/unpacker.py` - iterate all content types, create type subdirectories, export each item to <type>/<id>.yaml
- [X] T018 [US1] Add _metadata section generation in ContentUnpacker.unpack_full() - embed db_id, content_type, exported_at, content_size, checksum per data-model.md
- [X] T019 [US1] Implement progress tracking in ContentUnpacker.unpack_full() using rich progress bars (FR-015)
- [X] T020 [US1] Add metadata.json generation at export completion in ContentUnpacker.unpack_full() - call MetadataManager.generate_metadata() with strategy="full", content_type_counts, checksum

#### Core Packer (Full Strategy)

- [X] T021 [P] [US1] Implement ContentPacker class skeleton in `src/lookervault/export/packer.py` with __init__ taking repository and yaml_serializer
- [X] T022 [US1] Implement ContentPacker.pack() method in `src/lookervault/export/packer.py` - load metadata.json, discover YAML files, validate each file, deserialize to dict, extract _metadata, convert to ContentItem
- [X] T023 [US1] Add YAML validation in ContentPacker.pack() - call YamlValidator for syntax → schema → SDK conversion → business rules (FR-009)
- [X] T024 [US1] Implement database write logic in ContentPacker.pack() - use repository.save_content() with BEGIN IMMEDIATE transaction (FR-018)
- [X] T025 [US1] Add concurrent modification detection in ContentPacker.pack() - check database schema version, abort if mismatch (FR-019)
- [X] T026 [US1] Implement progress tracking in ContentPacker.pack() using rich progress bars (FR-015)
- [X] T027 [US1] Add checksum validation in ContentPacker.pack() - compare metadata.json checksum with recomputed value, warn if mismatch

#### CLI Commands

- [X] T028 [US1] Implement unpack CLI command in `src/lookervault/cli/commands/unpack.py` with --db-path, --output-dir, --strategy (default: full), --content-types, --overwrite, --json, --verbose options per cli-contracts.yaml
- [X] T029 [US1] Implement pack CLI command in `src/lookervault/cli/commands/pack.py` with --input-dir, --db-path, --dry-run, --force, --json, --verbose options per cli-contracts.yaml
- [X] T030 [US1] Register unpack and pack commands in `src/lookervault/cli/main.py` typer app
- [X] T031 [US1] Add --overwrite flag handling in unpack.py - check if output_dir exists, prompt or abort (exit code 2 per cli-contracts.yaml)
- [X] T032 [US1] Add --dry-run flag handling in pack.py - run validation pipeline without database writes (FR-014)
- [X] T033 [US1] Add --json output formatting in unpack.py and pack.py - output structured JSON per cli-contracts.yaml examples
- [X] T034 [US1] Add error handling and exit codes in unpack.py and pack.py per cli-contracts.yaml (0=success, 1=general error, 2=dir exists, 3=schema mismatch, 4=cycle detected, 5=transaction failed)

**Checkpoint**: At this point, User Story 1 should be fully functional - full strategy unpack/pack with round-trip fidelity

---

## Phase 4: User Story 2 - Folder Hierarchy Export/Import (Priority: P2)

**Goal**: Enable folder-based unpacking where dashboards/looks mirror Looker's folder hierarchy, improving navigation for folder-organized content.

**Independent Test**: Extract database with nested folders (e.g., "Marketing/Campaigns/Q4"), verify YAML files in matching nested directories, modify dashboard YAML in specific folder, repack, confirm change persists.

### Implementation for User Story 2

#### Folder Strategy Unpacker

- [X] T035 [P] [US2] Implement ContentUnpacker.unpack_folder() method in `src/lookervault/export/unpacker.py` - load all folders from database, build FolderTreeNode hierarchy using FolderTreeBuilder
- [X] T036 [US2] Add folder path construction in ContentUnpacker.unpack_folder() - for each dashboard/look, lookup folder_id in tree, get filesystem_path, create nested directories
- [X] T037 [US2] Add folder name sanitization in ContentUnpacker.unpack_folder() - call path_utils.sanitize_folder_name() for each folder level, store original_name in metadata if sanitized
- [X] T038 [US2] Add orphaned item handling in ContentUnpacker.unpack_folder() - items with missing/invalid folder_id go to _orphaned/ directory (per edge cases)
- [X] T039 [US2] Add circular reference detection in ContentUnpacker.unpack_folder() - use FolderTreeBuilder.detect_cycles(), report error with cycle path (exit code 4 per cli-contracts.yaml)
- [X] T040 [US2] Add folder_map generation in ContentUnpacker.unpack_folder() - populate ExportMetadata.folder_map with FolderInfo for each folder (id, name, parent_id, path, depth, child_count, original_name, sanitized)
- [X] T041 [US2] Update metadata.json generation for folder strategy - include folder_map, set strategy="folder"

#### Folder Strategy Packer

- [X] T042 [US2] Implement folder strategy detection in ContentPacker.pack() - load metadata.json, check strategy field, branch to folder-specific logic if strategy="folder"
- [X] T043 [US2] Add folder hierarchy reconstruction in ContentPacker.pack() for folder strategy - load folder_map from metadata.json, map YAML file paths to folder_id using FolderInfo.path
- [X] T044 [US2] Add folder validation in ContentPacker.pack() for folder strategy - verify folder_id references exist in folder_map, warn for orphaned items

#### CLI Integration

- [X] T045 [US2] Update unpack.py to support --strategy folder flag - call ContentUnpacker.unpack_folder() instead of unpack_full()
- [X] T046 [US2] Add folder strategy validation in unpack.py - ensure database contains folders before allowing folder strategy, error if no folders found
- [X] T047 [US2] Add folder strategy output formatting in unpack.py --json mode - include folder_map summary in JSON output

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently - full strategy and folder strategy

---

## Phase 5: User Story 3 - Bulk Content Modification via Scripts (Priority: P1)

**Goal**: Validate that bulk modifications (sed, awk, Python scripts) work correctly with unpack → modify → pack → restore workflow.

**Independent Test**: Export dashboards, run script to modify specific YAML field (e.g., title changes), repack, extract from new database, verify all modifications applied.

### Implementation for User Story 3

#### Modification Detection

- [X] T048 [P] [US3] Implement modification tracking in ContentPacker.pack() - compare YAML file timestamps with exported_at from _metadata, track modified vs unchanged items
- [X] T049 [US3] Add selective repacking logic in ContentPacker.pack() - only write modified items to database, skip unchanged items (FR-020)
- [X] T050 [US3] Add modification summary in pack output - report counts: created, updated, unchanged, errors

#### Validation Enhancements

- [X] T051 [P] [US3] Add field-level validation in YamlValidator - validate common bulk edit patterns (title changes, model references, filter values) against Looker SDK schemas
- [X] T052 [US3] Add detailed error reporting in YamlValidator - include file path, line number, field name, expected type, actual value for all validation failures (SC-006)
- [X] T053 [US3] Add validation error aggregation in ContentPacker.pack() - collect all validation errors before aborting, display grouped by error type

#### Script Integration Examples

- [X] T054 [US3] Add example Python script in `tests/fixtures/scripts/update_filters.py` - modify query filters in dashboard YAMLs (per quickstart.md Example 2)
- [X] T055 [US3] Add example sed script in `tests/fixtures/scripts/update_titles.sh` - modify dashboard titles (per quickstart.md Example 1)
- [X] T056 [US3] Add example awk script in `tests/fixtures/scripts/replace_models.sh` - replace LookML model references (per quickstart.md Example 3)

**Checkpoint**: At this point, bulk modification workflows should be validated and examples documented

---

## Phase 6: User Story 4 - Dashboard Query Modification with ID Remapping (Priority: P3)

**Goal**: Handle dashboard query modifications by detecting changes, creating new query objects, and remapping IDs automatically.

**Independent Test**: Export dashboard with 3 elements, modify query definition in one element's YAML (change dimensions), repack, verify dashboard element references newly created query ID.

### Implementation for User Story 4

#### Query Remapping Infrastructure

- [X] T057 [P] [US4] Implement QueryRemapEntry dataclass in `src/lookervault/export/query_remapper.py` with fields: original_query_id, new_query_id, query_hash, dashboard_element_ids, created_at
- [X] T058 [P] [US4] Implement QueryRemappingTable class in `src/lookervault/export/query_remapper.py` with entries dict, hash_index dict, get_or_create() method, _hash_query() using SHA-256
- [X] T059 [US4] Implement query hash computation in QueryRemappingTable._hash_query() - normalize query dict (sort keys, canonical JSON), compute SHA-256 hash (per research.md)
- [X] T060 [US4] Implement shared query deduplication in QueryRemappingTable.get_or_create() - check hash_index for existing new_query_id, reuse if found, otherwise mark for creation

#### Query Modification Detection

- [X] T061 [US4] Add query modification detection in ContentPacker.pack() for dashboard items - compare query definition hash with original, detect changes
- [X] T062 [US4] Implement new query creation logic in ContentPacker.pack() - for modified queries, generate new_query_id, store in QueryRemappingTable, update dashboard_element.query_id
- [X] T063 [US4] Add query reference updating in ContentPacker.pack() - for all dashboard_elements referencing modified query, update query_id to new_query_id from remapping table
- [X] T064 [US4] Add query remapping table persistence in ContentPacker.pack() - optionally write QueryRemappingTable to <input_dir>/.pack_state/query_remapping.json for debugging

#### Validation and Error Handling

- [X] T065 [US4] Add query validation in YamlValidator - validate query definitions against Looker SDK Query model schema, check required fields (model, view, fields)
- [X] T066 [US4] Add query creation failure handling in ContentPacker.pack() - if query validation fails, report clear error with query definition and missing fields (AS-4 from spec.md)
- [X] T067 [US4] Add query remapping summary in pack output - report: modified queries detected, new queries created, shared queries deduplicated

**Checkpoint**: All user stories should now be independently functional - query remapping completes advanced editing workflows

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories, documentation, and edge case handling

### Performance Optimization

- [ ] T068 [P] Add streaming I/O for large YAML files in YamlSerializer - process files in chunks to maintain constant memory usage (per performance constraints)
- [ ] T069 [P] Add batch commits in ContentPacker.pack() - commit every 100 items to balance performance and atomicity (per data-model.md)
- [ ] T070 [P] Add parallel file discovery in ContentUnpacker - use concurrent glob patterns for multiple content types simultaneously

### Edge Case Handling

- [ ] T071 [P] Add disk space pre-flight check in ContentUnpacker.unpack_full() and unpack_folder() - estimate required space, warn if insufficient (per edge cases)
- [ ] T072 [P] Add filesystem error handling in ContentUnpacker - catch PermissionError, OSError, report clear errors with file paths
- [ ] T073 [P] Add missing file handling in ContentPacker.pack() - detect YAML files deleted from export directory, optionally delete from database with --force flag
- [ ] T074 [P] Add path length limit handling in path_utils.sanitize_folder_name() - truncate to 255 chars with hash suffix, preserve uniqueness (per data-model.md)
- [ ] T075 [P] Add unicode normalization in path_utils.sanitize_folder_name() - use NFC normalization for cross-platform compatibility (per research.md)

### Documentation

- [ ] T076 [P] Add docstrings to all export/ module classes and methods - include examples for YamlSerializer, ContentUnpacker, ContentPacker
- [ ] T077 [P] Add inline comments for complex algorithms - FolderTreeBuilder BFS traversal, QueryRemappingTable hash-based deduplication
- [ ] T078 [P] Update CLAUDE.md with export/import module documentation - describe unpacker/packer architecture, YAML serialization patterns
- [ ] T079 Create user-facing README for export/import feature - link to quickstart.md, data-model.md, cli-contracts.yaml

### Validation and Testing

- [ ] T080 [P] Add round-trip fidelity validation script in `tests/scripts/validate_roundtrip.py` - unpack → pack → compare checksums, verify 100% fidelity (SC-003)
- [ ] T081 [P] Add performance benchmark script in `tests/scripts/benchmark_export_import.py` - measure unpack/pack times for 1k, 10k, 50k items, verify <5min/<10min targets (SC-001, SC-002)
- [ ] T082 Add edge case validation in quickstart.md - document all edge cases from spec.md with expected behaviors

### Code Quality

- [ ] T083 Run uvx ruff format on all new files in `src/lookervault/export/` and `src/lookervault/cli/commands/unpack.py` and `pack.py`
- [ ] T084 Run uvx ruff check --fix on all new files to fix linting violations
- [ ] T085 Run uvx ty check to verify type safety for all new modules
- [ ] T086 Review and fix any type errors or warnings from ty check

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational (Phase 2) - Foundation for all other stories
- **User Story 2 (Phase 4)**: Depends on Foundational (Phase 2) - Can start independently after foundation
- **User Story 3 (Phase 5)**: Depends on User Story 1 (Phase 3) - Needs basic unpack/pack workflow
- **User Story 4 (Phase 6)**: Depends on User Story 1 (Phase 3) - Needs basic packer with dashboard support
- **Polish (Phase 7)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - No dependencies on other stories - **THIS IS THE MVP**
- **User Story 2 (P2)**: Can start after Foundational (Phase 2) - Independent of US1 but builds on same infrastructure
- **User Story 3 (P1)**: Depends on User Story 1 - Validates bulk modification workflows on top of basic unpack/pack
- **User Story 4 (P3)**: Depends on User Story 1 - Extends packer with query remapping logic

### Within Each User Story

**User Story 1 (Full Export/Import)**:
- T016-T020: Core unpacker (can parallelize T016, T017)
- T021-T027: Core packer (depends on unpacker being functional)
- T028-T034: CLI commands (depends on both unpacker and packer)

**User Story 2 (Folder Hierarchy)**:
- T035-T041: Folder unpacker (depends on T014-T015 from Foundational)
- T042-T044: Folder packer (depends on folder unpacker)
- T045-T047: CLI integration (depends on folder packer)

**User Story 3 (Bulk Modifications)**:
- T048-T050: Modification detection (extends US1 packer)
- T051-T053: Validation enhancements (parallel with modification detection)
- T054-T056: Script examples (parallel, independent documentation)

**User Story 4 (Query Remapping)**:
- T057-T060: Remapping infrastructure (can parallelize T057, T058)
- T061-T064: Modification detection and remapping (depends on infrastructure)
- T065-T067: Validation and error handling (parallel with T061-T064)

### Parallel Opportunities

**Setup (Phase 1)**: All tasks T001-T006 can run in parallel (marked with [P])

**Foundational (Phase 2)**: Tasks T007-T013 can run in parallel (marked with [P]); T014-T015 must run sequentially after T014

**User Story 1**:
- Parallel: T016 (unpacker skeleton), T021 (packer skeleton)
- Parallel: T028 (unpack CLI), T029 (pack CLI)
- Parallel: T031-T034 (CLI feature flags)

**User Story 2**:
- Parallel: T035 (folder unpacker), T042 (folder packer skeleton)
- Parallel: T045-T047 (CLI integration tasks)

**User Story 3**:
- Parallel: T048 (modification tracking), T051 (field validation), T054-T056 (script examples)

**User Story 4**:
- Parallel: T057 (QueryRemapEntry), T058 (QueryRemappingTable)
- Parallel: T065 (query validation), T066 (error handling)

**Polish (Phase 7)**:
- All tasks T068-T086 can run in parallel except T083-T086 which must run sequentially

---

## Parallel Example: User Story 1

```bash
# Launch core components in parallel:
Task: "T016 [P] [US1] Implement ContentUnpacker class skeleton"
Task: "T021 [P] [US1] Implement ContentPacker class skeleton"

# After unpacker/packer are functional, launch CLI commands in parallel:
Task: "T028 [US1] Implement unpack CLI command"
Task: "T029 [US1] Implement pack CLI command"

# Launch CLI feature flags in parallel:
Task: "T031 [US1] Add --overwrite flag handling"
Task: "T032 [US1] Add --dry-run flag handling"
Task: "T033 [US1] Add --json output formatting"
Task: "T034 [US1] Add error handling and exit codes"
```

---

## Parallel Example: Foundational Phase

```bash
# Launch all independent foundation components in parallel:
Task: "T007 [P] Implement YamlSerializer class"
Task: "T008 [P] Implement YamlContentMetadata dataclass"
Task: "T009 [P] Implement ExportMetadata dataclass"
Task: "T010 [P] Implement MetadataManager class"
Task: "T011 [P] Implement path sanitization utilities"
Task: "T012 [P] Implement YamlValidator class"
Task: "T013 [P] Implement checksum utilities"

# After above complete, launch folder tree components sequentially:
Task: "T014 Implement FolderTreeNode dataclass"
Task: "T015 Implement FolderTreeBuilder class" # Depends on T014
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. ✅ Complete Phase 1: Setup (T001-T006) - 6 tasks
2. ✅ Complete Phase 2: Foundational (T007-T015) - 9 tasks
3. ✅ Complete Phase 3: User Story 1 (T016-T034) - 19 tasks
4. **STOP and VALIDATE**: Test full strategy unpack/pack independently
5. Deploy/demo if ready

**MVP Deliverable**: Basic unpack/pack commands with full strategy, round-trip fidelity, bulk modification support

**Total MVP Tasks**: 34 tasks

### Incremental Delivery

1. Complete Setup + Foundational (T001-T015) → Foundation ready - **15 tasks**
2. Add User Story 1 (T016-T034) → Test independently → Deploy/Demo (MVP!) - **19 tasks**
3. Add User Story 2 (T035-T047) → Test independently → Deploy/Demo (folder hierarchy) - **13 tasks**
4. Add User Story 3 (T048-T056) → Test independently → Deploy/Demo (bulk modifications) - **9 tasks**
5. Add User Story 4 (T057-T067) → Test independently → Deploy/Demo (query remapping) - **11 tasks**
6. Add Polish (T068-T086) → Final release - **19 tasks**

**Total Feature Tasks**: 86 tasks

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together (T001-T015)
2. Once Foundational is done:
   - Developer A: User Story 1 (T016-T034) - Core unpack/pack
   - Developer B: User Story 2 (T035-T047) - Folder hierarchy (starts after US1 core infrastructure)
   - Developer C: User Story 4 (T057-T067) - Query remapping (starts after US1 packer)
3. Developer A finishes US1 → picks up User Story 3 (T048-T056)
4. Team completes Polish together (T068-T086)

---

## Task Summary

**Total Tasks**: 86 tasks

**Tasks by Phase**:
- Phase 1 (Setup): 6 tasks
- Phase 2 (Foundational): 9 tasks
- Phase 3 (User Story 1 - P1): 19 tasks 🎯 MVP
- Phase 4 (User Story 2 - P2): 13 tasks
- Phase 5 (User Story 3 - P1): 9 tasks
- Phase 6 (User Story 4 - P3): 11 tasks
- Phase 7 (Polish): 19 tasks

**Tasks by User Story**:
- US1 (Full Content Export/Import): 19 tasks
- US2 (Folder Hierarchy Export/Import): 13 tasks
- US3 (Bulk Content Modification): 9 tasks
- US4 (Dashboard Query Modification): 11 tasks
- Foundation + Setup: 15 tasks
- Polish: 19 tasks

**Parallel Opportunities**:
- Setup phase: 6 parallel tasks (T001-T006)
- Foundational phase: 7 parallel tasks (T007-T013)
- User Story 1: 4 parallel opportunities (T016+T021, T028+T029, T031-T034)
- User Story 2: 3 parallel opportunities (T035+T042, T045-T047)
- User Story 3: 5 parallel opportunities (T048+T051, T054-T056)
- User Story 4: 4 parallel opportunities (T057+T058, T065+T066)
- Polish phase: 18 parallel tasks (T068-T082, T083-T086 sequential)

**Independent Test Criteria**:
- ✅ US1: Unpack → modify YAML → pack → verify modification in new database
- ✅ US2: Unpack with folder strategy → verify nested directories → modify → pack → verify change persists
- ✅ US3: Bulk script modification (sed/awk/Python) → pack → verify all changes applied
- ✅ US4: Modify query in dashboard YAML → pack → verify new query created and ID remapped

**Suggested MVP Scope**: Phase 1 + Phase 2 + Phase 3 (User Story 1) = **34 tasks**

**Format Validation**: ✅ All 86 tasks follow checklist format with:
- Checkbox: `- [ ]`
- Task ID: T001-T086 (sequential)
- [P] marker: 41 tasks parallelizable
- [Story] label: 52 tasks (US1: 19, US2: 13, US3: 9, US4: 11)
- File paths: All implementation tasks include specific file paths

---

## Notes

- [P] tasks = different files, no dependencies within phase
- [Story] label maps task to specific user story for traceability
- Each user story is independently completable and testable
- MVP (User Story 1) delivers core value: unpack → modify → pack workflow
- Stop at any checkpoint to validate story independently
- Commit after each task or logical group
- All file paths are absolute and follow project structure from plan.md
