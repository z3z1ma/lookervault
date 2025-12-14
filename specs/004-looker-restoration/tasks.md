# Tasks: Looker Content Restoration

**Input**: Design documents from `/specs/004-looker-restoration/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: No explicit test requirements in spec - tests are deferred to implementation discretion

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

- Single project structure: `src/lookervault/`, `tests/` at repository root
- Paths follow existing lookervault codebase patterns

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and database schema foundation

- [ ] T001 Add restoration exceptions to src/lookervault/exceptions.py (RestorationError, DeserializationError, ValidationError, DependencyError, IDMappingError)
- [ ] T002 [P] Create restoration module directory src/lookervault/restoration/ with __init__.py
- [ ] T003 [P] Add restoration_sessions table SQL to src/lookervault/storage/schema.py
- [ ] T004 [P] Add restoration_checkpoints table SQL to src/lookervault/storage/schema.py
- [ ] T005 [P] Add id_mappings table SQL to src/lookervault/storage/schema.py
- [ ] T006 [P] Add dead_letter_queue table SQL to src/lookervault/storage/schema.py
- [ ] T007 Add database indexes for restoration tables in src/lookervault/storage/schema.py

**Checkpoint**: Database schema ready for restoration operations

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core data models and repository methods that ALL user stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Data Models

- [ ] T008 [P] Add RestorationSession dataclass to src/lookervault/storage/models.py
- [ ] T009 [P] Add RestorationCheckpoint dataclass to src/lookervault/storage/models.py
- [ ] T010 [P] Add IDMapping dataclass to src/lookervault/storage/models.py
- [ ] T011 [P] Add DeadLetterItem dataclass to src/lookervault/storage/models.py
- [ ] T012 [P] Add RestorationTask dataclass to src/lookervault/storage/models.py
- [ ] T013 [P] Add DependencyOrder enum to src/lookervault/storage/models.py

### Repository Extensions

- [ ] T014 [P] Implement create_restoration_session() in src/lookervault/storage/repository.py
- [ ] T015 [P] Implement update_restoration_session() in src/lookervault/storage/repository.py
- [ ] T016 [P] Implement get_restoration_session() in src/lookervault/storage/repository.py
- [ ] T017 [P] Implement list_restoration_sessions() in src/lookervault/storage/repository.py
- [ ] T018 [P] Implement save_restoration_checkpoint() in src/lookervault/storage/repository.py
- [ ] T019 [P] Implement update_restoration_checkpoint() in src/lookervault/storage/repository.py
- [ ] T020 [P] Implement get_latest_restoration_checkpoint() in src/lookervault/storage/repository.py
- [ ] T021 [P] Implement save_id_mapping() in src/lookervault/storage/repository.py
- [ ] T022 [P] Implement get_id_mapping() in src/lookervault/storage/repository.py
- [ ] T023 [P] Implement get_destination_id() in src/lookervault/storage/repository.py
- [ ] T024 [P] Implement batch_get_mappings() in src/lookervault/storage/repository.py
- [ ] T025 [P] Implement clear_mappings() in src/lookervault/storage/repository.py
- [ ] T026 [P] Implement save_dead_letter_item() in src/lookervault/storage/repository.py
- [ ] T027 [P] Implement get_dead_letter_item() in src/lookervault/storage/repository.py
- [ ] T028 [P] Implement list_dead_letter_items() in src/lookervault/storage/repository.py
- [ ] T029 [P] Implement count_dead_letter_items() in src/lookervault/storage/repository.py
- [ ] T030 [P] Implement delete_dead_letter_item() in src/lookervault/storage/repository.py

### Core Restoration Infrastructure

- [ ] T031 [P] Create ContentDeserializer class in src/lookervault/restoration/deserializer.py
- [ ] T032 Implement ContentDeserializer.deserialize() method with support for all ContentType enum values
- [ ] T033 [P] Implement ContentDeserializer.validate_schema() method
- [ ] T034 [P] Create DependencyGraph class in src/lookervault/restoration/dependency_graph.py
- [ ] T035 Implement DependencyGraph.get_restoration_order() with hardcoded dependency relationships
- [ ] T036 [P] Implement DependencyGraph.validate_no_cycles() method
- [ ] T037 [P] Implement DependencyGraph.get_dependencies() method
- [ ] T038 [P] Create RestorationValidator class in src/lookervault/restoration/validation.py
- [ ] T039 [P] Implement RestorationValidator.validate_pre_flight() method
- [ ] T040 [P] Implement RestorationValidator.validate_content() method
- [ ] T041 [P] Implement RestorationValidator.validate_dependencies() method

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Single Object Restoration for Testing (Priority: P1) 🎯 MVP

**Goal**: Enable administrators to restore a single dashboard from SQLite backup to production Looker instance for safe testing before bulk operations

**Independent Test**: Select a single dashboard from SQLite, run `lookervault restore single dashboard <ID>`, verify dashboard appears correctly in Looker with all properties intact

**Acceptance Scenarios**:
1. Dashboard exists in SQLite but not in Looker → Creates new dashboard with matching properties, records new ID
2. Dashboard exists in both SQLite and Looker with different content → Updates existing Looker dashboard without changing ID
3. Dashboard restoration fails due to missing dependencies → Error logged with dependency details, dashboard remains in safe state

### Implementation for User Story 1

- [ ] T042 [P] [US1] Create LookerContentRestorer class in src/lookervault/restoration/restorer.py
- [ ] T043 [P] [US1] Implement LookerContentRestorer.__init__() with client, repository, rate_limiter, id_mapper parameters
- [ ] T044 [US1] Implement LookerContentRestorer.check_exists() method to verify content exists in destination via GET request
- [ ] T045 [US1] Implement LookerContentRestorer._call_api_update() method with retry_on_rate_limit decorator for PATCH operations
- [ ] T046 [US1] Implement LookerContentRestorer._call_api_create() method with retry_on_rate_limit decorator for POST operations
- [ ] T047 [US1] Implement LookerContentRestorer.restore_single() method (fetch from SQLite, deserialize, validate, check exists, call update or create, return RestorationResult)
- [ ] T048 [P] [US1] Create RestorationConfig Pydantic model in src/lookervault/config/models.py with workers, rate limits, dry_run, filtering options
- [ ] T049 [P] [US1] Create RestorationResult dataclass in src/lookervault/storage/models.py (content_id, content_type, status, destination_id, error_message, retry_count, duration_ms)
- [ ] T050 [P] [US1] Create RestorationSummary dataclass in src/lookervault/storage/models.py (session_id, total_items, success_count, created_count, updated_count, error_count, skipped_count, duration_seconds, average_throughput, content_type_breakdown, error_breakdown)
- [ ] T051 [P] [US1] Create CLI restore command module src/lookervault/cli/commands/restore.py
- [ ] T052 [US1] Implement restore_single() CLI command in src/lookervault/cli/commands/restore.py with typer (arguments: content_type, content_id; options: --db-path, --dry-run, --force, --json)
- [ ] T053 [US1] Add rich output formatting for restore_single() showing Found in backup, Checking destination, Restoration successful/failed with duration
- [ ] T054 [US1] Register restore command group in src/lookervault/cli/main.py
- [ ] T055 [US1] Add exit code handling (0=success, 1=error, 2=not found, 3=validation error, 4=API error)

**Checkpoint**: User Story 1 complete - single-item restoration works end-to-end, production-safe testing enabled

---

## Phase 4: User Story 2 - Dependency-Aware Bulk Restoration (Priority: P2)

**Goal**: Enable bulk restoration of multiple content items (dashboards, looks, folders, users, groups) while respecting dependency order between objects

**Independent Test**: Select a set of related content items (folder + dashboards in folder + users who own them), run bulk restore, verify all items restored in correct dependency order with relationships intact

**Acceptance Scenarios**:
1. Multiple content items with dependencies in SQLite → Restored in dependency order (users → groups → folders → models → explores → looks → dashboards → boards)
2. Content item depends on item that exists in Looker but not in SQLite → Uses existing Looker item, continues without error
3. Bulk restoration of 1000 items encounters network error after 500 → Records successful completions in checkpoint, allows resume from item 501

### Implementation for User Story 2

- [ ] T056 [US2] Implement LookerContentRestorer.restore_bulk() method in src/lookervault/restoration/restorer.py (query SQLite for all content IDs of type, loop through restore_single, aggregate to RestorationSummary)
- [ ] T057 [P] [US2] Add progress tracking using existing ProgressTracker from src/lookervault/extraction/progress.py
- [ ] T058 [P] [US2] Implement restore_bulk() CLI command in src/lookervault/cli/commands/restore.py (arguments: content_type; options: --workers, --rate-limit-per-minute, --rate-limit-per-second, --checkpoint-interval, --max-retries, --skip-if-modified, --dry-run, --json)
- [ ] T059 [US2] Add rich progress bar for bulk restore showing Progress bar, Success/Error counts, Throughput, ETA
- [ ] T060 [US2] Implement restore_all() CLI command in src/lookervault/cli/commands/restore.py (options: --exclude-types, --only-types, plus all bulk options)
- [ ] T061 [US2] Wire restore_all() to use DependencyGraph.get_restoration_order() for proper content type ordering
- [ ] T062 [US2] Call restore_bulk() for each content type sequentially in dependency order
- [ ] T063 [US2] Aggregate results across all content types into final RestorationSummary
- [ ] T064 [US2] Add rich output showing per-type progress ([1/9] Users... ✓ 150 users restored, [2/9] Groups..., etc.)
- [ ] T065 [P] [US2] Implement checkpoint save logic in LookerContentRestorer (save checkpoint every N items using save_restoration_checkpoint)
- [ ] T066 [P] [US2] Implement restore_resume() CLI command in src/lookervault/cli/commands/restore.py (optional session_id argument, loads latest checkpoint, filters completed IDs, continues restoration)
- [ ] T067 [US2] Add resume logic to LookerContentRestorer.restore_bulk() (query checkpoint, extract completed_ids, filter them from restoration query)

**Checkpoint**: User Story 2 complete - bulk restoration with dependency ordering works, resume capability functional

---

## Phase 5: User Story 3 - Parallel Restoration with Error Recovery (Priority: P2)

**Goal**: Enable parallel restoration of tens of thousands of content items efficiently using worker threads with retry logic and dead letter queue for error handling

**Independent Test**: Initiate parallel restore of 10,000+ items with simulated transient errors, verify throughput ≥100 items/second, errors retried appropriately, unrecoverable failures captured in DLQ

**Acceptance Scenarios**:
1. 10,000 content items with 8 workers configured → Achieves minimum 100 items/second throughput with automatic rate limiting
2. API rate limit (429) encountered → All workers automatically slow down via shared rate limiter, gradually recover after sustained success
3. Content item fails restoration after max retry attempts → Item moved to DLQ with full error context, restoration continues for remaining items
4. Parallel restoration interrupted mid-process → Resume skips already-completed items, continues from last checkpoint

### Implementation for User Story 3

- [ ] T068 [P] [US3] Create DeadLetterQueue class in src/lookervault/restoration/dead_letter_queue.py
- [ ] T069 [P] [US3] Implement DeadLetterQueue.__init__() with repository parameter
- [ ] T070 [P] [US3] Implement DeadLetterQueue.add() method (extract error type, message, stack trace from exception, call save_dead_letter_item)
- [ ] T071 [P] [US3] Implement DeadLetterQueue.get() method (call get_dead_letter_item)
- [ ] T072 [P] [US3] Implement DeadLetterQueue.list() method (call list_dead_letter_items with filters)
- [ ] T073 [P] [US3] Implement DeadLetterQueue.retry() method (get DLQ entry, call restorer.restore_single, delete from DLQ on success)
- [ ] T074 [P] [US3] Implement DeadLetterQueue.clear() method (call repository method with filters)
- [ ] T075 [P] [US3] Create ParallelRestorationOrchestrator class in src/lookervault/restoration/parallel_orchestrator.py
- [ ] T076 [P] [US3] Implement ParallelRestorationOrchestrator.__init__() with restorer, repository, config, rate_limiter, metrics, dlq, id_mapper parameters
- [ ] T077 [US3] Implement ParallelRestorationOrchestrator.restore() method (query SQLite for content IDs, create thread pool with config.workers threads, distribute IDs via queue, workers call restorer.restore_single with rate limiting, aggregate results, save checkpoints every N items, return RestorationSummary)
- [ ] T078 [US3] Add worker thread error handling (catch exceptions, call dlq.add() after max retries exhausted, update metrics, continue processing)
- [ ] T079 [US3] Implement ParallelRestorationOrchestrator.restore_all() method (use DependencyGraph.get_restoration_order, call restore() for each type sequentially, aggregate results)
- [ ] T080 [US3] Implement ParallelRestorationOrchestrator.resume() method (query incomplete checkpoints, extract completed_ids, call restore() with filtered query)
- [ ] T081 [US3] Update restore_bulk() CLI command to use ParallelOrchestrator when workers > 1
- [ ] T082 [US3] Update restore_all() CLI command to use ParallelOrchestrator when workers > 1
- [ ] T083 [US3] Update restore_resume() CLI command to use ParallelOrchestrator.resume()
- [ ] T084 [P] [US3] Implement restore_dlq_list() CLI command in src/lookervault/cli/commands/restore.py (options: --session-id, --content-type, --limit, --offset, --json)
- [ ] T085 [P] [US3] Implement restore_dlq_show() CLI command in src/lookervault/cli/commands/restore.py (argument: dlq_id, shows full error details including stack trace)
- [ ] T086 [P] [US3] Implement restore_dlq_retry() CLI command in src/lookervault/cli/commands/restore.py (argument: dlq_id, options: --fix-dependencies, --force, --json)
- [ ] T087 [P] [US3] Implement restore_dlq_clear() CLI command in src/lookervault/cli/commands/restore.py (options: --session-id, --content-type, --all, --force)
- [ ] T088 [P] [US3] Implement restore_status() CLI command in src/lookervault/cli/commands/restore.py (optional session_id argument, options: --all, --json)
- [ ] T089 [US3] Add rich formatting for DLQ list output (table with ID, Content Type, Content ID, Error Type, Failed At, Retries columns)
- [ ] T090 [US3] Add rich formatting for restore status output (session ID, status, timestamps, progress breakdown by content type)

**Checkpoint**: User Story 3 complete - parallel restoration with error recovery works, DLQ captures failures, resume functionality robust

---

## Phase 6: User Story 4 - ID Mapping for Cross-Instance Migration (Priority: P3)

**Goal**: Enable restoration from one Looker instance to a different Looker instance with automatic ID mapping and reference translation

**Independent Test**: Restore content from Instance A's backup to Instance B, verify all content created with new IDs, mapping table records old ID → new ID relationships

**Acceptance Scenarios**:
1. Content from Instance A restored to Instance B → System maintains mapping table of source_id → destination_id for each content type
2. Dashboard references a look by ID, both being migrated → Look created first with new ID, dashboard's reference updated to use new destination ID
3. ID mapping exists for previously migrated content → Incremental restore uses existing mappings to update rather than duplicate content

### Implementation for User Story 4

- [ ] T091 [P] [US4] Create IDMapper class in src/lookervault/restoration/id_mapper.py
- [ ] T092 [P] [US4] Implement IDMapper.__init__() with repository, source_instance, destination_instance parameters
- [ ] T093 [P] [US4] Implement IDMapper.save_mapping() method (call repository.save_id_mapping)
- [ ] T094 [P] [US4] Implement IDMapper.get_destination_id() method (call repository.get_destination_id)
- [ ] T095 [US4] Implement IDMapper.translate_references() method (parse content_dict for FK fields based on content_type, lookup mappings for each FK, replace source IDs with destination IDs, return translated content_dict)
- [ ] T096 [P] [US4] Implement IDMapper.clear_mappings() method (call repository.clear_mappings)
- [ ] T097 [P] [US4] Implement IDMapper.is_same_instance() method (compare source_instance with destination_instance URLs)
- [ ] T098 [US4] Update LookerContentRestorer.restore_single() to call id_mapper.save_mapping() after successful create operation (if id_mapper provided)
- [ ] T099 [US4] Update LookerContentRestorer.restore_single() to call id_mapper.translate_references() before API calls (if id_mapper provided and cross-instance migration)
- [ ] T100 [US4] Add --source-instance flag to all restore CLI commands for cross-instance migration scenarios
- [ ] T101 [US4] Wire --source-instance flag to create IDMapper instance when source_instance != destination_instance
- [ ] T102 [US4] Pass IDMapper to LookerContentRestorer and ParallelOrchestrator constructors when cross-instance mode enabled
- [ ] T103 [US4] Add FK field definitions for each ContentType (dashboard.folder_id, dashboard.look_ids, look.folder_id, etc.) to support translate_references()

**Checkpoint**: User Story 4 complete - cross-instance migration with ID mapping functional, FK references translated correctly

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories and final production readiness

- [ ] T104 [P] Add comprehensive docstrings to all restoration classes and methods
- [ ] T105 [P] Add type hints verification (run ty check on restoration module)
- [ ] T106 [P] Add code formatting (run ruff format on restoration module)
- [ ] T107 [P] Add linting fixes (run ruff check --fix on restoration module)
- [ ] T108 [P] Update CLAUDE.md with restoration feature documentation
- [ ] T109 Add --verbose and --quiet flags to all restore CLI commands for logging control
- [ ] T110 Add environment variable support for common options (LOOKERVAULT_DB_PATH, LOOKER_BASE_URL, LOOKER_CLIENT_ID, LOOKER_CLIENT_SECRET)
- [ ] T111 Add configuration file support (lookervault.toml [restore] section) for default values
- [ ] T112 Add user confirmation prompts for destructive operations (with --force flag to skip)
- [ ] T113 Add graceful Ctrl+C handling (save checkpoint, clean shutdown)
- [ ] T114 [P] Performance benchmarking: Verify single-item restore <10 seconds (SC-001)
- [ ] T115 [P] Performance benchmarking: Verify bulk throughput ≥100 items/second with 8 workers (SC-002)
- [ ] T116 [P] Performance benchmarking: Verify 50K items restore <10 minutes (SC-008)
- [ ] T117 [P] Memory profiling: Verify memory scales linearly with workers, not dataset size
- [ ] T118 Validate all success criteria from spec.md (SC-001 through SC-008)
- [ ] T119 Run quickstart.md validation (follow Phase 1-8 testing milestones)
- [ ] T120 Security audit: Verify credentials not logged, rate limiting enforced, dead letter queue doesn't expose sensitive data

**Checkpoint**: Feature production-ready, all acceptance criteria validated, documentation complete

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-6)**: All depend on Foundational phase completion
  - User Story 1 (P1): Can start after Foundational - No dependencies on other stories
  - User Story 2 (P2): Can start after Foundational - May integrate with US1 but independently testable
  - User Story 3 (P2): Can start after Foundational - Builds on US1/US2 components but independently testable
  - User Story 4 (P3): Can start after Foundational - Extends US1-US3 with ID mapping but independently testable
- **Polish (Phase 7)**: Depends on all desired user stories being complete

### User Story Dependencies

- **US1 → US2**: US2 builds on LookerContentRestorer.restore_single() from US1 for its restore_bulk() implementation
- **US2 → US3**: US3 wraps restore_bulk() with ParallelOrchestrator, depends on restore_bulk() existing
- **US1+US2+US3 → US4**: US4 extends restore_single() and restore_bulk() with ID mapping, needs base functionality

**Critical Path**: Setup → Foundational → US1 → US2 → US3 → US4 → Polish

**MVP Path (Fastest to production)**: Setup → Foundational → US1 only (delivers single-item restoration for production testing)

### Within Each User Story

- US1: Foundational → LookerContentRestorer → CLI command → Output formatting
- US2: US1 complete → restore_bulk → CLI commands (bulk/all/resume) → Progress bars
- US3: US2 complete → DeadLetterQueue → ParallelOrchestrator → Wire to CLI → DLQ commands
- US4: US1 complete → IDMapper → Update restorer with translate_references → Wire to CLI

### Parallel Opportunities

**Phase 1 (Setup)**: T002-T006 can run in parallel (different files)

**Phase 2 (Foundational)**:
- T008-T013 can run in parallel (different dataclasses)
- T014-T030 can run in parallel (different repository methods)
- T031, T034, T038 can run in parallel (different classes in different files)
- T033, T036-T037, T039-T041 can run in parallel (different methods in different classes)

**Phase 3 (US1)**:
- T042-T043 and T048-T050 can run in parallel (LookerContentRestorer vs data models)
- T044-T047 must be sequential (build up restore_single)
- T051-T053 can run in parallel with T048-T050 (CLI vs data models)

**Phase 4 (US2)**:
- T057-T059, T065-T066 can run in parallel (progress tracking, checkpointing, CLI - different files)
- T056, T060-T064, T067 must be sequential (core bulk logic)

**Phase 5 (US3)**:
- T068-T074 (DeadLetterQueue) can run in parallel with T075-T076 (ParallelOrchestrator class setup)
- T084-T090 can run in parallel (all DLQ/status CLI commands - different sections of file)

**Phase 6 (US4)**:
- T091-T097 can mostly run in parallel (different IDMapper methods)
- T098-T103 must be sequential (integration work)

**Phase 7 (Polish)**:
- T104-T108, T114-T117 can run in parallel (independent polish tasks)

---

## Parallel Example: User Story 1

```bash
# After Foundational phase completes, launch in parallel:
Task T042: "Create LookerContentRestorer class in src/lookervault/restoration/restorer.py"
Task T048: "Create RestorationConfig Pydantic model in src/lookervault/config/models.py"
Task T049: "Create RestorationResult dataclass in src/lookervault/storage/models.py"
Task T050: "Create RestorationSummary dataclass in src/lookervault/storage/models.py"
Task T051: "Create CLI restore command module src/lookervault/cli/commands/restore.py"
```

---

## Parallel Example: User Story 3

```bash
# After US2 completes, launch in parallel:
Task T068-T074: "Complete DeadLetterQueue class implementation"
Task T075-T076: "Create ParallelRestorationOrchestrator class structure"
Task T084: "Implement restore_dlq_list() CLI command"
Task T085: "Implement restore_dlq_show() CLI command"
Task T086: "Implement restore_dlq_retry() CLI command"
Task T087: "Implement restore_dlq_clear() CLI command"
Task T088: "Implement restore_status() CLI command"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

