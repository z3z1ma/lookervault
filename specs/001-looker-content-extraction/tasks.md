# Tasks: Looker Content Extraction System

**Input**: Design documents from `/specs/001-looker-content-extraction/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/internal-api.md

**Tests**: Not explicitly requested in specification - tests are optional for this MVP

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `- [ ] [ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- File paths use absolute imports: `lookervault.module.submodule`

## Path Conventions

- **Project type**: Single CLI project
- **Source**: `src/lookervault/`
- **Tests**: `tests/`
- All modules use absolute imports per CLAUDE.md

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and dependency installation

- [X] T001 Add production dependencies via uv: `uv add msgspec tenacity`
- [X] T002 [P] Create storage module structure: `src/lookervault/storage/__init__.py`
- [X] T003 [P] Create extraction module structure: `src/lookervault/extraction/__init__.py`
- [X] T004 [P] Create ContentType enum in `src/lookervault/storage/models.py`
- [X] T005 [P] Create custom exceptions in `src/lookervault/exceptions.py` (extend existing with StorageError, SerializationError, ExtractionError, RateLimitError, etc.)

**Checkpoint**: Project structure and dependencies ready

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Storage Foundation

- [X] T006 Create SQLite schema creation script in `src/lookervault/storage/schema.py` with content_items, sync_checkpoints, extraction_sessions tables
- [X] T007 Implement MsgpackSerializer protocol in `src/lookervault/storage/serializer.py` using msgspec library
- [X] T008 Create ContentItem dataclass in `src/lookervault/storage/models.py` with validation
- [X] T009 Create Checkpoint dataclass in `src/lookervault/storage/models.py`
- [X] T010 Create ExtractionSession dataclass in `src/lookervault/storage/models.py`
- [X] T011 Implement ContentRepository protocol in `src/lookervault/storage/repository.py` with SQLite backend

### Looker API Foundation

- [X] T012 Extend LookerClient in `src/lookervault/looker/client.py` with connection testing
- [X] T013 Create ContentExtractor in `src/lookervault/looker/extractor.py` with SDK method mappings for all content types

### Retry & Progress Foundation

- [X] T014 [P] Create retry decorators in `src/lookervault/extraction/retry.py` using tenacity
- [X] T015 [P] Create ProgressTracker protocol in `src/lookervault/extraction/progress.py`
- [X] T016 [P] Implement RichProgressTracker in `src/lookervault/extraction/progress.py` using Rich library
- [X] T017 [P] Implement JsonProgressTracker in `src/lookervault/extraction/progress.py` for machine-readable output

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - Full Content Backup (Priority: P1) 🎯 MVP

**Goal**: Administrator can extract all Looker content types to local SQLite storage with progress tracking

**Independent Test**: Run `lookervault extract`, verify all content types extracted, check SQLite database has data, view progress in terminal

### Implementation for User Story 1

- [X] T018 [US1] Create BatchProcessor in `src/lookervault/extraction/batch_processor.py` with memory monitoring (tracemalloc)
- [X] T019 [US1] Implement ExtractionOrchestrator in `src/lookervault/extraction/orchestrator.py` coordinating extractor, repository, serializer, progress
- [X] T020 [US1] Create ExtractionConfig dataclass in `src/lookervault/extraction/orchestrator.py`
- [X] T021 [US1] Create ExtractionResult dataclass in `src/lookervault/extraction/orchestrator.py`
- [X] T022 [US1] Implement extract command in `src/lookervault/cli/commands/extract.py` using Typer with --types, --output, --batch-size options
- [X] T023 [US1] Add extract command to CLI app in `src/lookervault/cli/main.py`
- [X] T024 [US1] Implement extraction workflow: create session → iterate content types → extract batches → serialize → save → update progress → complete session
- [X] T025 [US1] Configure SQLite optimizations (16KB pages, 64MB cache, WAL mode) in repository initialization
- [X] T026 [US1] Add extraction progress display with Rich showing content type, items processed, percentage, ETA
- [X] T027 [US1] Add extraction summary report showing items by type, errors, duration, storage location
- [X] T028 [US1] Handle rate limit errors (HTTP 429) with automatic retry using tenacity exponential back-off
- [X] T029 [US1] Implement memory-efficient batch processing (default 100 items) to avoid loading all content in memory

**Checkpoint**: Full extraction works end-to-end. User Story 1 is independently functional and testable.

**Acceptance Validation**:
1. ✅ Initiating extraction retrieves all content types
2. ✅ Progress shows real-time updates with percentage complete
3. ✅ Summary report displays total items by type
4. ✅ Transient API errors retry automatically with exponential back-off
5. ✅ Large instances process in batches without memory issues

---

## Phase 4: User Story 2 - Incremental Content Updates (Priority: P2)

**Goal**: Administrator can update backup with only changed content since last extraction

**Independent Test**: Run full extraction, modify content in Looker, run `lookervault extract --incremental`, verify only changed items updated

### Implementation for User Story 2

- [X] T030 [US2] Add --incremental flag to extract command in `src/lookervault/cli/commands/extract.py`
- [X] T031 [US2] Implement timestamp comparison logic in ExtractionOrchestrator to detect changed content
- [X] T032 [US2] Modify ContentExtractor to support filtering by updated_at timestamp
- [X] T033 [US2] Implement soft delete detection: query Looker for all IDs, compare with DB, mark missing items as deleted
- [X] T034 [US2] Update ContentRepository.save_content to handle upserts (insert or update)
- [X] T035 [US2] Add incremental extraction summary showing new items, updated items, deleted items

**Checkpoint**: Incremental extraction works independently. Both US1 (full) and US2 (incremental) work.

**Acceptance Validation**:
1. ✅ Incremental mode compares timestamps and retrieves only modified content
2. ✅ New content captured along with updates to existing items
3. ✅ Deleted content marked with deleted_at timestamp without removing historical data

---

## Phase 5: User Story 3 - Extraction Recovery and Resume (Priority: P3)

**Goal**: Interrupted extractions can resume from last checkpoint

**Independent Test**: Start extraction, interrupt (Ctrl+C), restart with `lookervault extract --resume`, verify continuation from checkpoint

### Implementation for User Story 3

- [X] T036 [US3] Add --resume flag to extract command in `src/lookervault/cli/commands/extract.py`
- [X] T037 [US3] Implement checkpoint creation in ExtractionOrchestrator after each content type batch completes
- [X] T038 [US3] Implement checkpoint detection logic: query sync_checkpoints for incomplete checkpoints by session_id
- [X] T039 [US3] Implement resume workflow: load checkpoint_data JSON, extract last_offset, skip to offset, continue extraction
- [X] T040 [US3] Add checkpoint completion logic: set completed_at timestamp when content type finishes
- [X] T041 [US3] Implement corruption detection: validate checkpoint_data JSON, verify item_count matches DB records
- [X] T042 [US3] Add resume confirmation prompt showing last checkpoint details (content type, offset, timestamp)
- [X] T043 [US3] Handle resume failures gracefully: if checkpoint corrupt or unresumable, offer to restart fresh

**Checkpoint**: Resume capability works. Interrupted extractions can continue. US1, US2, US3 all functional.

**Acceptance Validation**:
1. ✅ Restarted extraction detects incomplete extraction and offers resume
2. ✅ Resumed extraction skips already-extracted content
3. ✅ Corrupted checkpoints detected and handled appropriately

---

## Phase 6: User Story 4 - Content Verification (Priority: P4)

**Goal**: Administrator can verify extracted content integrity and faithful representation

**Independent Test**: Run extraction, run `lookervault verify`, see validation results

### Implementation for User Story 4

- [X] T044 [P] [US4] Create verify command in `src/lookervault/cli/commands/verify.py`
- [X] T045 [US4] Add verify command to CLI app in `src/lookervault/cli/main.py`
- [X] T046 [US4] Implement deserialization validation: load BLOB, msgspec.msgpack.decode(), catch exceptions
- [X] T047 [US4] Implement content_size validation: verify content_size == len(content_data)
- [X] T048 [US4] Add --compare-live option to fetch current Looker state and compare with DB
- [X] T049 [US4] Implement live comparison logic: fetch content from Looker, deserialize DB content, deep compare
- [X] T050 [US4] Add verification summary report showing valid items, errors, discrepancies
- [X] T051 [US4] Support --type filter to verify specific content types only

**Checkpoint**: Verification works. All user stories (US1-US4) independently functional.

**Acceptance Validation**:
1. ✅ Verification compares stored content against Looker and reports discrepancies
2. ✅ Binary representation can be deserialized successfully
3. ✅ Complex nested structures preserve all relationships

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements across all user stories and production readiness

- [X] T052 [P] Add comprehensive logging throughout extraction workflow using Python logging module
- [X] T053 [P] Add --verbose and --debug flags to all commands for detailed logging
- [X] T054 [P] Implement proper exit codes: 0=success, 1=general error, 2=config error, 3=API error
- [X] T055 [P] Add --config option to all commands for custom config file path
- [X] T056 [P] Add --db option to all commands for custom database path
- [X] T057 [P] Create list command in `src/lookervault/cli/commands/list.py` to query extracted content metadata
- [X] T058 [P] Implement retention policy cleanup command: `lookervault cleanup --retention-days N`
- [X] T059 [P] Add JSON output mode validation: ensure all progress events emit valid JSON
- [ ] T060 [P] Optimize SQLite queries with EXPLAIN QUERY PLAN analysis
- [X] T061 [P] Add memory usage warnings when approaching configured limits
- [X] T062 [P] Document CLI commands in `--help` output with rich formatting
- [ ] T063 [P] Add error recovery documentation to quickstart.md based on implementation
- [ ] T064 Validate quickstart.md examples match actual CLI interface
- [ ] T065 Run full extraction on test Looker instance to validate performance targets (1000 items <30min)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational phase - Core MVP
- **User Story 2 (Phase 4)**: Depends on Foundational phase - Can start independently but builds on US1
- **User Story 3 (Phase 5)**: Depends on Foundational phase - Can start independently but uses US1 infrastructure
- **User Story 4 (Phase 6)**: Depends on Foundational phase - Can start independently
- **Polish (Phase 7)**: Depends on desired user stories being complete

### User Story Dependencies

- **US1 (Full Backup)**: Foundation only - no user story dependencies
- **US2 (Incremental)**: Foundation only - uses US1 extract command but extends it independently
- **US3 (Resume)**: Foundation only - uses US1 orchestrator but adds checkpoint logic independently
- **US4 (Verify)**: Foundation only - separate command, no dependencies on other stories

**All user stories can theoretically start in parallel after Foundational phase**, but recommended order is P1→P2→P3→P4 for incremental delivery.

### Within Each User Story

**User Story 1**:
- T018-T021 can run in parallel (different components)
- T022-T023 require T018-T021 complete (CLI depends on orchestrator)
- T024-T029 implement orchestrator workflow sequentially

**User Story 2**:
- T030-T035 sequential (modify existing extract command)

**User Story 3**:
- T036-T043 sequential (checkpoint logic builds incrementally)

**User Story 4**:
- T044-T045 can run in parallel
- T046-T051 sequential (build verification logic)

### Parallel Opportunities

**Within Setup (Phase 1)**:
- All T002-T005 can run in parallel (different files)

**Within Foundational (Phase 2)**:
- T007 (serializer), T014-T017 (retry & progress) can run in parallel
- T006-T011 (storage) sequential
- T012-T013 (looker) sequential

**Across User Stories**:
- After Foundational complete, different developers can work on US1, US2, US3, US4 simultaneously
- Within each story, [P] marked tasks can run in parallel

**Within Polish (Phase 7)**:
- All [P] tasks (T052-T063) can run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch foundational components in parallel:
Task T007: "Implement MsgpackSerializer"
Task T014: "Create retry decorators"
Task T015: "Create ProgressTracker protocol"
Task T016: "Implement RichProgressTracker"
Task T017: "Implement JsonProgressTracker"

# Within US1, launch components in parallel:
Task T018: "Create BatchProcessor"
Task T019: "Implement ExtractionOrchestrator"
Task T020: "Create ExtractionConfig"
Task T021: "Create ExtractionResult"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T005) → ~30 minutes
2. Complete Phase 2: Foundational (T006-T017) → ~4-6 hours
3. Complete Phase 3: User Story 1 (T018-T029) → ~8-12 hours
4. **STOP and VALIDATE**: Test full extraction end-to-end
5. **MVP COMPLETE**: Working backup system

