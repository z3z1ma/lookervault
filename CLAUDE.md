**Note**: This project uses [bd (beads)](https://github.com/steveyegge/beads) for issue tracking. Use `bd` commands instead of markdown TODOs. See AGENTS.md for workflow details.

## Package Management

**IMPORTANT**: This project uses `uv` for all Python package management operations.

- **DO NOT** use `pip install`, `pip freeze`, `virtualenv`, `poetry`, or similar tools
- **DO NOT** manually edit `[project]`, `[project.optional-dependencies]`, `[project.scripts]`, or `[build-system]` in pyproject.toml
- **DO** use `uv` commands exclusively:
  - `uv venv` - Create virtual environment
  - `uv add <package>` - Add dependency (manages pyproject.toml and uv.lock automatically)
  - `uv add --dev <package>` - Add dev dependency
  - `uv lock` - Update lockfile
  - `uv sync` - Sync environment with lockfile

**pyproject.toml**: Only manually edit `[tool.*]` sections (pytest, mypy, ruff, etc.). All dependencies and project metadata are managed by `uv add` commands.

## Code Conventions

### Absolute Imports

**IMPORTANT**: This project uses absolute imports exclusively.

- **DO** use absolute imports: `from lookervault.config.models import Configuration`
- **DO NOT** use relative imports: `from ..config.models import Configuration`

All imports should reference the full module path starting from the package root (`lookervault`). This improves code readability, makes refactoring easier, and prevents import errors when files are moved.

**Examples:**
```python
# Good - Absolute imports
from lookervault.config.models import Configuration, ConnectionStatus
from lookervault.looker.client import LookerClient
from lookervault.exceptions import ConfigError

# Bad - Relative imports (DO NOT USE)
from ..config.models import Configuration
from .client import LookerClient
from ...exceptions import ConfigError
```

## Code Quality Tools

This project uses modern Rust-based tools from [Astral](https://astral.sh) for code quality:

### Ruff - Linting and Formatting

**Ruff** is an extremely fast Python linter and code formatter written in Rust. It replaces multiple tools (Black, Flake8, isort, pylint, etc.) with a single, high-performance tool.

**Basic Commands:**
```bash
# Linting
ruff check                    # Lint all files in current directory
ruff check path/to/file.py    # Lint specific file
ruff check --fix              # Lint and auto-fix violations

# Formatting
ruff format                   # Format all files in current directory
ruff format path/to/file.py   # Format specific file
ruff format --check           # Check formatting without modifying files
ruff format --diff            # Show what would be formatted

# Using uvx (no installation required)
uvx ruff check
uvx ruff format
```

**Configuration:** Ruff is configured in `pyproject.toml` under `[tool.ruff]`, `[tool.ruff.lint]`, and `[tool.ruff.format]` sections.

**Key Features:**
- 10-100x faster than traditional Python linters
- Black-compatible code formatting
- 800+ lint rules with auto-fix support
- Native Jupyter Notebook support
- Drop-in replacement for Flake8, isort, and Black

### Ty - Type Checking

**Ty** is an extremely fast Python type checker and language server written in Rust, designed as a modern alternative to mypy.

**Basic Commands:**
```bash
# Type checking
ty check                      # Check entire project (auto-discovers pyproject.toml)
ty check path/to/file.py      # Check specific file
ty check src/ tests/          # Check specific directories
ty check --watch              # Watch mode (recheck on file changes)

# Output formats
ty check --output-format concise    # Concise output
ty check --output-format github     # GitHub Actions annotations
ty check --output-format gitlab     # GitLab Code Quality JSON

# Configuration
ty check --python-version 3.11      # Target specific Python version
ty check --python .venv/bin/python3 # Specify Python environment
ty check -vv                        # Verbose output for debugging

# Using uvx (no installation required)
uvx ty check
```

**Configuration:** Ty is configured in `pyproject.toml` under `[tool.ty]` section.

**Key Features:**
- Significantly faster than mypy (written in Rust)
- Built-in language server for IDE integration
- Watch mode for continuous type checking
- Multiple output formats for CI/CD integration
- Compatible with existing Python type hints

### Workflow Integration

**Development Workflow:**
1. Write code
2. Run `ruff format` to auto-format
3. Run `ruff check --fix` to lint and auto-fix issues
4. Run `ty check` to verify types
5. Run `uv run pytest` to ensure tests pass
6. Commit changes

**Pre-commit Integration:** Both tools work well in pre-commit hooks to ensure code quality before commits.

**Note:** Line length and formatting rules should be consistent between ruff's formatter and linter. Ruff makes a best-effort attempt to wrap lines at the configured `line-length`, but may exceed it in some cases.

## Pre-Commit Requirements

**CRITICAL**: No changes should be committed without running ALL of the following checks:

```bash
# Format code
uvx ruff format

# Lint and auto-fix issues
uvx ruff check --fix

# Type check
uvx ty check

# Run tests
uv run pytest
```

All checks must pass before committing. If any check fails, fix the issues before proceeding with the commit.

## Active Technologies
- Python 3.13 (per pyproject.toml) (001-looker-content-extraction)
- SQLite database with binary blob storage + metadata columns (001-looker-content-extraction)
