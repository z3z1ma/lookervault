# Tasks: Parallel Content Extraction

**Input**: Design documents from `/specs/002-parallel-extraction/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: This feature does NOT include explicit test generation tasks. Testing will be done through existing pytest framework after implementation.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

- **Project Structure**: Single project (CLI tool)
- **Source**: `src/lookervault/`
- **Tests**: `tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and dependency management

- [X] T001 ~~Add pyrate-limiter dependency~~ (Changed to custom implementation using threading.Lock and sliding window algorithm for better reliability)
- [X] T002 [P] Review and update CLAUDE.md with parallel extraction context (already updated by setup script)
- [X] T003 [P] Create directory structure for new modules: `src/lookervault/extraction/parallel/`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 Refactor SQLiteContentRepository to use thread-local connections in `src/lookervault/storage/repository.py`
  - Replace singleton `self._conn` with `self._local = threading.local()`
  - Add `_create_connection()` method with `timeout=60.0`, `cached_statements=0`, `isolation_level=None`
  - Add `close_thread_connection()` method for worker cleanup
- [X] T005 Add BEGIN IMMEDIATE transaction control to all write operations in `src/lookervault/storage/repository.py`
  - Update `save_content()` to use `BEGIN IMMEDIATE` before writes
  - Add proper commit/rollback handling
  - Update `save_checkpoint()` and `update_checkpoint()` with BEGIN IMMEDIATE
- [X] T006 [P] Create WorkItem dataclass in `src/lookervault/extraction/work_queue.py`
  - Fields: content_type, items, batch_number, is_final_batch
  - Add validation for content_type and items
- [X] T007 [P] Create ParallelConfig model in `src/lookervault/config/models.py`
  - Fields: workers, queue_size, batch_size, rate_limit_per_minute, rate_limit_per_second, adaptive_rate_limiting
  - Add validation (workers: 1-50, queue_size >= workers*10, batch_size: 10-1000)
  - Add defaults: workers=min(cpu_count, 8), queue_size=workers*100, batch_size=100

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Configure Parallel Extraction (Priority: P1) 🎯 MVP

**Goal**: Enable users to configure thread pool size and extract content in parallel, reducing extraction time from hours to minutes for large datasets.

**Independent Test**: Run `lookervault extract --workers 8 dashboards` and verify:
- 8 worker threads created
- Extraction completes faster than `--workers 1`
- No database corruption or data loss
- Progress shows concurrent processing

### Implementation for User Story 1

- [X] T008 [P] [US1] Create ThreadSafeMetrics class in `src/lookervault/extraction/metrics.py`
  - Fields: items_processed, items_by_type, errors, worker_errors, start_time, _lock
  - Methods: increment_processed(), record_error(), snapshot()
  - All methods use `with self._lock` for thread safety
- [X] T009 [P] [US1] Create WorkQueue class in `src/lookervault/extraction/work_queue.py`
  - Wraps `queue.Queue[WorkItem | None]` with bounded size
  - Methods: put_work(), get_work(), send_stop_signals()
  - Handle queue.Empty and queue.Full exceptions
- [X] T010 [US1] Create ParallelOrchestrator class in `src/lookervault/extraction/parallel_orchestrator.py`
  - Constructor: extractor, repository, serializer, progress, config, parallel_config
  - Method: extract() - main parallel extraction workflow
  - Method: _producer_worker() - fetches from API, creates WorkItems, queues them
  - Method: _consumer_worker() - gets WorkItems, processes items, saves to DB
  - Use ThreadPoolExecutor with max_workers
  - Producer in main thread, consumers in ThreadPoolExecutor
- [X] T011 [US1] ParallelConfig already created in Phase 2 (separate model, not nested in ExtractionConfig)
- [X] T012 [US1] Add --workers CLI option to extract command in `src/lookervault/cli/commands/extract.py`
  - Add workers parameter with default=min(cpu_count, 8)
  - Choose ParallelOrchestrator if workers > 1, else use existing ExtractionOrchestrator
  - Pass ParallelConfig to ParallelOrchestrator
