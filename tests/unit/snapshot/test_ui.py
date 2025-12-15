"""Unit tests for snapshot UI module - Fixed version."""

import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from lookervault.snapshot.models import SnapshotMetadata
from lookervault.snapshot.ui import (
    _format_age,
    detect_interactive_mode,
    interactive_snapshot_picker,
)


class TestDetectInteractiveMode:
    """Test interactive mode detection."""

    def test_detect_interactive_mode_both_tty(self):
        """Test detection when both stdin and stdout are TTYs."""
        with patch.object(sys.stdin, "isatty", return_value=True):
            with patch.object(sys.stdout, "isatty", return_value=True):
                assert detect_interactive_mode() is True

    def test_detect_interactive_mode_stdin_not_tty(self):
        """Test detection when stdin is not a TTY (piped input)."""
        with patch.object(sys.stdin, "isatty", return_value=False):
            with patch.object(sys.stdout, "isatty", return_value=True):
                assert detect_interactive_mode() is False

    def test_detect_interactive_mode_stdout_not_tty(self):
        """Test detection when stdout is not a TTY (redirected output)."""
        with patch.object(sys.stdin, "isatty", return_value=True):
            with patch.object(sys.stdout, "isatty", return_value=False):
                assert detect_interactive_mode() is False

    def test_detect_interactive_mode_neither_tty(self):
        """Test detection when neither stdin nor stdout are TTYs (CI/CD)."""
        with patch.object(sys.stdin, "isatty", return_value=False):
            with patch.object(sys.stdout, "isatty", return_value=False):
                assert detect_interactive_mode() is False


