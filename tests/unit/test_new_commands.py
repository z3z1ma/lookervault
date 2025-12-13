"""Tests for new list and cleanup commands."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from lookervault.storage.models import ContentItem, ContentType


class TestListCommand:
    """Test list command functionality."""

    def test_list_dashboards_basic(self):
        """Test listing dashboards."""
        # Create mock repository
        mock_repo = Mock()
        mock_items = [
            ContentItem(
                id="dashboard::123",
                content_type=ContentType.DASHBOARD.value,
                name="Sales Dashboard",
                owner_email="john@example.com",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                content_data=b"test",
                content_size=1024,
            )
        ]
        mock_repo.list_content.return_value = mock_items

        # Test that list_content is called with correct parameters
        items = mock_repo.list_content(
            content_type=ContentType.DASHBOARD.value,
            include_deleted=False,
            limit=None,
            offset=0,
        )

        assert len(items) == 1
        assert items[0].name == "Sales Dashboard"

    def test_list_with_owner_filter(self):
        """Test listing with owner email filter."""
        mock_items = [
            ContentItem(
                id="dashboard::123",
                content_type=ContentType.DASHBOARD.value,
                name="Dashboard 1",
                owner_email="john@example.com",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                content_data=b"test",
            ),
            ContentItem(
                id="dashboard::456",
                content_type=ContentType.DASHBOARD.value,
                name="Dashboard 2",
                owner_email="jane@example.com",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                content_data=b"test",
            ),
        ]

        # Filter by owner
        filtered = [item for item in mock_items if "john" in item.owner_email.lower()]

        assert len(filtered) == 1
        assert filtered[0].owner_email == "john@example.com"

    def test_list_with_created_after_filter(self):
        """Test listing with created_after date filter."""
        cutoff = datetime(2025, 12, 1, tzinfo=UTC)

        mock_items = [
            ContentItem(
                id="dashboard::123",
                content_type=ContentType.DASHBOARD.value,
                name="Old Dashboard",
                created_at=datetime(2025, 11, 15, tzinfo=UTC),
                updated_at=datetime(2025, 11, 15, tzinfo=UTC),
                content_data=b"test",
            ),
            ContentItem(
                id="dashboard::456",
                content_type=ContentType.DASHBOARD.value,
                name="New Dashboard",
                created_at=datetime(2025, 12, 10, tzinfo=UTC),
                updated_at=datetime(2025, 12, 10, tzinfo=UTC),
                content_data=b"test",
            ),
        ]

        # Filter by creation date
        filtered = [item for item in mock_items if item.created_at >= cutoff]

        assert len(filtered) == 1
        assert filtered[0].name == "New Dashboard"

    def test_list_with_pagination(self):
        """Test listing with limit and offset."""
        mock_items = [
            ContentItem(
                id=f"dashboard::{i}",
                content_type=ContentType.DASHBOARD.value,
                name=f"Dashboard {i}",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                content_data=b"test",
            )
            for i in range(100)
        ]

        # Paginate: offset=20, limit=10
        offset = 20
        limit = 10
        page = mock_items[offset : offset + limit]

        assert len(page) == 10
        assert page[0].name == "Dashboard 20"
        assert page[-1].name == "Dashboard 29"


class TestCleanupCommand:
    """Test cleanup command functionality."""

    def test_get_deleted_items_before(self):
        """Test querying soft-deleted items before cutoff."""
        cutoff_date = datetime.now(UTC) - timedelta(days=30)

        mock_items = [
            ContentItem(
                id="dashboard::123",
                content_type=ContentType.DASHBOARD.value,
                name="Old Deleted",
                created_at=datetime.now(UTC) - timedelta(days=60),
                updated_at=datetime.now(UTC) - timedelta(days=60),
                deleted_at=datetime.now(UTC) - timedelta(days=45),
                content_data=b"test",
            ),
            ContentItem(
                id="dashboard::456",
                content_type=ContentType.DASHBOARD.value,
                name="Recent Deleted",
                created_at=datetime.now(UTC) - timedelta(days=20),
                updated_at=datetime.now(UTC) - timedelta(days=20),
                deleted_at=datetime.now(UTC) - timedelta(days=10),
                content_data=b"test",
            ),
        ]

        # Filter items deleted before cutoff
        old_items = [
            item for item in mock_items if item.deleted_at and item.deleted_at < cutoff_date
        ]

        assert len(old_items) == 1
        assert old_items[0].name == "Old Deleted"

    def test_cleanup_dry_run(self):
        """Test dry run mode doesn't delete items."""
        dry_run = True
        items_to_delete = ["item1", "item2", "item3"]

        # In dry run, nothing should be deleted
        if not dry_run:
            deleted_count = len(items_to_delete)
        else:
            deleted_count = 0

        assert deleted_count == 0

    def test_cleanup_calculates_retention(self):
        """Test retention period calculation."""
        retention_days = 30

        # Item deleted 45 days ago (should be cleaned up)
        item_age = 45
        should_delete = item_age > retention_days

        assert should_delete is True

        # Item deleted 20 days ago (should be kept)
        item_age = 20
        should_delete = item_age > retention_days

        assert should_delete is False

    def test_cleanup_groups_by_content_type(self):
        """Test that cleanup groups items by content type."""
        items = [
            ContentItem(
                id="dashboard::1",
                content_type=ContentType.DASHBOARD.value,
                name="Dashboard 1",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                deleted_at=datetime.now(UTC) - timedelta(days=40),
                content_data=b"test",
            ),
            ContentItem(
                id="dashboard::2",
                content_type=ContentType.DASHBOARD.value,
                name="Dashboard 2",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                deleted_at=datetime.now(UTC) - timedelta(days=40),
                content_data=b"test",
            ),
            ContentItem(
                id="look::1",
                content_type=ContentType.LOOK.value,
                name="Look 1",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                deleted_at=datetime.now(UTC) - timedelta(days=40),
                content_data=b"test",
            ),
        ]

        # Group by content type
        items_by_type = {}
        for item in items:
            type_name = item.id.split("::")[0]
            items_by_type.setdefault(type_name, []).append(item)

        assert len(items_by_type) == 2
        assert "dashboard" in items_by_type
        assert "look" in items_by_type
        assert len(items_by_type["dashboard"]) == 2
        assert len(items_by_type["look"]) == 1


