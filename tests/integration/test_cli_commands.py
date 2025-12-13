"""Integration tests for CLI commands."""

import json

from typer.testing import CliRunner

from lookervault.cli.main import app

runner = CliRunner()


def test_version_command() -> None:
    """Test --version flag."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "LookerVault version" in result.stdout
    assert "0.1.0" in result.stdout


def test_help_command() -> None:
    """Test --help flag."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "LookerVault" in result.stdout
    assert "check" in result.stdout
    assert "info" in result.stdout


def test_check_command_help() -> None:
    """Test check command --help."""
    result = runner.invoke(app, ["check", "--help"])
    assert result.exit_code == 0
    assert "readiness" in result.stdout.lower()


def test_info_command_help() -> None:
    """Test info command --help."""
    result = runner.invoke(app, ["info", "--help"])
    assert result.exit_code == 0
    assert "instance" in result.stdout.lower()


def test_check_command_with_missing_config() -> None:
    """Test check command when config file doesn't exist."""
    result = runner.invoke(app, ["check", "--config", "/nonexistent/config.toml"])

    # Should exit with error code (config not found = exit 2)
    assert result.exit_code in [1, 2]


def test_check_command_json_output(tmp_path) -> None:
    """Test check command with JSON output."""
    # Create a valid config file
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
[lookervault]
config_version = "1.0"

[lookervault.looker]
api_url = "https://looker.example.com:19999"
""")

    result = runner.invoke(app, ["check", "--config", str(config_file), "--output", "json"])

    # Should produce valid JSON output
    try:
        data = json.loads(result.stdout)
        assert "ready" in data
        assert "checks" in data
        assert "timestamp" in data
        assert isinstance(data["checks"], list)
    except json.JSONDecodeError:
        pytest.fail("Output is not valid JSON")