class TestInteractiveSnapshotPicker:
    """Test interactive snapshot picker."""

    @pytest.fixture
    def mock_snapshots(self):
        """Create mock snapshots for testing."""
        return [
            SnapshotMetadata(
                sequential_index=1,
                filename="snapshots/looker-2025-12-14T10-30-00.db.gz",
                timestamp=datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
                size_bytes=1024 * 1024,
                gcs_bucket="test-bucket",
                gcs_path="gs://test-bucket/snapshots/looker-2025-12-14T10-30-00.db.gz",
                crc32c="AAAAAA==",
                content_encoding="gzip",
                tags=[],
                created=datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
                updated=datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
            ),
            SnapshotMetadata(
                sequential_index=2,
                filename="snapshots/looker-2025-12-13T08-15-00.db.gz",
                timestamp=datetime(2025, 12, 13, 8, 15, 0, tzinfo=UTC),
                size_bytes=2048 * 1024,
                gcs_bucket="test-bucket",
                gcs_path="gs://test-bucket/snapshots/looker-2025-12-13T08-15-00.db.gz",
                crc32c="BBBBBB==",
                content_encoding="gzip",
                tags=[],
                created=datetime(2025, 12, 13, 8, 15, 0, tzinfo=UTC),
                updated=datetime(2025, 12, 13, 8, 15, 0, tzinfo=UTC),
            ),
        ]

    def test_interactive_picker_empty_snapshots(self):
        """Test picker fails with empty snapshots list."""
        with pytest.raises(ValueError) as exc_info:
            interactive_snapshot_picker([])

        assert "No snapshots available" in str(exc_info.value)

    def test_interactive_picker_non_interactive_terminal(self, mock_snapshots):
        """Test picker fails in non-interactive terminal."""
        with patch("lookervault.snapshot.ui.detect_interactive_mode", return_value=False):
            with pytest.raises(RuntimeError) as exc_info:
                interactive_snapshot_picker(mock_snapshots)

            error_msg = str(exc_info.value)
            assert "Interactive mode not supported" in error_msg
            assert "Use snapshot index" in error_msg

    @patch("lookervault.snapshot.ui.detect_interactive_mode", return_value=True)
    @patch("lookervault.snapshot.ui.Menu")
    @patch("lookervault.snapshot.ui.console")
    def test_interactive_picker_success(
        self, mock_console, mock_menu_class, mock_detect, mock_snapshots
    ):
        """Test successful snapshot selection."""
        # Mock menu to return first option
        mock_menu = MagicMock()
        mock_menu.ask.return_value = "1. looker-2025-12-14T10-30-00.db.gz (1.0 MB, 1 day ago)"
        mock_menu_class.return_value = mock_menu

        selected = interactive_snapshot_picker(mock_snapshots)

        # Verify correct snapshot was returned
        assert selected is not None
        assert selected.sequential_index == 1
        assert selected.filename == mock_snapshots[0].filename

    @patch("lookervault.snapshot.ui.detect_interactive_mode", return_value=True)
    @patch("lookervault.snapshot.ui.Menu")
    @patch("lookervault.snapshot.ui.console")
    def test_interactive_picker_cancellation(
        self, mock_console, mock_menu_class, mock_detect, mock_snapshots
    ):
        """Test snapshot selection cancellation."""
        # Mock menu to raise KeyboardInterrupt (ESC pressed)
        mock_menu = MagicMock()
        mock_menu.ask.side_effect = KeyboardInterrupt()
        mock_menu_class.return_value = mock_menu

        selected = interactive_snapshot_picker(mock_snapshots, allow_cancel=True)

        # Should return None on cancellation
        assert selected is None

    @patch("lookervault.snapshot.ui.detect_interactive_mode", return_value=True)
    @patch("lookervault.snapshot.ui.Menu")
    @patch("lookervault.snapshot.ui.console")
    def test_interactive_picker_displays_preview(
        self, mock_console, mock_menu_class, mock_detect, mock_snapshots
    ):
        """Test that preview panel is displayed."""
        mock_menu = MagicMock()
        mock_menu.ask.return_value = "1. looker-2025-12-14T10-30-00.db.gz (1.0 MB, 1 day ago)"
        mock_menu_class.return_value = mock_menu

        interactive_snapshot_picker(mock_snapshots)

        # Verify console.print was called (for preview and help text)
        assert mock_console.print.call_count >= 2

    @patch("lookervault.snapshot.ui.detect_interactive_mode", return_value=True)
    @patch("lookervault.snapshot.ui.Menu")
    @patch("lookervault.snapshot.ui.console")
    def test_interactive_picker_custom_title(
        self, mock_console, mock_menu_class, mock_detect, mock_snapshots
    ):
        """Test picker with custom title."""
        mock_menu = MagicMock()
        mock_menu.ask.return_value = "1. looker-2025-12-14T10-30-00.db.gz (1.0 MB, 1 day ago)"
        mock_menu_class.return_value = mock_menu

        interactive_snapshot_picker(mock_snapshots, title="Custom Title")

        # Verify Menu was created with custom title
        menu_call_kwargs = mock_menu_class.call_args[1]
        assert menu_call_kwargs["title"] == "Custom Title"

    @patch("lookervault.snapshot.ui.detect_interactive_mode", return_value=True)
    @patch("lookervault.snapshot.ui.Menu")
    @patch("lookervault.snapshot.ui.console")
    def test_interactive_picker_menu_options_format(
        self, mock_console, mock_menu_class, mock_detect, mock_snapshots
    ):
        """Test menu options are correctly formatted."""
        mock_menu = MagicMock()
        mock_menu.ask.return_value = "1. looker-2025-12-14T10-30-00.db.gz (1.0 MB, < 1 day)"
        mock_menu_class.return_value = mock_menu

        interactive_snapshot_picker(mock_snapshots)

        # Verify Menu was created with correct options
        menu_call_args = mock_menu_class.call_args[0]

        # Should have 2 options (one per snapshot)
        assert len(menu_call_args) == 2

        # Options should contain index, filename, and size
        for option in menu_call_args:
            assert "." in option  # Index separator
            assert "MB" in option  # Size
            # Age can be "< 1 day" or "X days ago"


class TestFormatAge:
    """Test age formatting helper."""

    def test_format_age_less_than_one_day(self):
        """Test formatting age less than 1 day."""
        result = _format_age(0)
        assert result == "< 1 day"

    def test_format_age_one_day(self):
        """Test formatting age of 1 day."""
        result = _format_age(1)
        assert result == "1 day ago"

    def test_format_age_multiple_days(self):
        """Test formatting age in days."""
        result = _format_age(7)
        assert result == "7 days ago"

    def test_format_age_one_month(self):
        """Test formatting age in months."""
        result = _format_age(30)
        assert result == "1 month ago"

    def test_format_age_multiple_months(self):
        """Test formatting age in months."""
        result = _format_age(60)
        assert result == "2 months ago"

    def test_format_age_one_year(self):
        """Test formatting age in years."""
        result = _format_age(365)
        assert result == "1 year ago"

    def test_format_age_multiple_years(self):
        """Test formatting age in years."""
        result = _format_age(730)
        assert result == "2 years ago"
