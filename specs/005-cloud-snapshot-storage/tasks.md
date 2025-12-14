# Tasks: Cloud Snapshot Storage & Management

**Input**: Design documents from `/specs/005-cloud-snapshot-storage/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-commands.md

**Tests**: Tests are NOT explicitly requested in the feature specification, so they are excluded from this task breakdown. Focus is on implementation only.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `src/lookervault/`, `tests/` at repository root
- Paths assume single project structure as specified in plan.md

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and dependency installation

- [X] T001 Add google-cloud-storage dependency via `uv add google-cloud-storage`
- [X] T002 [P] Add google-crc32c dependency via `uv add google-crc32c`
- [X] T003 [P] SKIPPED: rich-menu has dependency conflict with Rich 14.2.0. Implemented interactive UI using built-in Menu class instead (no extra dependency needed).
- [X] T004 Create snapshot module directory at src/lookervault/snapshot/
- [X] T005 Create snapshot CLI commands directory at src/lookervault/cli/commands/snapshot.py
- [X] T006 [P] Update lookervault.toml.example with snapshot configuration section
- [X] T007 [P] Create tests/unit/snapshot/ directory for unit tests
- [X] T008 [P] Create tests/integration/ directory if it doesn't exist

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T009 Create Pydantic models for snapshot configuration in src/lookervault/snapshot/models.py (SnapshotMetadata, RetentionPolicy, GCSStorageProvider, SnapshotConfig)
- [X] T010 Implement GCS client abstraction with ADC authentication in src/lookervault/snapshot/client.py (create_storage_client function with error handling)
- [X] T011 Update src/lookervault/config/models.py to add SnapshotConfig to main Configuration model
- [X] T012 Update src/lookervault/config/loader.py to load snapshot configuration from lookervault.toml and environment variables
- [X] T013 Create snapshot CLI command group in src/lookervault/cli/commands/snapshot.py with placeholder subcommands
- [X] T014 Register snapshot command group in src/lookervault/cli/main.py

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Upload Snapshot to Cloud Storage (Priority: P1) 🎯 MVP

**Goal**: Enable administrators to upload local database snapshots to Google Cloud Storage with timestamped filenames and compression

**Independent Test**: Run `lookervault snapshot upload` and verify snapshot appears in GCS with correct filename format (looker-YYYY-MM-DDTHH-MM-SS.db.gz) and CRC32C checksum verification

### Implementation for User Story 1

- [X] T015 [P] [US1] Implement compression logic in src/lookervault/snapshot/uploader.py (compress_file function with gzip, progress tracking)
- [X] T016 [P] [US1] Implement CRC32C checksum computation in src/lookervault/snapshot/uploader.py (compute_crc32c function)
- [X] T017 [US1] Implement snapshot upload with resumable upload in src/lookervault/snapshot/uploader.py (upload_snapshot function with retry logic, progress bar)
- [X] T018 [US1] Implement timestamp generation logic in src/lookervault/snapshot/uploader.py (generate_snapshot_filename function using UTC timestamp)
- [X] T019 [US1] Implement upload CLI command in src/lookervault/cli/commands/snapshot.py (upload subcommand with --source, --compress, --compression-level, --dry-run, --json flags)
- [X] T020 [US1] Add error handling for authentication failures in src/lookervault/snapshot/uploader.py (catch DefaultCredentialsError, display helpful messages)
- [X] T021 [US1] Add error handling for network failures with retry logic in src/lookervault/snapshot/uploader.py (use tenacity or SDK DEFAULT_RETRY)
- [X] T022 [US1] Implement dry-run mode for upload command in src/lookervault/snapshot/uploader.py (validate configuration, skip actual upload)
- [X] T023 [US1] Add JSON output support for upload command in src/lookervault/cli/commands/snapshot.py (return snapshot metadata as JSON when --json flag used)

**Checkpoint**: At this point, User Story 1 should be fully functional - users can upload snapshots to GCS

---

## Phase 4: User Story 2 - List Available Snapshots (Priority: P1)

**Goal**: Enable administrators to list all available snapshots in cloud storage sorted by date with sequential indices

**Independent Test**: Upload 2-3 snapshots, run `lookervault snapshot list`, verify snapshots appear sorted by date (newest first) with sequential indices (1, 2, 3...)

### Implementation for User Story 2

- [X] T024 [P] [US2] Implement snapshot listing logic in src/lookervault/snapshot/lister.py (list_snapshots function with GCS pagination, sorting by creation time)
- [X] T025 [P] [US2] Implement sequential index assignment in src/lookervault/snapshot/lister.py (assign indices 1, 2, 3... to sorted snapshots)
- [X] T026 [P] [US2] Implement local caching for snapshot listings in src/lookervault/snapshot/lister.py (BlobCache class with 5-minute TTL, JSON storage)
- [X] T027 [US2] Implement timestamp parsing from filename in src/lookervault/snapshot/lister.py (parse_timestamp_from_filename function)
- [X] T028 [US2] Implement list CLI command in src/lookervault/cli/commands/snapshot.py (list subcommand with --limit, --filter, --verbose, --json, --no-cache flags)
- [X] T029 [US2] Implement Rich table output for snapshot listing in src/lookervault/cli/commands/snapshot.py (use Rich Table widget with columns: Index, Filename, Timestamp, Size, Age)
- [X] T030 [US2] Implement verbose mode output in src/lookervault/cli/commands/snapshot.py (detailed metadata display for each snapshot)
- [X] T031 [US2] Implement filtering by date range in src/lookervault/snapshot/lister.py (filter_by_date_range function supporting "last-7-days", "last-30-days", "YYYY-MM" patterns)
- [X] T032 [US2] Add JSON output support for list command in src/lookervault/cli/commands/snapshot.py (return list of snapshot metadata as JSON when --json flag used)

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently - users can upload and list snapshots

---

## Phase 5: User Story 3 - Download Snapshot to Local (Priority: P2)

**Goal**: Enable administrators to download specific snapshots from cloud storage to local machine for restoration

**Independent Test**: Upload a snapshot, run `lookervault snapshot download 1`, verify snapshot is downloaded to ./looker.db with CRC32C checksum verification

### Implementation for User Story 3

- [X] T033 [P] [US3] Implement snapshot lookup by index in src/lookervault/snapshot/lister.py (get_snapshot_by_index function)
- [X] T034 [P] [US3] Implement snapshot lookup by timestamp in src/lookervault/snapshot/lister.py (get_snapshot_by_timestamp function)
- [X] T035 [US3] Implement snapshot download logic in src/lookervault/snapshot/downloader.py (download_snapshot function with progress tracking, checksum verification)
- [X] T036 [US3] Implement decompression logic in src/lookervault/snapshot/downloader.py (decompress_file function for gzipped snapshots)
- [X] T037 [US3] Implement CRC32C checksum verification after download in src/lookervault/snapshot/downloader.py (verify_download_integrity function)
- [X] T038 [US3] Implement download CLI command in src/lookervault/cli/commands/snapshot.py (download subcommand with SNAPSHOT_REF argument, --output, --overwrite, --verify-checksum, --json flags)
- [X] T039 [US3] Add overwrite confirmation prompt in src/lookervault/cli/commands/snapshot.py (use typer.confirm when file exists and --overwrite not set)
- [X] T040 [US3] Add error handling for invalid snapshot references in src/lookervault/cli/commands/snapshot.py (display helpful error message, suggest running list command)
- [X] T041 [US3] Add error handling for checksum mismatch in src/lookervault/snapshot/downloader.py (delete corrupted file, display clear error message)
- [X] T042 [US3] Add JSON output support for download command in src/lookervault/cli/commands/snapshot.py (return download metadata as JSON when --json flag used)

**Checkpoint**: At this point, User Stories 1, 2, AND 3 should all work independently - users can upload, list, and download snapshots

---

## Phase 6: User Story 4 - Restore Directly from Cloud Snapshot (Priority: P2)

**Goal**: Enable administrators to restore Looker content directly from cloud snapshots without manual download step

**Independent Test**: Upload a snapshot, run `lookervault restore --from-snapshot 1`, verify snapshot is downloaded to temp location and restoration proceeds

### Implementation for User Story 4

- [X] T043 [P] [US4] Add --from-snapshot flag to restore command in src/lookervault/cli/commands/restore.py (optional argument accepting index or timestamp)
- [X] T044 [US4] Implement temporary snapshot download logic in src/lookervault/restoration/snapshot_integration.py (download_snapshot_to_temp function that downloads to /tmp/lookervault-snapshot-{timestamp}.db)
- [X] T045 [US4] Integrate snapshot download with restore orchestrator in src/lookervault/cli/commands/restore.py (modify restore_single and restore_bulk to accept from_snapshot parameter, download before restoration)
- [X] T046 [US4] Implement temporary file cleanup after restoration in src/lookervault/restoration/snapshot_integration.py (cleanup_temp_snapshot function, called after restore completion or failure)
- [X] T047 [US4] Add snapshot metadata display before restoration in src/lookervault/cli/commands/restore.py (fetch and display snapshot info when --from-snapshot used)
- [X] T048 [US4] Add error handling for snapshot download failures during restore in src/lookervault/cli/commands/restore.py (report error, do not attempt restoration from incomplete data)
- [X] T049 [US4] Ensure --dry-run works with --from-snapshot flag in src/lookervault/cli/commands/restore.py (download to temp, validate, cleanup without restoring)
- [X] T050 [US4] Verify all existing restore flags work with --from-snapshot in src/lookervault/cli/commands/restore.py (workers, content types, rate limits)

**Checkpoint**: All P1 and P2 user stories complete - core snapshot backup/restore functionality fully operational

---

## Phase 7: User Story 5 - Automatic Retention Policy Enforcement (Priority: P3)

**Goal**: Automatically delete old snapshots based on configured retention policies to control storage costs

**Independent Test**: Set retention policy (min_days=7, max_days=30, min_count=3), upload 5 snapshots with varying ages, run cleanup, verify old snapshots deleted while minimum count protected

### Implementation for User Story 5

- [X] T051 [P] [US5] Implement retention policy evaluation logic in src/lookervault/snapshot/retention.py (evaluate_retention_policy function that identifies snapshots to protect/delete)
- [X] T052 [P] [US5] Implement minimum backup count protection in src/lookervault/snapshot/retention.py (protect_minimum_backups function that applies temporary holds)
- [X] T053 [US5] Implement snapshot deletion logic in src/lookervault/snapshot/retention.py (delete_old_snapshots function with error handling)
- [X] T054 [US5] Implement GCS bucket retention policy configuration in src/lookervault/snapshot/retention.py (configure_gcs_retention_policy function)
- [X] T055 [US5] Implement GCS lifecycle policy configuration in src/lookervault/snapshot/retention.py (configure_gcs_lifecycle_policy function for automatic age-based deletion)
- [X] T056 [US5] Implement cleanup CLI command in src/lookervault/cli/commands/snapshot.py (cleanup subcommand with --dry-run, --force, --older-than, --json flags)
- [X] T057 [US5] Implement audit logging for deletions in src/lookervault/snapshot/retention.py (AuditLogger class with log_deletion method, JSON Lines format)
- [X] T058 [US5] Add dry-run preview for cleanup command in src/lookervault/snapshot/retention.py (display snapshots to protect and delete with counts)
- [X] T059 [US5] Add confirmation prompt for cleanup command in src/lookervault/cli/commands/snapshot.py (use typer.confirm when --force not set)
- [X] T060 [US5] Add JSON output support for cleanup command in src/lookervault/cli/commands/snapshot.py (return cleanup summary as JSON when --json flag used)
- [X] T061 [US5] Implement error handling for protected snapshots in src/lookervault/snapshot/retention.py (skip deletion, log warning, continue with cleanup)
- [X] T062 [US5] Implement safety mechanism to prevent deleting all snapshots in src/lookervault/snapshot/retention.py (enforce minimum retention count, fail if would delete below threshold)

**Checkpoint**: Retention policy enforcement complete - automated cost control operational

---

## Phase 8: User Story 6 - Interactive Snapshot Selection UI (Priority: P3)

**Goal**: Provide interactive terminal UI for browsing and selecting snapshots with keyboard navigation

**Independent Test**: Run `lookervault snapshot list --interactive`, verify arrow key navigation works, preview panel shows metadata, Enter selects snapshot

### Implementation for User Story 6

- [X] T063 [P] [US6] Implement interactive snapshot picker using Menu class in src/lookervault/snapshot/ui.py (interactive_snapshot_picker function with menu items from snapshots list) - Implemented using custom Menu class instead of rich-menu to avoid dependency conflicts
- [X] T064 [P] [US6] Implement terminal capability detection in src/lookervault/snapshot/ui.py (detect_interactive_mode function using sys.stdout.isatty())
- [X] T065 [US6] Add --interactive flag to download command in src/lookervault/cli/commands/snapshot.py (launch interactive picker if flag set)
- [X] T066 [US6] SKIPPED: delete command not yet implemented (Additional Features phase)
- [X] T067 [US6] SKIPPED: --from-snapshot already integrated in restore.py, interactive mode can be added later if needed
- [X] T068 [US6] Implement graceful fallback to non-interactive mode in src/lookervault/snapshot/ui.py (auto-detect when terminal doesn't support interactive, raises RuntimeError with helpful message)
- [X] T069 [US6] Implement preview panel with snapshot metadata in src/lookervault/snapshot/ui.py (display filename, created date, size, age, CRC32C, encoding, tags)
- [X] T070 [US6] Add help text for keyboard navigation in src/lookervault/snapshot/ui.py (display arrow key usage, Enter to select, ESC to cancel)

**Checkpoint**: All user stories complete - full snapshot management feature set operational

---

## Phase 9: Additional Features (Optional)

**Purpose**: Additional CLI commands and utilities beyond core user stories

- [ ] T071 [P] Implement delete CLI command in src/lookervault/cli/commands/snapshot.py (delete subcommand with SNAPSHOT_REF argument, --force, --dry-run, --json flags)
- [ ] T072 [P] Implement delete confirmation prompt in src/lookervault/cli/commands/snapshot.py (display snapshot metadata, confirm before deletion)
- [ ] T073 [P] Implement delete operation in src/lookervault/snapshot/retention.py (delete_snapshot function with audit logging)
- [ ] T074 [P] Add soft delete reminder in delete output in src/lookervault/cli/commands/snapshot.py (inform user about 7-day GCS soft delete recovery period)

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T075 [P] Add comprehensive error messages for all authentication failures in src/lookervault/snapshot/client.py (provide troubleshooting steps for GOOGLE_APPLICATION_CREDENTIALS, gcloud auth)
- [ ] T076 [P] Add comprehensive error messages for all network failures in src/lookervault/snapshot/uploader.py and src/lookervault/snapshot/downloader.py (retry suggestions, firewall checks)
- [ ] T077 [P] Validate lookervault.toml snapshot configuration schema in src/lookervault/config/validator.py (check bucket_name format, region validity, compression_level range)
- [ ] T078 [P] Add progress bars for all long-running operations in src/lookervault/snapshot/uploader.py and src/lookervault/snapshot/downloader.py (use Rich Progress for compression, upload, download)
- [ ] T079 [P] Update README.md with snapshot management section linking to quickstart.md
- [ ] T080 [P] Update CLAUDE.md Active Technologies section with google-cloud-storage, google-crc32c, rich-menu
- [ ] T081 Code cleanup: remove any debug logging, ensure consistent error handling patterns across all snapshot modules
- [ ] T082 Run ruff format and ruff check --fix on all new snapshot code
- [ ] T083 Run ty check on all new snapshot code to verify type safety
- [ ] T084 Validate quickstart.md workflows manually: test 5-minute quick start, daily backup automation, disaster recovery test, retention management, migration workflow

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-8)**: All depend on Foundational phase completion
  - User Stories 1-2 (P1): Can proceed in parallel after Foundational
  - User Stories 3-4 (P2): Can proceed in parallel after Foundational (US3 benefits from US1-2 for testing)
  - User Stories 5-6 (P3): Can proceed in parallel after Foundational (US5 benefits from US1-2 for cleanup testing)
- **Additional Features (Phase 9)**: Depends on Foundational - can run anytime
- **Polish (Phase 10)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational - No dependencies on other stories
- **User Story 2 (P1)**: Can start after Foundational - No dependencies on other stories (but benefits from US1 for testing)
- **User Story 3 (P2)**: Can start after Foundational - Integrates with US2 (list) but independently testable
- **User Story 4 (P2)**: Can start after Foundational - Integrates with US2 (list) and US3 (download) but independently testable
- **User Story 5 (P3)**: Can start after Foundational - Benefits from US1-2 for cleanup testing
- **User Story 6 (P3)**: Can start after Foundational - Integrates with US2 (list), US3 (download), US4 (restore) but independently testable

### Within Each User Story

- Models before services (Foundational phase handles this)
- Services before CLI commands
- Core implementation before error handling and JSON output
- Story complete before moving to next priority

### Parallel Opportunities

- **Setup (Phase 1)**: T002, T003, T006, T007, T008 can all run in parallel
- **Foundational (Phase 2)**: No parallel tasks (sequential setup required)
- **User Story 1**: T015, T016 can run in parallel (different functions)
- **User Story 2**: T024, T025, T026 can run in parallel (different functions in lister.py)
- **User Story 3**: T033, T034 can run in parallel (different functions); T035, T036, T037 are sequential
- **User Story 4**: T043, T044 can run in parallel (different files)
- **User Story 5**: T051, T052 can run in parallel (different functions)
- **User Story 6**: T063, T064 can run in parallel (different functions)
- **Additional Features (Phase 9)**: T071, T072, T073, T074 can run in parallel
- **Polish (Phase 10)**: T075, T076, T077, T078, T079, T080 can all run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch compression and checksum logic in parallel:
Task: "Implement compression logic in src/lookervault/snapshot/uploader.py"
Task: "Implement CRC32C checksum computation in src/lookervault/snapshot/uploader.py"

# Then implement upload function (depends on both):
Task: "Implement snapshot upload with resumable upload in src/lookervault/snapshot/uploader.py"
```