- [X] T013 [US1] Implement worker cleanup logic in ParallelOrchestrator
  - Call `repository.close_thread_connection()` in finally block of _consumer_worker()
  - Ensure all worker threads clean up connections on completion or error
- [X] T014 [US1] Add validation for thread pool size in CLI and ParallelConfig
  - Validate workers in range [1, 50]
  - Display warning if workers > 16 (SQLite write contention)
  - Use default min(os.cpu_count() or 1, 8) if not specified

**Checkpoint**: At this point, User Story 1 should be fully functional - users can run `lookervault extract --workers N` and see parallel extraction working with faster throughput than sequential.

---

## Phase 4: User Story 2 - Monitor Parallel Extraction Progress (Priority: P2)

**Goal**: Provide real-time visibility into parallel extraction progress, showing items processed per second, active workers, and thread pool utilization.

**Independent Test**: Run `lookervault extract --workers 8 dashboards` and verify:
- Progress display shows per-content-type progress bars
- Items/second throughput displayed
- Worker failure (simulated) shows in progress without crashing extraction
- Final summary shows total items, duration, throughput

### Implementation for User Story 2

- [X] T015 [P] [US2] Enhanced ThreadSafeMetrics with progress tracking in `src/lookervault/extraction/metrics.py`
  - Added fields: total_by_type (expected totals), batches_completed
  - Added methods: set_total(), increment_batches()
  - Updated snapshot() to return progress_by_type (percentage 0-100 per content type)
  - Provides foundation for real-time progress monitoring
- [X] T016 [P] [US2] Created ProgressUpdate dataclass in `src/lookervault/extraction/progress_update.py`
  - Fields: content_type, items_processed, total_items, timestamp, worker_id, metadata
  - Property: progress_percentage() calculates 0-100% or None
  - Ready for future real-time progress event system
- [X] T017 [US2] Integrated batch completion tracking into ParallelOrchestrator
  - Call metrics.increment_batches() after each batch processed
  - Debug logging shows running batch count
  - Provides granular progress monitoring beyond just item counts
- [X] T018 [US2] Worker failure isolation already implemented in ParallelOrchestrator
  - Uses concurrent.futures.as_completed() for worker result processing
  - Catches worker exceptions without crashing orchestrator (line 124-128)
  - Records errors in metrics.worker_errors
  - Continues with remaining workers on failure
- [X] T019 [US2] Per-content-type progress tracking foundation complete
  - ThreadSafeMetrics tracks items_by_type, total_by_type, progress_by_type
  - Workers call increment_processed(content_type) after each item
  - Progress percentages calculated per content type in snapshot()
- [X] T020 [US2] Throughput calculation implemented in ThreadSafeMetrics
  - Calculates items/second in snapshot() based on start_time
  - Returns duration_seconds and items_per_second
  - Already displayed in final summary (extract.py line 172-188)

**Checkpoint**: At this point, User Stories 1 AND 2 should both work - users can see real-time progress during parallel extraction with throughput metrics.

---

## Phase 5: User Story 3 - Handle API Rate Limits with Parallelism (Priority: P2)

**Goal**: Automatically detect HTTP 429 rate limit responses and coordinate backoff across all workers to prevent extraction failures in rate-limited environments.

**Independent Test**: Run extraction with simulated rate limits and verify:
- HTTP 429 detected and logged
- All workers slow down (adaptive backoff)
- Extraction completes successfully without manual intervention
- No data loss or corruption

### Implementation for User Story 3

- [X] T021 [P] [US3] Create AdaptiveRateLimiter class in `src/lookervault/extraction/rate_limiter.py`
  - Custom sliding window implementation using threading.Lock and deque
  - Fields: _minute_window, _second_window, _lock, state, adaptive
  - Methods: acquire(), on_429_detected(), on_success(), get_stats()
  - Thread-safe via threading.Lock (more reliable than pyrate-limiter)