**Fastest path to production testing capability**:

1. Complete Phase 1: Setup (T001-T007) - ~1 day
2. Complete Phase 2: Foundational (T008-T041) - ~2 days
3. Complete Phase 3: User Story 1 (T042-T055) - ~2 days
4. **STOP and VALIDATE**: Test single-item restoration independently
5. Deploy to production for safe single-dashboard testing

**Total MVP timeline**: ~5 days

**MVP Deliverable**: `lookervault restore single dashboard <ID>` command working end-to-end

### Incremental Delivery

**After MVP, add capabilities incrementally**:

1. **MVP (US1)**: Single-item restoration → Production testing enabled
2. **+US2**: Bulk restoration with dependency ordering → Data recovery capability enabled
3. **+US3**: Parallel restoration with error recovery → Large-scale restoration enabled (50K+ items)
4. **+US4**: Cross-instance migration with ID mapping → Instance migration capability enabled
5. **+Polish**: Production hardening → Feature complete and optimized

**Each increment independently tested and deployed**

### Parallel Team Strategy

With multiple developers:

1. **Week 1**: Team completes Setup + Foundational together
2. **Week 2**: Once Foundational done:
   - Developer A: User Story 1 (P1) - MVP priority
   - Developer B: Start User Story 2 (P2) infrastructure
   - Developer C: Start User Story 3 (P3) infrastructure