## Parallel Example: User Story 2

```bash
# Launch all listing functions in parallel:
Task: "Implement snapshot listing logic in src/lookervault/snapshot/lister.py"
Task: "Implement sequential index assignment in src/lookervault/snapshot/lister.py"
Task: "Implement local caching for snapshot listings in src/lookervault/snapshot/lister.py"
```

---

## Implementation Strategy

### MVP First (User Stories 1-2 Only - P1 Features)

1. Complete Phase 1: Setup → Dependencies installed
2. Complete Phase 2: Foundational → Core models and config ready
3. Complete Phase 3: User Story 1 → Upload functionality working
4. Complete Phase 4: User Story 2 → List functionality working
5. **STOP and VALIDATE**: Test upload and list commands independently
6. Deploy/demo if ready (users can now upload and view snapshots)

**MVP Delivery**: 23 tasks (T001-T023) for core backup capability

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready (14 tasks)
2. Add User Story 1 → Upload working (9 tasks) → Deploy/Demo (MVP!)
3. Add User Story 2 → List working (9 tasks) → Deploy/Demo
4. Add User Story 3 → Download working (10 tasks) → Deploy/Demo
5. Add User Story 4 → Restore from snapshot working (8 tasks) → Deploy/Demo
6. Add User Story 5 → Retention policy working (12 tasks) → Deploy/Demo
7. Add User Story 6 → Interactive UI working (8 tasks) → Deploy/Demo
8. Polish → Production-ready (10 tasks)

**Total**: 84 tasks across all phases

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together (14 tasks)
2. Once Foundational is done:
   - Developer A: User Story 1 (Upload) - 9 tasks
   - Developer B: User Story 2 (List) - 9 tasks
   - Developer C: User Story 3 (Download) - 10 tasks
3. Stories complete and integrate independently
4. Proceed to User Story 4-6 with same parallel approach

---

## Notes

- [P] tasks = different files/functions, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Tests NOT included (not requested in feature specification)
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Avoid: vague tasks, same file conflicts, cross-story dependencies that break independence
- All file paths use absolute imports starting from lookervault package root
- Follow existing LookerVault patterns: Typer for CLI, Pydantic for config, Rich for output