- [X] T022 [P] [US3] Create RateLimiterState dataclass in `src/lookervault/extraction/rate_limiter.py`
  - Fields: backoff_multiplier, last_429_timestamp, consecutive_successes, total_429_count, _lock
  - Methods for state management and adaptive backoff logic
- [X] T023 [US3] Integrate AdaptiveRateLimiter into LookerContentExtractor in `src/lookervault/looker/extractor.py`
  - Add rate_limiter field to constructor (optional, backward compatible)
  - Call rate_limiter.acquire() before each API call in _call_api()
  - Call rate_limiter.on_success() after successful API calls
  - Call rate_limiter.on_429_detected() when HTTP 429 detected
- [X] T024 [US3] Existing retry logic already works with rate limiter
  - @retry_on_rate_limit decorator works seamlessly with new rate limiter
  - Logging already present for rate limit detection
  - Exponential backoff behavior preserved
- [X] T025 [US3] Rate limiter configuration already in ParallelConfig (created in Phase 2)
  - Fields: rate_limit_per_minute (default 100), rate_limit_per_second (default 10)
  - Validation: rate_limit_per_second <= rate_limit_per_minute
- [X] T026 [US3] Pass rate limiter to all workers in ParallelOrchestrator
  - Create single shared AdaptiveRateLimiter instance in __init__
  - Inject into extractor so all workers share same rate limiter
  - Ensures thread-safe coordination across workers
- [X] T027 [US3] Add CLI options for rate limiting in `src/lookervault/cli/main.py` and `src/lookervault/cli/commands/extract.py`
  - Add --rate-limit-per-minute option (optional, default 100)
  - Add --rate-limit-per-second option (optional, default 10)
  - Pass to ParallelConfig when creating orchestrator

**Checkpoint**: At this point, User Stories 1, 2, AND 3 should all work - users can extract in parallel with automatic rate limit handling and real-time progress.

---

## Phase 6: User Story 4 - Resume Failed Parallel Extraction (Priority: P3)

**Goal**: Enable fault tolerance by allowing users to resume interrupted parallel extractions from checkpoints without re-processing completed work.

**Independent Test**: Interrupt extraction mid-way (Ctrl+C or kill) and verify:
- Restart extraction with same parameters
- System resumes from last checkpoint per content type
- No duplicate items in final dataset
- Extraction completes successfully

### Implementation for User Story 4

- [ ] T028 [US4] Ensure checkpoints are thread-safe in ParallelOrchestrator
  - Producer thread creates checkpoint when starting content type
  - Producer thread marks checkpoint complete when all batches queued
  - Use BEGIN IMMEDIATE for checkpoint writes (already in foundational phase)
- [ ] T029 [US4] Implement checkpoint-based resume logic in ParallelOrchestrator._producer_worker()
  - Before extracting content type, check for existing complete checkpoint
  - Skip extraction if checkpoint exists and is marked complete
  - Log resume action for user visibility
- [ ] T030 [US4] Handle partial checkpoint recovery
  - If checkpoint exists but not complete, log warning
  - Re-extract content type (upserts handle duplicates)
  - Update checkpoint on successful completion
- [ ] T031 [US4] Add resume flag validation in extract command
  - Existing --resume flag should work with parallel extraction
  - Document behavior: resumes at content-type level (not page-level)
  - Ensure backward compatibility with sequential extraction
- [ ] T032 [US4] Test idempotency of parallel extraction
  - Running extraction twice should produce same final dataset
  - Upserts in repository handle duplicate writes
  - Verify no data corruption on resume

**Checkpoint**: All user stories (1-4) should now be independently functional - parallel extraction with progress, rate limiting, and resume capability.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories and production readiness

- [ ] T033 [P] Add comprehensive logging for parallel extraction
  - Log worker startup/shutdown in ParallelOrchestrator
  - Log queue depths and worker utilization
  - Log rate limit events (429 detected, backoff applied, recovery)
  - Add debug-level logging for troubleshooting