**Total MVP Time**: ~12-18 hours of implementation

### Incremental Delivery

1. **Milestone 1**: MVP (US1) → Full extraction working
2. **Milestone 2**: +US2 → Incremental updates added
3. **Milestone 3**: +US3 → Resume capability added
4. **Milestone 4**: +US4 → Verification added
5. **Milestone 5**: Polish → Production-ready

Each milestone adds value without breaking previous functionality.

### Parallel Team Strategy

With 3-4 developers:

**Week 1**:
- Team: Setup + Foundational together (T001-T017)
- Checkpoint: Foundation ready

**Week 2**:
- Dev A: User Story 1 (T018-T029)
- Dev B: User Story 2 (T030-T035) - starts after US1 command structure clear
- Dev C: User Story 4 (T044-T051) - fully independent

**Week 3**:
- Dev A: User Story 3 (T036-T043)
- Dev B+C: Polish tasks (T052-T065)

**Total Time**: ~2-3 weeks with parallel development

---

## Task Count Summary

- **Phase 1 (Setup)**: 5 tasks
- **Phase 2 (Foundational)**: 12 tasks
- **Phase 3 (US1 - MVP)**: 12 tasks
- **Phase 4 (US2)**: 6 tasks
- **Phase 5 (US3)**: 8 tasks
- **Phase 6 (US4)**: 8 tasks
- **Phase 7 (Polish)**: 14 tasks

