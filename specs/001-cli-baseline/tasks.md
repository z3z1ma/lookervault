# Tasks: Base CLI with Looker Connectivity

**Input**: Design documents from `/specs/001-cli-baseline/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-commands.md

**Tests**: Tests are NOT explicitly requested in the feature specification, so test tasks are omitted.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `src/`, `tests/` at repository root
- Paths use the structure defined in plan.md

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [X] T001 Create project directory structure: src/lookervault/{cli/commands,config,looker}/ and tests/{unit,integration,fixtures}/
- [X] T002 [P] Create all __init__.py files in src/lookervault/, src/lookervault/cli/, src/lookervault/cli/commands/, src/lookervault/config/, src/lookervault/looker/
- [X] T003 [P] Add tool configurations (pytest, mypy, ruff) to pyproject.toml
- [X] T004 [P] Create .env.example file with LOOKERVAULT_CLIENT_ID, LOOKERVAULT_CLIENT_SECRET, LOOKERVAULT_API_URL
- [X] T005 Add production dependencies using uv: typer[all]>=0.9.0, looker-sdk>=24.0.0, pydantic>=2.0.0, tomli-w>=1.0.0
- [X] T006 Add development dependencies using uv: pytest>=7.4.0, pytest-mock>=3.12.0, pytest-cov>=4.1.0, mypy>=1.8.0, ruff>=0.1.0

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T007 [P] Create Pydantic models in src/lookervault/config/models.py: LookerConfig, OutputConfig, Configuration
- [X] T008 [P] Create additional Pydantic models in src/lookervault/config/models.py: ConnectionStatus, LookerInstance, ReadinessCheckResult, CheckItem
- [X] T009 [P] Create custom exception classes in src/lookervault/exceptions.py: ConfigError, ConnectionError
- [X] T010 Implement config path resolution in src/lookervault/config/loader.py: get_config_path() function
- [X] T011 Implement config loading with env var merging in src/lookervault/config/loader.py: load_config() function
- [X] T012 [P] Implement Looker SDK client wrapper in src/lookervault/looker/client.py: LookerClient class with _init_sdk(), sdk property, test_connection()
- [X] T013 [P] Create output formatting utilities in src/lookervault/cli/output.py: format_table() and format_json() functions

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - CLI Initialization and Readiness Checks (Priority: P1) 🎯 MVP

**Goal**: Provide help/version commands and readiness checks to validate installation and configuration

**Independent Test**: Run `lookervault --help`, `lookervault --version`, and `lookervault check` to verify CLI is operational and configuration is valid

### Implementation for User Story 1

- [X] T014 [P] [US1] Create main Typer app in src/lookervault/cli/main.py with help text, version callback, and global options
- [X] T015 [P] [US1] Create __main__.py entry point in src/lookervault/__main__.py that imports and runs the Typer app
- [X] T016 [US1] Implement readiness check logic in src/lookervault/config/validator.py: check_config_file(), check_config_valid(), check_credentials(), check_python_version(), check_dependencies()
- [X] T017 [US1] Create check command implementation in src/lookervault/cli/commands/check.py: run() function with readiness checks
- [X] T018 [US1] Integrate check command into main Typer app in src/lookervault/cli/main.py
- [X] T019 [US1] Add table output formatting for readiness check in src/lookervault/cli/output.py: format_readiness_check_table()
- [X] T020 [US1] Add JSON output formatting for readiness check in src/lookervault/cli/output.py: format_readiness_check_json()
- [X] T021 [US1] Implement exit code handling in check command (0 for ready, 1 for not ready, 2 for config errors)

**Checkpoint**: At this point, User Story 1 should be fully functional - users can verify installation and configuration status

---

## Phase 4: User Story 2 - Looker Instance Connection and Information Display (Priority: P2)

**Goal**: Connect to Looker instance and display instance metadata to confirm connectivity

**Independent Test**: Set valid credentials, run `lookervault info` to verify successful connection and instance details display

### Implementation for User Story 2

- [X] T022 [P] [US2] Implement connection testing in src/lookervault/looker/connection.py: connect_and_get_info() function
- [X] T023 [P] [US2] Create info command implementation in src/lookervault/cli/commands/info.py: run() function that calls LookerClient
- [X] T024 [US2] Integrate info command into main Typer app in src/lookervault/cli/main.py
- [X] T025 [US2] Add table output formatting for instance info in src/lookervault/cli/output.py: format_instance_info_table()
- [X] T026 [US2] Add JSON output formatting for instance info in src/lookervault/cli/output.py: format_instance_info_json()
- [X] T027 [US2] Add error handling for authentication failures in src/lookervault/cli/commands/info.py with exit code 3
- [X] T028 [US2] Add error handling for network/connection failures in src/lookervault/cli/commands/info.py with exit code 3
- [X] T029 [US2] Add actionable error messages for common failure scenarios in src/lookervault/cli/commands/info.py

**Checkpoint**: All user stories should now be independently functional - users can verify installation AND connect to Looker

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [X] T030 [P] Create sample configuration file in tests/fixtures/sample_config.toml
- [X] T031 [P] Create unit test for config loader in tests/unit/test_config_loader.py
- [X] T032 [P] Create unit test for config validator in tests/unit/test_config_validator.py
- [X] T033 [P] Create unit test for output formatting in tests/unit/test_output_formatting.py
- [X] T034 [P] Create unit test for Looker client in tests/unit/test_looker_client.py (with mocked SDK)
- [X] T035 [P] Create integration test for CLI commands in tests/integration/test_cli_commands.py (using CliRunner)
- [X] T036 [P] Create integration test for Looker connection in tests/integration/test_looker_connection.py (may require real credentials or mocking)
- [X] T037 [P] Update README.md with installation instructions, usage examples, and configuration guide
- [X] T038 Run pytest test suite and verify all tests pass
- [X] T039 Run mypy type checking on src/lookervault and fix any type errors
- [X] T040 Run ruff linting on src/ and tests/ and fix any issues
- [X] T041 Validate against quickstart.md manual testing scenarios

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
  - User stories can then proceed in parallel (if staffed)
  - Or sequentially in priority order (P1 → P2)
- **Polish (Final Phase)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - No dependencies on other stories
- **User Story 2 (P2)**: Can start after Foundational (Phase 2) - Reuses config/models from foundation but independently testable

### Within Each User Story

- Models before services (already in Foundational phase)
- Services before commands
- Core implementation before integration
- Output formatting can be done in parallel with command logic
- Error handling added after basic implementation

### Parallel Opportunities

- All Setup tasks marked [P] can run in parallel (T002, T003, T004)
- All Foundational tasks marked [P] can run in parallel within groups:
  - T007, T008, T009 (data models and exceptions)
  - T012, T013 (client wrapper and output utilities)
- Once Foundational phase completes, User Story 1 and User Story 2 can start in parallel (if team capacity allows)
- Within User Story 1: T014, T015 can run in parallel
- Within User Story 2: T022, T023 can run in parallel, T025, T026 can run in parallel
- All Polish tasks marked [P] can run in parallel (T030-T037)

---

## Parallel Example: Foundational Phase

```bash
# Launch all data models together:
Task: "Create Pydantic models in src/lookervault/config/models.py: LookerConfig, OutputConfig, Configuration"
Task: "Create additional Pydantic models in src/lookervault/config/models.py: ConnectionStatus, LookerInstance, ReadinessCheckResult, CheckItem"
Task: "Create custom exception classes in src/lookervault/exceptions.py: ConfigError, ConnectionError"

