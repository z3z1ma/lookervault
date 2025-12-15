"""Unit tests for datetime parsing utility."""

from datetime import UTC, datetime

import pytest

from lookervault.utils.datetime_parsing import parse_timestamp


class TestParseTimestamp:
    """Tests for parse_timestamp function."""

    def test_parse_iso_string_with_z(self):
        """Test parsing ISO 8601 string with Z timezone."""
        result = parse_timestamp("2024-01-01T12:00:00Z", "created_at")
        assert result == datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    def test_parse_iso_string_with_offset(self):
        """Test parsing ISO 8601 string with +00:00 timezone."""
        result = parse_timestamp("2024-01-01T12:00:00+00:00", "created_at")
        assert result == datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    def test_parse_datetime_object(self):
        """Test passing through datetime object."""
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = parse_timestamp(dt, "created_at")
        assert result == dt

    def test_parse_unix_timestamp_int(self):
        """Test parsing Unix timestamp (integer)."""
        # 2024-01-01 12:00:00 UTC
        unix_ts = 1704110400
        result = parse_timestamp(unix_ts, "created_at")
        assert result == datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    def test_parse_unix_timestamp_float(self):
        """Test parsing Unix timestamp (float)."""
        # 2024-01-01 12:00:00.5 UTC
        unix_ts = 1704110400.5
        result = parse_timestamp(unix_ts, "created_at")
        expected = datetime.fromtimestamp(unix_ts, tz=UTC)
        assert result == expected

    def test_parse_none_value(self):
        """Test parsing None returns default (current time)."""
        result = parse_timestamp(None, "created_at")
        # Should be current time (within a few seconds)
        assert (datetime.now(UTC) - result).total_seconds() < 5

    def test_parse_empty_string(self):
        """Test parsing empty string returns default."""
        result = parse_timestamp("", "created_at")
        # Should be current time (within a few seconds)
        assert (datetime.now(UTC) - result).total_seconds() < 5

    def test_parse_with_custom_default(self):
        """Test parsing with custom default value."""
        default = datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC)
        result = parse_timestamp(None, "created_at", default=default)
        assert result == default

    def test_parse_invalid_type(self):
        """Test parsing invalid type returns default."""
        result = parse_timestamp({"invalid": "dict"}, "created_at")
        # Should return default (current time)
        assert (datetime.now(UTC) - result).total_seconds() < 5

    def test_parse_invalid_string(self):
        """Test parsing invalid string returns default."""
        result = parse_timestamp("not-a-timestamp", "created_at")
        # Should return default (current time)
        assert (datetime.now(UTC) - result).total_seconds() < 5

    def test_parse_with_item_id_logging(self):
        """Test parsing includes item_id in log messages."""
        # This test verifies the signature works, actual logging verification
        # would require capturing logs
        result = parse_timestamp("invalid", "created_at", item_id="dashboard::123")
        # Should return default (current time)
        assert (datetime.now(UTC) - result).total_seconds() < 5

    def test_parse_iso_string_with_microseconds(self):
        """Test parsing ISO string with microseconds."""
        result = parse_timestamp("2024-01-01T12:00:00.123456Z", "created_at")
        assert result == datetime(2024, 1, 1, 12, 0, 0, 123456, tzinfo=UTC)