**Total**: 65 tasks

**MVP Tasks (Phase 1 + 2 + 3)**: 29 tasks (~12-18 hours)
**Full Feature (All phases)**: 65 tasks (~30-40 hours)

### Parallel Opportunities Identified

- **Setup**: 4 parallel tasks (T002-T005)
- **Foundational**: 5 parallel tasks (T007, T014-T017)
- **US1**: 4 parallel tasks (T018-T021)
- **US4**: 2 parallel tasks (T044-T045)
- **Polish**: 13 parallel tasks (T052-T064)

**Total Parallelizable**: 28 tasks (43% of all tasks)

---

## Independent Test Criteria

### User Story 1 (Full Backup)
**Test Command**: `lookervault extract`
**Success Criteria**:
- All content types extracted (dashboards, looks, models, users, etc.)
- Progress bars display real-time updates
- Summary report shows item counts
- SQLite database created with data
- Automatic retry on API errors
- Batch processing for large instances

### User Story 2 (Incremental Updates)
**Test Command**: `lookervault extract --incremental` (after modifying Looker content)
**Success Criteria**:
- Only changed items extracted
- New items captured
- Deleted items marked with deleted_at
- Faster than full extraction

### User Story 3 (Resume)
**Test Command**: `lookervault extract` → Ctrl+C → `lookervault extract --resume`
**Success Criteria**:
- Incomplete extraction detected
- Resume from last checkpoint
- Skip already-extracted content
- Handle corrupted checkpoints

