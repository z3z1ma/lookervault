# Quickstart: Base CLI with Looker Connectivity

**Feature**: 001-cli-baseline
**Audience**: Developers implementing this feature
**Date**: 2025-12-13

This guide provides step-by-step instructions for implementing and testing the CLI baseline feature.

---

## Prerequisites

- Python 3.11 or later installed
- Access to a Looker instance with API credentials
- Git repository cloned locally

---

## Implementation Steps

### Phase 1: Project Setup

**1.1 Create Project Structure**

```bash
# Create source directories
mkdir -p src/lookervault/{cli/commands,config,looker}
mkdir -p tests/{unit,integration,fixtures}

# Create __init__.py files
touch src/lookervault/__init__.py
touch src/lookervault/cli/__init__.py
touch src/lookervault/cli/commands/__init__.py
touch src/lookervault/config/__init__.py
touch src/lookervault/looker/__init__.py
```

**1.2 Add Tool Configurations to pyproject.toml**

Add these tool configuration sections to the existing pyproject.toml:

```toml
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

**1.3 Add Dependencies**

```bash
# Create virtual environment with uv
uv venv

# Activate virtual environment
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Add production dependencies
uv add "typer[all]>=0.9.0"
uv add "looker-sdk>=24.0.0"
uv add "pydantic>=2.0.0"
uv add "tomli-w>=1.0.0"

# Add development dependencies
uv add --dev "pytest>=7.4.0"
uv add --dev "pytest-mock>=3.12.0"
uv add --dev "pytest-cov>=4.1.0"
uv add --dev "mypy>=1.8.0"
uv add --dev "ruff>=0.1.0"
```

**Note**: This project uses `uv` for all Python package management operations. Do not use `pip` directly. Dependencies are added imperatively with `uv add`, not declared in pyproject.toml.

---

### Phase 2: Core Implementation

**2.1 Implement Pydantic Models** (`src/lookervault/config/models.py`)

```python
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, Literal
from datetime import datetime

class LookerConfig(BaseModel):
    api_url: HttpUrl
    client_id: Optional[str] = ""
    client_secret: Optional[str] = ""
    timeout: int = Field(default=30, ge=5, le=300)
    verify_ssl: bool = True

class OutputConfig(BaseModel):
    default_format: Literal["table", "json"] = "table"
    color_enabled: bool = True

class Configuration(BaseModel):
    config_version: str
    looker: LookerConfig
    output: OutputConfig = OutputConfig()
```

**2.2 Implement Config Loader** (`src/lookervault/config/loader.py`)

```python
import tomllib
import os
from pathlib import Path
from typing import Optional
import typer
from .models import Configuration

def get_config_path(config_arg: Optional[Path] = None) -> Path:
    """Get configuration file path with priority order."""
    # 1. Command-line argument
    if config_arg:
        return config_arg

    # 2. Environment variable
    env_config = os.getenv("LOOKERVAULT_CONFIG")
    if env_config:
        return Path(env_config)

    # 3. User home directory
    app_dir = Path(typer.get_app_dir("lookervault"))
    user_config = app_dir / "config.toml"
    if user_config.exists():
        return user_config

    # 4. Current directory
    cwd_config = Path("lookervault.toml")
    if cwd_config.exists():
        return cwd_config

    # Default (may not exist)
    return user_config

def load_config(config_path: Optional[Path] = None) -> Configuration:
    """Load and validate configuration."""
    path = get_config_path(config_path)

    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    with open(path, "rb") as f:
        data = tomllib.load(f)

    # Merge environment variables
    if "lookervault" in data and "looker" in data["lookervault"]:
        looker_config = data["lookervault"]["looker"]

        # Override with env vars if present
        if client_id := os.getenv("LOOKERVAULT_CLIENT_ID"):
            looker_config["client_id"] = client_id
        if client_secret := os.getenv("LOOKERVAULT_CLIENT_SECRET"):
            looker_config["client_secret"] = client_secret
        if api_url := os.getenv("LOOKERVAULT_API_URL"):
            looker_config["api_url"] = api_url

    return Configuration(**data["lookervault"])
