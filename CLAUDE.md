## Project Overview

LookerVault is a Looker content backup/restore tool with parallel extraction, cloud storage, and YAML export/import capabilities.

**Issue Tracking**: This project uses [bd (beads)](https://github.com/steveyegge/beads) for issue tracking. Use `bd` commands instead of markdown TODOs. See @AGENTS.md for workflow details.

## Package Management

**CRITICAL**: This project uses `uv` exclusively for Python package management.

- **DO NOT** use `pip install`, `pip freeze`, `virtualenv`, `poetry`, or similar tools
- **DO NOT** manually edit `[project]`, `[project.optional-dependencies]`, `[project.scripts]`, or `[build-system]` in pyproject.toml
- **DO** use `uv` commands: `uv add <package>`, `uv add --dev <package>`, `uv sync`, `uv lock`

**pyproject.toml**: Only manually edit `[tool.*]` sections. Dependencies are managed by `uv add` commands.

## Code Conventions

### Absolute Imports

**CRITICAL**: This project uses absolute imports exclusively.

- **DO** use: `from lookervault.config.models import Configuration`
- **DO NOT** use relative imports: `from ..config.models import Configuration`

## Code Quality Tools

### Pre-Commit Requirements

**CRITICAL**: Run ALL checks before committing:

```bash
uvx ruff format              # Format code
uvx ruff check --fix         # Lint and auto-fix
uvx ty check                 # Type check
uv run pytest                # Run tests
```

### Tools

- **Ruff**: Fast linter/formatter (replaces Black, Flake8, isort). Config: `pyproject.toml` `[tool.ruff]`
- **Ty**: Fast type checker (mypy alternative). Config: `pyproject.toml` `[tool.ty]`

## Tech Stack

- Python 3.13
- looker-sdk, typer, pydantic, tenacity, rich, msgspec, PyYAML
- SQLite (local storage)
- Google Cloud Storage (cloud snapshots)

## Architecture Overview

### Parallel Content Extraction

High-performance extraction using dynamic work stealing pattern with parallel API fetching. Achieves 400-600 items/second (8-16 workers) vs. ~50 items/second sequential.

**Key features**: Parallel API fetching, adaptive rate limiting, checkpoint-based resume, thread-safe SQLite, multi-folder SDK optimization (10x speedup).

**Important**: Only dashboards and looks support SDK-level `folder_id` filtering. Other content types require in-memory filtering.

**Module**: `src/lookervault/extraction/`

**CLI**: `lookervault extract --workers 8 dashboards`

**Docs**: See `specs/003-parallel-extraction/` for detailed architecture

### Folder Filtering

- **Dashboards/Looks**: SDK-level filtering via `search_dashboards(folder_id="123")` (fast)
- **Other types**: In-memory filtering after fetching all items (slower)
- **Multi-folder**: N parallel SDK calls for dashboards/looks (10x faster than in-memory filtering)

---

### Content Restoration

Restores Looker content from SQLite backups with dependency-aware ordering, parallel workers, and robust error recovery.

**Key features**: Single-item and bulk restoration, dependency ordering (Users → Groups → Folders → Looks → Dashboards → Boards), Dead Letter Queue (DLQ) for failures, checkpoint-based resume, dry-run mode.

**Module**: `src/lookervault/restoration/`

**CLI**: `lookervault restore single dashboard <id>` or `lookervault restore bulk dashboards --workers 8`

**Important**: Same-instance only (no cross-instance ID remapping). Always use `--dry-run` first.

**Docs**: See `specs/004-looker-restoration/` for detailed architecture

### Cloud Snapshot Management

GCS-backed snapshot storage with automated retention policies and interactive selection UI.

**Module**: `src/lookervault/snapshot/`

**CLI**: `lookervault snapshot upload --name "backup-name"`, `lookervault snapshot list`, `lookervault snapshot download <id>`

**Docs**: See `specs/005-cloud-snapshot-storage/` for details

---

### YAML Export/Import

Bidirectional conversion between SQLite backups and human-editable YAML files for bulk content modification workflows.

**Export strategies**:
- `--strategy full`: Organize by content type (`dashboards/`, `looks/`, etc.) - best for bulk operations
- `--strategy folder`: Mirror Looker folder hierarchy - best for folder-scoped modifications

**Key features**: Query remapping (auto-creates new query objects for modified dashboards), multi-stage validation (syntax, schema, SDK, business rules), path sanitization, modification tracking.

**Module**: `src/lookervault/export/`

**CLI**:
```bash
# Export: SQLite → YAML
lookervault unpack --output-dir export/ --strategy full

# Modify YAML files
sed -i 's/old_model/new_model/g' export/dashboards/*.yaml

# Import: YAML → SQLite
lookervault pack --input-dir export/ --dry-run  # Validate first
lookervault pack --input-dir export/            # Then import
```

**Workflow**: Extract → Unpack → Modify YAML → Pack → Restore

**Docs**: See `specs/006-yaml-export-import/` for detailed architecture

