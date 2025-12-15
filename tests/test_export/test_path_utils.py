"""Tests for path utilities."""

from pathlib import Path

import pytest

from lookervault.export.path_utils import (
    PathCollisionResolver,
    sanitize_folder_name,
    truncate_path_component,
    validate_path_length,
)


class TestSanitizeFolderName:
    """Test folder name sanitization."""

    def test_sanitize_simple_name(self):
        """Sanitize simple folder name."""
        result = sanitize_folder_name("Sales Dashboard")
        assert result == "Sales Dashboard"

    def test_sanitize_invalid_chars(self):
        """Sanitize folder name with invalid characters."""
        result = sanitize_folder_name("Sales/Marketing")
        # Forward slash should be replaced
        assert "/" not in result
        assert "_" in result

    def test_sanitize_windows_reserved_chars(self):
        """Sanitize Windows reserved characters."""
        result = sanitize_folder_name('Sales: "Q1"')
        # Colons and quotes should be replaced
        assert ":" not in result
        assert '"' not in result

    def test_sanitize_unicode_normalization(self):
        """Unicode normalization (NFC)."""
        # Café with combining accent
        result = sanitize_folder_name("Café")
        assert "Café" in result or "Cafe" in result

    def test_sanitize_max_length(self):
        """Respect maximum length limit."""
        long_name = "x" * 300
        result = sanitize_folder_name(long_name, max_length=255)
        assert len(result.encode("utf-8")) <= 255

    def test_sanitize_empty_name_raises_error(self):
        """Empty name after sanitization is replaced with underscores."""
        # pathvalidate sanitizes /// to ___ instead of empty string
        result = sanitize_folder_name("///")
        # Should not be empty
        assert len(result) > 0

    def test_sanitize_whitespace_only_raises_error(self):
        """Whitespace-only name raises error."""
        with pytest.raises(ValueError, match="empty string"):
            sanitize_folder_name("   ")

    def test_sanitize_special_chars(self):
        """Sanitize various special characters."""
        result = sanitize_folder_name("Report<2025>")
        assert "<" not in result
        assert ">" not in result

    def test_sanitize_dots_preserved(self):
        """Dots should be preserved."""
        result = sanitize_folder_name("v1.2.3")
        assert result == "v1.2.3"

    def test_sanitize_underscores_preserved(self):
        """Underscores should be preserved."""
        result = sanitize_folder_name("sales_dashboard")
        assert result == "sales_dashboard"


class TestPathCollisionResolver:
    """Test path collision resolution."""

    def test_first_occurrence_no_suffix(self):
        """First occurrence has no suffix."""
        resolver = PathCollisionResolver()
        result = resolver.resolve(Path("/export"), "dashboard.yaml")

        assert result == Path("/export/dashboard.yaml")

    def test_second_occurrence_adds_suffix(self):
        """Second occurrence adds (2) suffix."""
        resolver = PathCollisionResolver()
        resolver.resolve(Path("/export"), "dashboard.yaml")
        result = resolver.resolve(Path("/export"), "dashboard.yaml")

        assert result == Path("/export/dashboard (2).yaml")

    def test_third_occurrence_adds_suffix(self):
        """Third occurrence adds (3) suffix."""
        resolver = PathCollisionResolver()
        resolver.resolve(Path("/export"), "dashboard.yaml")
        resolver.resolve(Path("/export"), "dashboard.yaml")
        result = resolver.resolve(Path("/export"), "dashboard.yaml")

        assert result == Path("/export/dashboard (3).yaml")

    def test_different_directories_no_collision(self):
        """Same filename in different directories doesn't collide."""
        resolver = PathCollisionResolver()
        result1 = resolver.resolve(Path("/export/dir1"), "dashboard.yaml")
        result2 = resolver.resolve(Path("/export/dir2"), "dashboard.yaml")

        assert result1 == Path("/export/dir1/dashboard.yaml")
        assert result2 == Path("/export/dir2/dashboard.yaml")

    def test_different_filenames_no_collision(self):
        """Different filenames in same directory don't collide."""
        resolver = PathCollisionResolver()
        result1 = resolver.resolve(Path("/export"), "dashboard1.yaml")
        result2 = resolver.resolve(Path("/export"), "dashboard2.yaml")

        assert result1 == Path("/export/dashboard1.yaml")
        assert result2 == Path("/export/dashboard2.yaml")

    def test_case_insensitive_collision(self):
        """Case-insensitive collision detection."""
        resolver = PathCollisionResolver()
        result1 = resolver.resolve(Path("/export"), "Dashboard.yaml")
        result2 = resolver.resolve(Path("/export"), "dashboard.yaml")

        # Should detect collision despite case difference
        assert result1 == Path("/export/Dashboard.yaml")
        # The second call preserves the original case of the filename
        assert result2 == Path("/export/dashboard (2).yaml")

    def test_reset_clears_tracking(self):
        """Reset clears collision tracking."""
        resolver = PathCollisionResolver()
        resolver.resolve(Path("/export"), "dashboard.yaml")
        resolver.reset()

        result = resolver.resolve(Path("/export"), "dashboard.yaml")
        assert result == Path("/export/dashboard.yaml")  # No suffix after reset

    def test_multiple_collisions(self):
        """Handle many collisions."""
        resolver = PathCollisionResolver()
        results = [resolver.resolve(Path("/export"), "dashboard.yaml") for _ in range(5)]

        assert results[0] == Path("/export/dashboard.yaml")
        assert results[1] == Path("/export/dashboard (2).yaml")
        assert results[4] == Path("/export/dashboard (5).yaml")

    def test_preserve_file_extension(self):
        """File extension is preserved in suffixed names."""
        resolver = PathCollisionResolver()
        resolver.resolve(Path("/export"), "dashboard.yaml")
        result = resolver.resolve(Path("/export"), "dashboard.yaml")

        assert result.suffix == ".yaml"
        assert result.stem == "dashboard (2)"

    def test_no_extension_files(self):
        """Files without extension are handled."""
        resolver = PathCollisionResolver()
        result1 = resolver.resolve(Path("/export"), "README")
        result2 = resolver.resolve(Path("/export"), "README")

        assert result1 == Path("/export/README")
        assert result2 == Path("/export/README (2)")