- [ ] T034 [P] Add error handling for edge cases
  - Handle queue overflow gracefully (should block producer)
  - Handle worker thread exceptions without crashing orchestrator
  - Handle SQLite SQLITE_BUSY errors with retry logic
- [ ] T035 [P] Performance tuning and optimization
  - Benchmark sequential vs parallel extraction (1, 2, 4, 8, 16 workers)
  - Tune default worker count based on benchmarks
  - Tune queue size based on memory usage
  - Document optimal batch_size for different content types
- [ ] T036 [P] Add memory monitoring integration
  - Integrate with existing MemoryAwareBatchProcessor
  - Log memory usage warnings with parallel extraction
  - Consider backpressure if memory exceeds threshold
- [ ] T037 [P] Documentation updates in CLAUDE.md and quickstart.md
  - Document --workers option usage
  - Document rate limiting configuration
  - Add troubleshooting guide for common parallel extraction issues
  - Add performance tuning guidelines
- [ ] T038 [P] Add validation for parallel extraction configuration
  - Warn if workers > 16 (SQLite contention limit)
  - Warn if queue_size too small (potential starvation)
  - Suggest optimal configuration based on content type counts
- [ ] T039 Code cleanup and refactoring
  - Remove any debug code
  - Ensure consistent error messages
  - Verify all type hints are correct
  - Run ruff format and ruff check --fix
- [ ] T040 Run ty check for type safety
  - Verify all type annotations are correct
  - Fix any type errors
- [ ] T041 Final integration testing with real Looker instance
  - Extract large dataset (10k+ items) with various worker counts
  - Verify throughput improvements (target: 8x with 8 workers)
  - Verify memory stays under 2GB
  - Verify no data corruption or loss

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phases 3-6)**: All depend on Foundational phase completion
  - US1 (P1): Can start after Foundational - No dependencies on other stories
  - US2 (P2): Can start after Foundational - Builds on US1 but independently testable
  - US3 (P2): Can start after Foundational - Builds on US1 but independently testable
  - US4 (P3): Can start after Foundational - Leverages US1 infrastructure
- **Polish (Phase 7)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - Core parallel extraction, NO dependencies
- **User Story 2 (P2)**: Can start after Foundational (Phase 2) - Progress tracking, builds on US1 orchestrator
- **User Story 3 (P2)**: Can start after Foundational (Phase 2) - Rate limiting, integrates with US1 extractor
- **User Story 4 (P3)**: Can start after Foundational (Phase 2) - Resume logic, leverages US1 checkpoints

**Note**: US2, US3, and US4 all build on US1's ParallelOrchestrator but can be implemented in parallel by different developers since they modify different components (progress, rate limiter, resume logic).

### Within Each User Story

- **US1**: Metrics [P] and WorkQueue [P] → ParallelOrchestrator → CLI integration
- **US2**: ParallelProgressTracker [P] and failure isolation → throughput calculation
- **US3**: AdaptiveRateLimiter [P] and RateLimiterState [P] → extractor integration → CLI options
- **US4**: Thread-safe checkpoints → resume logic → testing

### Parallel Opportunities

**Setup Phase**:
- T002 and T003 can run in parallel

**Foundational Phase**:
- T006 (WorkItem) and T007 (ParallelConfig) can run in parallel

**User Story 1**:
- T008 (ThreadSafeMetrics) and T009 (WorkQueue) can run in parallel
- After T010 (orchestrator) completes, T011-T014 can proceed sequentially

**User Story 2**:
- T015 (ParallelProgressTracker) and T016 (progress updates) can run in parallel

**User Story 3**:
- T021 (AdaptiveRateLimiter) and T022 (RateLimiterState) can run in parallel

**Polish Phase**:
- T033, T034, T035, T036, T037, T038 can all run in parallel (different concerns)

