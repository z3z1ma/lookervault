"""Unit tests for output formatting."""

import json
from datetime import datetime

from lookervault.cli.output import format_json, format_readiness_check_json
from lookervault.config.models import CheckItem, ConnectionStatus, ReadinessCheckResult


def test_format_json_with_dict() -> None:
    """Test JSON formatting with dictionary."""
    data = {"key": "value", "number": 42}
    result = format_json(data)

    # Should be valid JSON
    parsed = json.loads(result)
    assert parsed["key"] == "value"
    assert parsed["number"] == 42


def test_format_json_with_pydantic_model() -> None:
    """Test JSON formatting with Pydantic model."""
    status = ConnectionStatus(
        connected=True,
        authenticated=True,
        instance_url="https://looker.example.com:19999",
        looker_version="24.4.12",
        api_version="4.0",
        user_id=1,
        user_email="admin@example.com",
    )

    result = format_json(status)

    # Should be valid JSON
    parsed = json.loads(result)
    assert parsed["connected"] is True
    assert parsed["instance_url"] == "https://looker.example.com:19999"
    assert parsed["user_id"] == 1


def test_format_readiness_check_json() -> None:
    """Test readiness check JSON formatting."""
    result = ReadinessCheckResult(
        ready=True,
        checks=[
            CheckItem(name="Test Check 1", status="pass", message="OK"),
            CheckItem(name="Test Check 2", status="warning", message="Minor issue"),
        ],
        timestamp=datetime(2025, 12, 13, 10, 30, 45),
    )

    output = format_readiness_check_json(result)

    # Should be valid JSON
    parsed = json.loads(output)
    assert parsed["ready"] is True
    assert len(parsed["checks"]) == 2
    assert parsed["checks"][0]["name"] == "Test Check 1"
    assert parsed["checks"][0]["status"] == "pass"