3. **Week 3**: Integration
   - US1 complete and tested → Deploy
   - US2 builds on US1 → Test
   - US3 builds on US2 → Test
4. **Week 4**: US4 + Polish
   - Developer A: User Story 4
   - Developer B+C: Polish tasks

**Total team timeline**: ~4 weeks for full feature

---

## Task Summary

**Total Tasks**: 120 tasks

**Task Count by Phase**:
- Phase 1 (Setup): 7 tasks
- Phase 2 (Foundational): 34 tasks
- Phase 3 (US1 - P1 MVP): 14 tasks
- Phase 4 (US2 - P2): 12 tasks
- Phase 5 (US3 - P2): 23 tasks
- Phase 6 (US4 - P3): 13 tasks
- Phase 7 (Polish): 17 tasks

**Parallel Opportunities Identified**: 68 tasks marked [P] can run in parallel within their phase

**Independent Test Criteria**:
- **US1**: Single dashboard restore from SQLite to Looker, verify properties match
- **US2**: Bulk restore of folder + dashboards + users, verify dependency order respected
- **US3**: Parallel restore of 10K+ items, verify throughput ≥100 items/sec, DLQ captures failures
- **US4**: Cross-instance restore, verify ID mappings created and FK references translated

**Suggested MVP Scope**: Phase 1 + Phase 2 + Phase 3 only (US1 - Single Object Restoration)

**Format Validation**: ✅ ALL tasks follow checklist format:
- ✅ Checkbox prefix: `- [ ]`
- ✅ Task ID: T001-T120
- ✅ [P] marker: 68 tasks marked as parallelizable
- ✅ [Story] label: All user story tasks labeled (US1, US2, US3, US4)
- ✅ File paths: All implementation tasks include exact file paths

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Avoid: vague tasks, same file conflicts, cross-story dependencies that break independence
- Success criteria validation happens in Phase 7 (T118)
- Performance benchmarking happens in Phase 7 (T114-T117)
- Follow quickstart.md testing milestones for validation (T119)