**Parallel Team Strategy**:
- After Foundational complete, developers can work on US1, US2, US3 simultaneously
- US1 developer: Core orchestrator
- US2 developer: Progress tracking
- US3 developer: Rate limiting
- US4 can start once US1 orchestrator is stable

---

## Parallel Example: User Story 1

```bash
# Launch parallel tasks for User Story 1:
Task: "Create ThreadSafeMetrics class in src/lookervault/extraction/metrics.py"
Task: "Create WorkQueue class in src/lookervault/extraction/work_queue.py"

# Then sequentially:
Task: "Create ParallelOrchestrator class in src/lookervault/extraction/orchestrator.py"
Task: "Add --workers CLI option to extract command in src/lookervault/cli/commands/extract.py"
```

---

## Parallel Example: User Story 3

```bash
# Launch parallel tasks for User Story 3:
Task: "Create AdaptiveRateLimiter class in src/lookervault/extraction/rate_limiter.py"
Task: "Create RateLimiterState dataclass in src/lookervault/extraction/rate_limiter.py"

# Then sequentially:
Task: "Integrate AdaptiveRateLimiter into LookerContentExtractor"
Task: "Add CLI options for rate limiting"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (3 tasks, ~30 minutes)
2. Complete Phase 2: Foundational (4 tasks, ~2 hours) - CRITICAL
3. Complete Phase 3: User Story 1 (7 tasks, ~4 hours)
4. **STOP and VALIDATE**: Test parallel extraction with `--workers 8`
5. Benchmark: Compare --workers 1 vs --workers 8 throughput
6. Demo MVP if ready

**Estimated MVP Time**: 1 day (assuming tasks done sequentially)

### Incremental Delivery

1. **Day 1**: Setup + Foundational + US1 → Parallel extraction working (MVP!)
2. **Day 2**: US2 → Progress tracking and monitoring
3. **Day 3**: US3 → Rate limiting for production use
4. **Day 4**: US4 → Resume capability for fault tolerance
5. **Day 5**: Polish → Production-ready release

Each user story adds value without breaking previous functionality.

### Parallel Team Strategy (3 Developers)

**Day 1** (All Together):
- Complete Setup + Foundational (blocks everyone)

**Day 2-4** (Parallel Work):
- **Developer A**: US1 (Core orchestrator) - **MUST finish first**
- **Developer B**: Wait for US1 orchestrator, then US2 (Progress tracking)
- **Developer C**: Wait for US1 orchestrator, then US3 (Rate limiting)

**Day 4-5**:
- **Developer A**: US4 (Resume logic)
- **Developer B + C**: Polish tasks in parallel

**Constraint**: US2, US3, US4 all need US1's ParallelOrchestrator to exist before they can integrate, so US1 has highest priority.

---

## Summary

**Total Tasks**: 41 tasks across 7 phases
- **Phase 1 (Setup)**: 3 tasks
- **Phase 2 (Foundational)**: 4 tasks - **BLOCKING**
- **Phase 3 (US1 - P1)**: 7 tasks - **MVP CORE**
- **Phase 4 (US2 - P2)**: 6 tasks
- **Phase 5 (US3 - P2)**: 7 tasks
- **Phase 6 (US4 - P3)**: 5 tasks
- **Phase 7 (Polish)**: 9 tasks

**Parallel Opportunities**: 16 tasks marked [P] can run concurrently

**MVP Scope** (User Story 1 only): 14 tasks (Setup + Foundational + US1)

**Independent Test Criteria**:
- US1: Parallel extraction faster than sequential, no data loss
- US2: Real-time progress with throughput metrics
- US3: Automatic rate limit handling, extraction completes
- US4: Resume from checkpoint without duplicates

**Expected Performance**: 50,000 items in <15 minutes with 10 workers (vs. 2+ hours sequential)

---

## Notes

- [P] tasks = different files, no dependencies, can run in parallel
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Focus on US1 first - it's the foundation for US2, US3, US4
- Run `ruff format` and `ty check` after each major task
- Test thoroughly with real Looker data before declaring story complete
