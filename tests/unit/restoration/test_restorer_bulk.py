"""Unit tests for LookerContentRestorer.restore_bulk() method."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from lookervault.restoration.restorer import LookerContentRestorer
from lookervault.storage.models import ContentType, RestorationResult, RestorationSummary


@pytest.fixture
def mock_client():
    """Mock LookerClient."""
    return MagicMock()


@pytest.fixture
def mock_repository():
    """Mock ContentRepository."""
    return MagicMock()


@pytest.fixture
def mock_config():
    """Mock RestorationConfig."""
    config = Mock()
    config.session_id = "test_session"
    config.dry_run = False
    config.checkpoint_interval = 100
    return config


@pytest.fixture
def restorer(mock_client, mock_repository):
    """Create LookerContentRestorer instance with mocked dependencies."""
    return LookerContentRestorer(client=mock_client, repository=mock_repository)


def test_restore_bulk_no_content(restorer, mock_repository, mock_config):
    """Test restore_bulk when no content found in repository."""
    # Setup: repository returns empty set
    mock_repository.get_content_ids.return_value = set()

    # Execute
    result = restorer.restore_bulk(ContentType.DASHBOARD, mock_config)

    # Assert
    assert isinstance(result, RestorationSummary)
    assert result.total_items == 0
    assert result.success_count == 0
    assert result.error_count == 0
    assert result.session_id == "test_session"
    assert result.content_type_breakdown == {ContentType.DASHBOARD.value: 0}


def test_restore_bulk_success(restorer, mock_repository, mock_config):
    """Test restore_bulk with successful restorations."""
    # Setup: repository returns 3 content IDs
    mock_repository.get_content_ids.return_value = {"1", "2", "3"}

    # Mock restore_single to return success results
    with patch.object(restorer, "restore_single") as mock_restore_single:
        mock_restore_single.side_effect = [
            RestorationResult(
                content_id="1",
                content_type=ContentType.DASHBOARD.value,
                status="created",
                destination_id="101",
                duration_ms=100.0,
            ),
            RestorationResult(
                content_id="2",
                content_type=ContentType.DASHBOARD.value,
                status="updated",
                destination_id="2",
                duration_ms=150.0,
            ),
            RestorationResult(
                content_id="3",
                content_type=ContentType.DASHBOARD.value,
                status="created",
                destination_id="102",
                duration_ms=120.0,
            ),
        ]

        # Execute
        result = restorer.restore_bulk(ContentType.DASHBOARD, mock_config)

        # Assert
        assert result.total_items == 3
        assert result.success_count == 3
        assert result.created_count == 2
        assert result.updated_count == 1
        assert result.error_count == 0
        assert result.skipped_count == 0
        assert result.average_throughput > 0
        assert result.duration_seconds > 0
        assert result.content_type_breakdown == {ContentType.DASHBOARD.value: 3}
        assert result.error_breakdown == {}


def test_restore_bulk_with_errors(restorer, mock_repository, mock_config):
    """Test restore_bulk with some failures."""
    # Setup: repository returns 4 content IDs
    mock_repository.get_content_ids.return_value = {"1", "2", "3", "4"}

    # Mock restore_single with mixed results
    with patch.object(restorer, "restore_single") as mock_restore_single:
        mock_restore_single.side_effect = [
            RestorationResult(
                content_id="1",
                content_type=ContentType.DASHBOARD.value,
                status="created",
                destination_id="101",
                duration_ms=100.0,
            ),
            RestorationResult(
                content_id="2",
                content_type=ContentType.DASHBOARD.value,
                status="failed",
                error_message="Validation error: Missing required field",
                duration_ms=50.0,
            ),
            RestorationResult(
                content_id="3",
                content_type=ContentType.DASHBOARD.value,
                status="updated",
                destination_id="3",
                duration_ms=150.0,
            ),
            RestorationResult(
                content_id="4",
                content_type=ContentType.DASHBOARD.value,
                status="failed",
                error_message="Not found in repository",
                duration_ms=30.0,
            ),
        ]

        # Execute
        result = restorer.restore_bulk(ContentType.DASHBOARD, mock_config)

        # Assert
        assert result.total_items == 4
        assert result.success_count == 2
        assert result.created_count == 1
        assert result.updated_count == 1
        assert result.error_count == 2
        assert result.skipped_count == 0
        assert len(result.error_breakdown) == 2  # ValidationError and NotFoundError
        assert "ValidationError" in result.error_breakdown
        assert "NotFoundError" in result.error_breakdown


def test_restore_bulk_dry_run(restorer, mock_repository, mock_config):
    """Test restore_bulk in dry run mode."""
    # Setup
    mock_config.dry_run = True
    mock_repository.get_content_ids.return_value = {"1", "2"}

    # Mock restore_single for dry run
    with patch.object(restorer, "restore_single") as mock_restore_single:
        mock_restore_single.side_effect = [
            RestorationResult(
                content_id="1",
                content_type=ContentType.DASHBOARD.value,
                status="success",
                duration_ms=50.0,
            ),
            RestorationResult(
                content_id="2",
                content_type=ContentType.DASHBOARD.value,
                status="success",
                duration_ms=60.0,
            ),
        ]

        # Execute
        result = restorer.restore_bulk(ContentType.DASHBOARD, mock_config)

        # Assert
        assert result.total_items == 2
        assert result.success_count == 2
        assert result.created_count == 0  # No creates in dry run
        assert result.updated_count == 0  # No updates in dry run
        assert result.error_count == 0
        # Verify dry_run was passed to restore_single
        assert mock_restore_single.call_args_list[0][1]["dry_run"] is True


def test_restore_bulk_skipped_items(restorer, mock_repository, mock_config):
    """Test restore_bulk with skipped items."""
    # Setup
    mock_repository.get_content_ids.return_value = {"1", "2", "3"}

    # Mock restore_single with skipped results
    with patch.object(restorer, "restore_single") as mock_restore_single:
        mock_restore_single.side_effect = [
            RestorationResult(
                content_id="1",
                content_type=ContentType.DASHBOARD.value,
                status="created",
                destination_id="101",
                duration_ms=100.0,
            ),
            RestorationResult(
                content_id="2",
                content_type=ContentType.DASHBOARD.value,
                status="skipped",
                duration_ms=10.0,
            ),
            RestorationResult(
                content_id="3",
                content_type=ContentType.DASHBOARD.value,
                status="created",
                destination_id="102",
                duration_ms=120.0,
            ),
        ]

        # Execute
        result = restorer.restore_bulk(ContentType.DASHBOARD, mock_config)

        # Assert
        assert result.total_items == 3
        assert result.success_count == 2
        assert result.created_count == 2
        assert result.updated_count == 0
        assert result.error_count == 0
        assert result.skipped_count == 1


def test_restore_bulk_exception_handling(restorer, mock_repository, mock_config):
    """Test restore_bulk handles unexpected exceptions."""
    # Setup
    mock_repository.get_content_ids.return_value = {"1", "2"}

    # Mock restore_single to raise exception on second call
    with patch.object(restorer, "restore_single") as mock_restore_single:
        mock_restore_single.side_effect = [
            RestorationResult(
                content_id="1",
                content_type=ContentType.DASHBOARD.value,
                status="created",
                destination_id="101",
                duration_ms=100.0,
            ),
            RuntimeError("Unexpected error"),
        ]

        # Execute
        result = restorer.restore_bulk(ContentType.DASHBOARD, mock_config)

        # Assert: should handle exception gracefully
        assert result.total_items == 2
        assert result.success_count == 1
        assert result.error_count == 1
        assert "RuntimeError" in result.error_breakdown
        assert result.error_breakdown["RuntimeError"] == 1