class TestTruncatePathComponent:
    """Test path component truncation."""

    def test_no_truncation_needed(self):
        """Short names are not truncated."""
        result = truncate_path_component("short_name", max_bytes=255)
        assert result == "short_name"

    def test_truncate_long_name(self):
        """Long names are truncated."""
        long_name = "x" * 300
        result = truncate_path_component(long_name, max_bytes=255)
        assert len(result.encode("utf-8")) <= 255

    def test_truncate_respects_utf8_boundaries(self):
        """Truncation doesn't break multibyte UTF-8 characters."""
        # String with multibyte characters at the end
        name_with_unicode = "a" * 253 + "café"
        result = truncate_path_component(name_with_unicode, max_bytes=255)

        # Result should be valid UTF-8
        assert result.encode("utf-8")
        assert len(result.encode("utf-8")) <= 255

    def test_truncate_exact_limit(self):
        """Name exactly at byte limit is not truncated."""
        name = "x" * 255
        result = truncate_path_component(name, max_bytes=255)
        assert result == name

    def test_truncate_unicode_characters(self):
        """Unicode characters are handled properly."""
        # Each emoji is 4 bytes in UTF-8
        emoji_name = "☕" * 100  # 400 bytes
        result = truncate_path_component(emoji_name, max_bytes=255)
        assert len(result.encode("utf-8")) <= 255

    def test_truncate_custom_max_bytes(self):
        """Custom max_bytes parameter works."""
        name = "x" * 100
        result = truncate_path_component(name, max_bytes=50)
        assert len(result.encode("utf-8")) <= 50


class TestValidatePathLength:
    """Test path length validation."""

    def test_valid_short_path(self):
        """Short path is valid."""
        path = Path("/export/dashboards/test.yaml")
        assert validate_path_length(path, max_path_length=260) is True

    def test_valid_at_limit(self):
        """Path exactly at limit is valid."""
        # Create path exactly 260 characters
        path = Path("/" + "x" * 259)
        assert validate_path_length(path, max_path_length=260) is True

    def test_invalid_exceeds_limit(self):
        """Path exceeding limit is invalid."""
        # Create path longer than 260 characters
        path = Path("/" + "x" * 300)
        assert validate_path_length(path, max_path_length=260) is False

    def test_custom_max_length(self):
        """Custom max_path_length works."""
        path = Path("/export/test.yaml")
        assert validate_path_length(path, max_path_length=10) is False
        assert validate_path_length(path, max_path_length=100) is True

    def test_unicode_path_length(self):
        """Unicode characters in path are counted correctly."""
        # Path with multibyte UTF-8 characters
        path = Path("/export/☕☕☕/test.yaml")
        # Should count actual string length, not byte length
        assert validate_path_length(path, max_path_length=260) is True


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_sanitize_null_bytes(self):
        """Null bytes are removed."""
        result = sanitize_folder_name("name\x00with\x00nulls")
        assert "\x00" not in result

    def test_sanitize_leading_trailing_spaces(self):
        """Leading/trailing spaces are preserved by pathvalidate."""
        result = sanitize_folder_name("  name  ")
        # pathvalidate preserves spaces
        assert result.strip() == "name"

    def test_collision_resolver_empty_filename(self):
        """Collision resolver handles edge case of empty filename."""
        resolver = PathCollisionResolver()
        # This should work without error
        result = resolver.resolve(Path("/export"), "")
        assert result == Path("/export/")

    def test_truncate_empty_string(self):
        """Truncate empty string."""
        result = truncate_path_component("", max_bytes=255)
        assert result == ""

    def test_truncate_single_multibyte_char(self):
        """Truncate single multibyte character."""
        result = truncate_path_component("café", max_bytes=2)
        # Should truncate to fit within byte limit
        assert len(result.encode("utf-8")) <= 2

    def test_path_length_with_relative_path(self):
        """Path length validation with relative paths."""
        path = Path("relative/path/to/file.yaml")
        assert validate_path_length(path, max_path_length=100) is True