```

**2.3 Implement Looker Client Wrapper** (`src/lookervault/looker/client.py`)

```python
import looker_sdk
from looker_sdk import api_settings, error as looker_error
from typing import Optional
import os

class LookerClient:
    """Wrapper for Looker SDK with custom configuration."""

    def __init__(self, api_url: str, client_id: str, client_secret: str,
                 timeout: int = 30, verify_ssl: bool = True):
        self.api_url = api_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self._sdk: Optional[looker_sdk.methods40.Looker40SDK] = None

    def _init_sdk(self):
        """Initialize Looker SDK with custom settings."""
        os.environ["LOOKERSDK_BASE_URL"] = self.api_url
        os.environ["LOOKERSDK_CLIENT_ID"] = self.client_id
        os.environ["LOOKERSDK_CLIENT_SECRET"] = self.client_secret
        os.environ["LOOKERSDK_VERIFY_SSL"] = str(self.verify_ssl).lower()
        os.environ["LOOKERSDK_TIMEOUT"] = str(self.timeout)

        self._sdk = looker_sdk.init40()

    @property
    def sdk(self):
        """Lazy-load SDK on first access."""
        if self._sdk is None:
            self._init_sdk()
        return self._sdk

    def test_connection(self) -> dict:
        """Test connection and return instance info."""
        try:
            user = self.sdk.me()
            versions = self.sdk.versions()

            return {
                "connected": True,
                "authenticated": True,
                "instance_url": self.api_url,
                "looker_version": versions.looker_release_version,
                "api_version": versions.current_version.version,
                "user_id": user.id,
                "user_email": user.email,
                "supported_api_versions": [v.version for v in versions.supported_versions]
            }
        except looker_error.SDKError as e:
            return {
                "connected": False,
                "authenticated": False,
                "error_message": str(e)
            }
```

**2.4 Implement CLI Commands** (`src/lookervault/cli/main.py`)

```python
import typer
from typing_extensions import Annotated
from pathlib import Path

app = typer.Typer(help="LookerVault - Backup and restore tool for Looker instances")

@app.command()
def check(
    config: Annotated[Path, typer.Option("--config", "-c")] = None,
    output: Annotated[str, typer.Option("--output", "-o")] = "table"
):
    """Perform readiness checks."""
    # Implementation in separate commands/check.py module
    from .commands import check as check_module
    check_module.run(config, output)

@app.command()
def info(
    config: Annotated[Path, typer.Option("--config", "-c")] = None,
    output: Annotated[str, typer.Option("--output", "-o")] = "table"
):
    """Display Looker instance information."""
    # Implementation in separate commands/info.py module
    from .commands import info as info_module
    info_module.run(config, output)

def version_callback(value: bool):
    if value:
        typer.echo("LookerVault version 0.1.0")
        raise typer.Exit()

@app.callback()
def main(
    version: Annotated[bool, typer.Option("--version", callback=version_callback)] = False
):
    """Main callback."""
    pass

if __name__ == "__main__":
    app()
```

---

### Phase 3: Testing

**3.1 Unit Test: Config Loader** (`tests/unit/test_config_loader.py`)

```python
import pytest
from pathlib import Path
from lookervault.config.loader import load_config, get_config_path
from lookervault.config.models import Configuration

def test_load_valid_config(tmp_path):
    """Test loading valid TOML configuration."""
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[lookervault]
config_version = "1.0"

[lookervault.looker]
api_url = "https://looker.example.com:19999"
timeout = 30
verify_ssl = true
""")

    config = load_config(config_file)

    assert isinstance(config, Configuration)
    assert config.config_version == "1.0"
    assert str(config.looker.api_url) == "https://looker.example.com:19999/"
    assert config.looker.timeout == 30

def test_load_config_file_not_found():
    """Test error when config file doesn't exist."""
    with pytest.raises(FileNotFoundError):
        load_config(Path("/nonexistent/config.toml"))