### User Story 4 (Verify)
**Test Command**: `lookervault verify`
**Success Criteria**:
- All BLOBs deserialize successfully
- content_size matches actual size
- Live comparison (--compare-live) shows discrepancies
- Verification report shows valid/invalid items

---

## Suggested MVP Scope

**Recommended MVP**: User Story 1 only (Phase 1 + 2 + 3)

**Rationale**:
- Delivers immediate value (full content backup)
- Tests all core infrastructure (storage, serialization, retry, progress)
- Can be used in production immediately
- ~12-18 hours of implementation
- Provides foundation for all other stories

**Post-MVP Additions** (in priority order):
1. US2 (Incremental) - Makes regular backups practical
2. US3 (Resume) - Improves reliability for large instances
3. US4 (Verify) - Adds confidence but not required for basic operation

---

## Format Validation

✅ **All 65 tasks follow checklist format**:
- Start with `- [ ]`
- Include Task ID (T001-T065)
- Include [P] marker where parallelizable
- Include [Story] label (US1-US4) for user story tasks
- Include file paths in descriptions
- Clear, actionable descriptions

✅ **Organization validated**:
- Grouped by user story for independent implementation
- Each phase has clear purpose and checkpoint
- Dependencies documented
- Parallel opportunities identified
- Independent test criteria defined for each story

**Ready for execution** ✅