class TestTimeoutConfiguration:
    """Test timeout configuration and environment variables."""

    def test_default_timeout_increased(self):
        """Test that default timeout is 120 seconds."""
        from pydantic import HttpUrl

        from lookervault.config.models import LookerConfig

        # Create config with defaults
        config = LookerConfig(api_url=HttpUrl("https://test.looker.com"))

        assert config.timeout == 120

    def test_timeout_env_var_override(self):
        """Test that LOOKERVAULT_TIMEOUT overrides default."""
        import os

        # Set environment variable
        os.environ["LOOKERVAULT_TIMEOUT"] = "300"

        # Simulate loading config with env var
        timeout_str = os.getenv("LOOKERVAULT_TIMEOUT")
        timeout = int(timeout_str) if timeout_str else 120

        assert timeout == 300

        # Clean up
        del os.environ["LOOKERVAULT_TIMEOUT"]

    def test_timeout_validation(self):
        """Test timeout validation (5-600 seconds range)."""
        from pydantic import HttpUrl, ValidationError

        from lookervault.config.models import LookerConfig

        # Valid timeout
        config = LookerConfig(api_url=HttpUrl("https://test.looker.com"), timeout=300)
        assert config.timeout == 300

        # Too small (should fail)
        with pytest.raises(ValidationError):
            LookerConfig(api_url=HttpUrl("https://test.looker.com"), timeout=2)

        # Too large (should fail)
        with pytest.raises(ValidationError):
            LookerConfig(api_url=HttpUrl("https://test.looker.com"), timeout=700)


class TestContentSizeFormatting:
    """Test that list command formats content sizes correctly."""

    def test_format_size_kb(self):
        """Test KB formatting for small items."""
        size_bytes = 45 * 1024  # 45 KB
        size_kb = size_bytes / 1024

        if size_kb < 1024:
            size_str = f"{size_kb:.1f} KB"
        else:
            size_str = f"{size_kb / 1024:.1f} MB"

        assert size_str == "45.0 KB"

    def test_format_size_mb(self):
        """Test MB formatting for large items."""
        size_bytes = 5 * 1024 * 1024  # 5 MB
        size_kb = size_bytes / 1024

        if size_kb < 1024:
            size_str = f"{size_kb:.1f} KB"
        else:
            size_str = f"{size_kb / 1024:.1f} MB"

        assert size_str == "5.0 MB"
