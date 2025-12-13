"""Unit tests for configuration loader."""

from pathlib import Path

import pytest

from lookervault.config.loader import get_config_path, load_config
from lookervault.config.models import Configuration
from lookervault.exceptions import ConfigError


def test_load_valid_config(tmp_path: Path) -> None:
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
    assert config.looker.verify_ssl is True


def test_load_config_with_env_vars(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that environment variables override config file."""
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[lookervault]
config_version = "1.0"

[lookervault.looker]
api_url = "https://looker.example.com:19999"
client_id = "file_id"
client_secret = "file_secret"
""")

    # Set environment variables
    monkeypatch.setenv("LOOKERVAULT_CLIENT_ID", "env_id")
    monkeypatch.setenv("LOOKERVAULT_CLIENT_SECRET", "env_secret")

    config = load_config(config_file)

    # Env vars should override file values
    assert config.looker.client_id == "env_id"
    assert config.looker.client_secret == "env_secret"


def test_load_config_file_not_found() -> None:
    """Test error when config file doesn't exist."""
    with pytest.raises(ConfigError, match="No config file found"):
        load_config(Path("/nonexistent/config.toml"))


def test_load_config_invalid_toml(tmp_path: Path) -> None:
    """Test error with invalid TOML syntax."""
    config_file = tmp_path / "config.toml"
    config_file.write_text("this is not valid TOML {]")

    with pytest.raises(ConfigError, match="Invalid TOML syntax"):
        load_config(config_file)


def test_load_config_missing_section(tmp_path: Path) -> None:
    """Test error when lookervault section is missing."""
    config_file = tmp_path / "config.toml"
    config_file.write_text("[other]\nkey = 'value'")

    with pytest.raises(ConfigError, match="Missing 'lookervault' section"):
        load_config(config_file)


def test_get_config_path_priority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test config path resolution priority."""
    # Create test files
    explicit_path = tmp_path / "explicit.toml"
    explicit_path.touch()

    env_path = tmp_path / "env.toml"
    env_path.touch()

    # Test 1: Explicit argument has highest priority
    result = get_config_path(explicit_path)
    assert result == explicit_path

    # Test 2: Environment variable is second priority
    monkeypatch.setenv("LOOKERVAULT_CONFIG", str(env_path))
    result = get_config_path()
    assert result == env_path
