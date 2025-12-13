# Research: Base CLI with Looker Connectivity

**Feature**: 001-cli-baseline
**Date**: 2025-12-13
**Status**: Complete

This document captures research findings that resolve technical unknowns identified in the implementation plan.

---

## 1. Configuration File Format: TOML vs YAML

### Decision: **TOML**

### Rationale

1. **Native Python 3.11+ Support**: Python 3.11+ includes `tomllib` in the standard library for reading TOML files with zero dependencies (PEP 680). This aligns with our Python 3.11+ requirement.

2. **Ecosystem Alignment**: LookerVault will use `pyproject.toml` for package metadata. Using TOML for application configuration creates consistency and allows consolidating configuration in a single file.

3. **Simplicity & Type Safety**: TOML enforces strict formatting and explicit typing (strings, integers, floats, booleans, dates), reducing configuration errors compared to YAML's permissiveness.

4. **Python Tooling Standard**: Modern Python tools (black, mypy, pytest, tox, pylint, isort) all use TOML configuration. This is the current ecosystem direction for Python CLI applications.

5. **Human-Readable**: TOML is designed to be minimal and obvious - perfect for configuration files that users will hand-edit.

### Alternatives Considered

**YAML**: Better for deeply nested/hierarchical configurations and widely used in DevOps (Kubernetes, CI/CD). However:
- Requires external dependency (PyYAML or ruamel.yaml)
- Indentation-sensitive (tabs vs spaces issues)
- Type ambiguity (strings like `yes`/`no` can become booleans unexpectedly)
- Overkill for relatively flat CLI configuration

### Implementation

**Python Libraries**:
- `tomllib` - Standard library (read-only), Python 3.11+
- `tomli-w` - Minimal TOML writer for generating config files

**Example Configuration Structure**:
```toml
[lookervault]
config_version = "1.0"

[lookervault.looker]
api_url = "https://looker.example.com:19999"
client_id = ""  # Set via env var LOOKERVAULT_CLIENT_ID
client_secret = ""  # Set via env var LOOKERVAULT_CLIENT_SECRET
timeout = 30
verify_ssl = true

[lookervault.output]
default_format = "table"  # or "json"
color_enabled = true
```

---

## 2. Typer CLI Best Practices

### Command Organization

**Pattern**: Use modular structure with `app.add_typer()` for multi-command CLIs:

```python
# main.py
import typer
from .commands import info, check

app = typer.Typer()

# Add command modules
app.add_typer(info.app, name="info")
app.add_typer(check.app, name="check")
```

**Directory Structure**:
```
src/lookervault/cli/
├── main.py              # Typer app definition
├── commands/
│   ├── info.py          # Info command group
│   └── check.py         # Check command group
└── output.py            # Shared output formatting
```

### Output Formatting

**Dual Output Modes**: Support both human-readable and JSON output:

```python
@app.command()
def info(
    output: str = typer.Option(
        "table",
        "--output",
        "-o",
        help="Output format: table or json"
    )
):
    data = get_instance_info()

    if output == "json":
        typer.echo(json.dumps(data, indent=2))
    else:
        # Use Rich for beautiful tables
        console = Console()
        table = Table(title="Looker Instance Info")
        # ... populate table
        console.print(table)
```