```

**3.2 Integration Test: CLI Commands** (`tests/integration/test_cli_commands.py`)

```python
from typer.testing import CliRunner
from lookervault.cli.main import app
import json

runner = CliRunner()

def test_version_command():
    """Test --version flag."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "LookerVault version" in result.stdout

def test_check_command_json_output():
    """Test check command with JSON output."""
    result = runner.invoke(app, ["check", "--output", "json"])

    # May fail if no config exists, but should return valid JSON
    if result.exit_code == 0:
        data = json.loads(result.stdout)
        assert "ready" in data
        assert "checks" in data
```

---

### Phase 4: Manual Testing

**4.1 Create Test Configuration**

```bash
mkdir -p ~/.lookervault
cat > ~/.lookervault/config.toml << 'EOF'
[lookervault]
config_version = "1.0"

[lookervault.looker]
api_url = "https://your-looker.com:19999"
timeout = 30
verify_ssl = true

[lookervault.output]
default_format = "table"
color_enabled = true
EOF
```

**4.2 Set Environment Variables**

```bash
export LOOKERVAULT_CLIENT_ID="your_client_id"
export LOOKERVAULT_CLIENT_SECRET="your_client_secret"
```

**4.3 Test Commands**

```bash
# Test version
lookervault --version

# Test help
lookervault --help

# Test readiness check
lookervault check

# Test readiness check with JSON
lookervault check --output json

# Test Looker connection
lookervault info

# Test Looker connection with JSON
lookervault info --output json
```

---

## Validation Checklist

- [ ] Project structure matches specification
- [ ] All dependencies installed correctly
- [ ] Pydantic models validate correctly
- [ ] Config loader handles all priority sources (CLI arg, env var, file)
- [ ] Looker client connects successfully
- [ ] CLI commands execute without errors
- [ ] Unit tests pass (`pytest tests/unit/`)
- [ ] Integration tests pass (`pytest tests/integration/`)
- [ ] JSON output is valid and parseable
- [ ] Table output is human-readable
- [ ] Exit codes match specification
- [ ] Error messages are clear and actionable
- [ ] Help text is accurate and complete

---

## Troubleshooting

### Issue: "Configuration file not found"
**Solution**: Create config file at `~/.lookervault/config.toml` or use `--config` flag

### Issue: "Authentication failed"
**Solution**: Verify `LOOKERVAULT_CLIENT_ID` and `LOOKERVAULT_CLIENT_SECRET` are set correctly

### Issue: "Connection timeout"
**Solution**:
- Check network connectivity to Looker instance
- Verify `api_url` is correct (no `/api/*` path)
- Increase timeout in config: `timeout = 60`

### Issue: "Module not found"
**Solution**: Ensure package is installed in development mode: `pip install -e .`

---

## Next Steps

After completing the baseline implementation:

1. Run full test suite: `pytest tests/ -v --cov`
2. Check type hints: `mypy src/lookervault`
3. Lint code: `ruff check src/`
4. Create example configurations in `docs/examples/`
5. Update README.md with installation and usage instructions
6. Proceed to `/speckit.tasks` to generate task breakdown
7. Begin implementation following task order

---

## Reference Commands

```bash
# Development workflow (using uv)
uv venv                              # Create virtual environment
uv sync --all-extras --dev           # Sync all dependencies including dev
uv add <package>                     # Add new dependency
uv add --dev <package>               # Add new dev dependency
uv lock                              # Update lockfile
pytest tests/ -v --cov               # Run tests with coverage
mypy src/lookervault                 # Type checking
ruff check src/                      # Linting
ruff format src/                     # Formatting

# Build and distribution
uv build                             # Build distribution packages
uv pip install dist/lookervault-0.1.0-py3-none-any.whl  # Install built package

# Usage
lookervault --help                   # Show help
lookervault --version                # Show version
lookervault check                    # Readiness check
lookervault info                     # Instance info
lookervault info --output json | jq  # Pipe to jq for processing
```