# After models are done, launch client and output in parallel:
Task: "Implement Looker SDK client wrapper in src/lookervault/looker/client.py"
Task: "Create output formatting utilities in src/lookervault/cli/output.py"
```

## Parallel Example: User Story 1

```bash
# Launch Typer app and entry point together:
Task: "Create main Typer app in src/lookervault/cli/main.py"
Task: "Create __main__.py entry point in src/lookervault/__main__.py"
```

## Parallel Example: User Story 2

```bash
# Launch connection logic and command implementation together:
Task: "Implement connection testing in src/lookervault/looker/connection.py"
Task: "Create info command implementation in src/lookervault/cli/commands/info.py"

# Launch output formatting together:
Task: "Add table output formatting for instance info in src/lookervault/cli/output.py: format_instance_info_table()"
Task: "Add JSON output formatting for instance info in src/lookervault/cli/output.py: format_instance_info_json()"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T006)
2. Complete Phase 2: Foundational (T007-T013) - CRITICAL - blocks all stories
3. Complete Phase 3: User Story 1 (T014-T021)
4. **STOP and VALIDATE**: Test help, version, and check commands independently
5. Demo readiness checks working

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready (T001-T013)
2. Add User Story 1 → Test independently → Deploy/Demo (MVP!) (T014-T021)
3. Add User Story 2 → Test independently → Deploy/Demo (T022-T029)
4. Add Polish tasks → Full baseline complete (T030-T041)
5. Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together (T001-T013)
2. Once Foundational is done:
   - Developer A: User Story 1 (T014-T021)
   - Developer B: User Story 2 (T022-T029)
3. Stories complete and integrate independently
4. Both developers collaborate on Polish phase (T030-T041)

---

## Notes

- [P] tasks = different files, no dependencies - can run in parallel
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Tests are in Polish phase (not TDD approach) since not explicitly requested
- Configuration models in Foundational phase are reused across both user stories
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Use `uv add` for all dependency management (NOT pip)
- Follow exit code conventions: 0=success, 1=general error, 2=config error, 3=connection error, 130=interrupted