**Best Practices**:
- Default to human-readable output
- JSON output via `--output json` flag
- Use Rich library for tables and styling
- Separate debug output to stderr (doesn't interfere with piping)

### Configuration Management

**Environment Variables**: Typer has built-in support:

```python
@app.command()
def connect(
    api_url: Annotated[str, typer.Option(
        envvar="LOOKERVAULT_API_URL",
        help="Looker API URL"
    )]
):
    # Value automatically loaded from env var if not provided as CLI arg
    pass
```

**Config Files**: Use `typer.get_app_dir()` for storing configuration:

```python
APP_NAME = "lookervault"

def get_config_path() -> Path:
    app_dir = Path(typer.get_app_dir(APP_NAME))
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir / "config.toml"
```

### Error Handling and Exit Codes

**Exit Codes**:
- `0` - Success (default)
- `1` - General errors
- `2` - Configuration errors
- `3` - Connection errors
- `130` - Terminated by Ctrl+C

**Pattern**:
```python
@app.command()
def check():
    try:
        validate_config()
    except ConfigError as e:
        typer.echo(f"Configuration error: {e}", err=True)
        raise typer.Exit(code=2)
    except ConnectionError as e:
        typer.echo(f"Connection error: {e}", err=True)
        raise typer.Exit(code=3)
```

### Testing

**Use CliRunner**:
```python
from typer.testing import CliRunner

runner = CliRunner()

def test_info_command():
    result = runner.invoke(app, ["info", "--output", "json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "version" in data
```

---

## 3. Looker SDK Integration

### Client Initialization

**Recommended Pattern**: Use environment variables for credentials:

```python
import looker_sdk

# SDK reads from environment variables:
# - LOOKERSDK_BASE_URL
# - LOOKERSDK_CLIENT_ID
# - LOOKERSDK_CLIENT_SECRET
# - LOOKERSDK_VERIFY_SSL
# - LOOKERSDK_TIMEOUT

sdk = looker_sdk.init40()
```

**Alternative**: Custom ApiSettings for dynamic configuration:

```python
from looker_sdk import api_settings

class LookerVaultSettings(api_settings.ApiSettings):
    def read_config(self) -> api_settings.SettingsConfig:
        # Load from our TOML config file
        config = load_lookervault_config()
        return {
            "base_url": config["looker"]["api_url"],
            "client_id": os.getenv("LOOKERVAULT_CLIENT_ID"),
            "client_secret": os.getenv("LOOKERVAULT_CLIENT_SECRET"),
            "verify_ssl": config["looker"]["verify_ssl"],
            "timeout": config["looker"]["timeout"]
        }

sdk = looker_sdk.init40(config_settings=LookerVaultSettings())
```

### Authentication Handling

**SDK Architecture**: The SDK automatically handles token refresh and session management via AuthSession plugin. No manual token management needed.

**Error Handling Pattern**:
```python
from looker_sdk import error as looker_error
import json

try:
    sdk = looker_sdk.init40()
    user = sdk.me()
except looker_error.SDKError as exc:
    # Parse error data for detailed information
    error_data = json.loads(exc.args[0])
    raise ConnectionError(f"Authentication failed: {error_data}")
```

### Instance Info Retrieval

**Connection Test**:
```python
# Get current user (validates authentication)
my_user = sdk.me()

# Returns User model with:
# - id, first_name, last_name, email
# - Can be accessed as dict or model: user["id"] or user.id
```

**Version Information**:
```python
# Get API version and instance metadata
versions = sdk.versions()

# ApiVersion structure:
# - looker_release_version: Looker instance version
# - current_version: Current API version details
# - supported_versions: List of supported API versions
# - api_server_url: API base URL
# - web_server_url: Web UI base URL
```

### Connection Timeout and Retry

**Timeout Configuration**:
```python
# Global timeout (via env var or config)
os.environ["LOOKERSDK_TIMEOUT"] = "30"

# Per-request timeout
user = sdk.me(transport_options={"timeout": 10})
```

**Retry Pattern** (SDK has no built-in retry):
```python
def retry_api_call(func, max_retries=3, delay=2):
    for attempt in range(max_retries):
        try:
            return func()
        except looker_error.SDKError as e:
            if attempt < max_retries - 1:
                time.sleep(delay)
            else:
                raise
```

### Testing/Mocking

**Mock SDK with pytest-mock**:
```python
def test_get_user_info(mocker):
    mock_sdk = MagicMock()
    mock_user = MagicMock()
    mock_user.first_name = "Test"
    mock_sdk.me.return_value = mock_user

    mocker.patch('looker_sdk.init40', return_value=mock_sdk)

    sdk = looker_sdk.init40()
    user = sdk.me()
    assert user.first_name == "Test"
```

### Known Limitations

- **Error messages**: Looker API errors can be cryptic - wrap in custom exceptions
- **No built-in retry**: Must implement retry logic manually
- **base_url format**: Must NOT include `/api/*` (common mistake)
- **SSL verification**: Don't disable `verify_ssl` in production
- **Credential security**: Never hardcode credentials

---

## 4. Python Project Structure

### Modern Python Packaging (PEP 517/518) with uv

**Project Layout**:
```
lookervault/
├── src/lookervault/       # Source code in src/ layout
├── tests/                 # Test directory
├── pyproject.toml         # Project metadata and dependencies
├── uv.lock                # Lockfile managed by uv
├── README.md
└── .env.example           # Example environment variables
```

**Package Manager**: This project uses `uv` (https://github.com/astral-sh/uv) for all Python package management operations. `uv` is an extremely fast Python package and project manager written in Rust that replaces pip, pip-tools, pipx, poetry, and virtualenv.

**Key uv Commands**:
- `uv venv` - Create virtual environment
- `uv add <package>` - Add dependency to project
- `uv add --dev <package>` - Add development dependency
- `uv lock` - Update lockfile (uv.lock)
- `uv sync` - Sync environment with lockfile
- `uv sync --all-extras --dev` - Sync including all optional and dev dependencies
- `uv build` - Build distribution packages

**Dependencies Management**:

Dependencies are added imperatively using `uv add` commands, NOT declared in pyproject.toml:

```bash
# Production dependencies
uv add "typer[all]>=0.9.0"      # CLI framework with Rich
uv add "looker-sdk>=24.0.0"     # Looker API SDK
uv add "pydantic>=2.0.0"        # Configuration validation
uv add "tomli-w>=1.0.0"         # TOML writing

# Development dependencies
uv add --dev "pytest>=7.4.0"
uv add --dev "pytest-mock>=3.12.0"
uv add --dev "pytest-cov>=4.1.0"
uv add --dev "mypy>=1.8.0"
uv add --dev "ruff>=0.1.0"
```

**pyproject.toml** (tool configurations only):
```toml
# Only tool configurations - NO [project], [build-system], or dependency declarations

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = "test_*.py"
python_functions = "test_*"
addopts = "-v --cov=lookervault --cov-report=term-missing"

[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true

[tool.ruff]
line-length = 100
target-version = "py311"
```

**Why uv?**:
- **Speed**: 10-100x faster than pip for installation and dependency resolution
- **Unified Tool**: Replaces pip, pip-tools, virtualenv, poetry in a single tool
- **Lockfile**: Automatic dependency locking (uv.lock) for reproducible builds
- **Rust-based**: Fast, reliable, and memory-efficient
- **Project Management**: Built-in project scaffolding and workspace support

### Testing Structure

**Test Organization**:
```
tests/
├── unit/                  # Fast, isolated tests
│   ├── test_config_loader.py
│   ├── test_output_formatting.py
│   └── test_looker_client.py
├── integration/           # Tests with external dependencies
│   ├── test_cli_commands.py
│   └── test_looker_connection.py
└── fixtures/
    ├── sample_config.toml
    └── mock_responses.py
```

---

## Summary of Resolved Unknowns

| Unknown | Resolution |
|---------|-----------|
| Config file format (TOML vs YAML) | **TOML** - Native Python 3.11+ support, ecosystem alignment |
| Package manager | **uv** - Fast Rust-based Python package manager (replaces pip, poetry, virtualenv) |
| Typer command organization | **Modular with add_typer()** - One file per command group |
| Output formatting approach | **Dual mode**: Rich tables (default) + JSON (--output json) |
| Looker SDK initialization | **Environment variables** with custom ApiSettings wrapper |
| Connection testing strategy | **sdk.me() + sdk.versions()** - Validates auth and retrieves metadata |
| Testing approach | **pytest + pytest-mock** - Unit tests with mocked SDK |

---

## References

- [Python TOML Support (PEP 680)](https://peps.python.org/pep-0680/)
- [Typer Documentation](https://typer.tiangolo.com/)
- [Looker Python SDK](https://pypi.org/project/looker-sdk/)
- [Modern Python Packaging](https://packaging.python.org/en/latest/)
- [Rich Library](https://rich.readthedocs.io/)
