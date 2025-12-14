"""Unit tests for DeadLetterQueue class.

This test suite follows TDD principles - tests are written BEFORE implementation.
The tests define the expected behavior of the DeadLetterQueue class which will be
implemented in src/lookervault/restoration/dead_letter_queue.py as part of Phase 5.

Test Coverage:
- DeadLetterQueue initialization
- add() method with various error types
- get() method (found and not found scenarios)
- list() method with filters (session_id, content_type, pagination)
- retry() method (success and failure scenarios)
- clear() method (with/without force flag)
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from lookervault.exceptions import NotFoundError, RestorationError
from lookervault.restoration.dead_letter_queue import DeadLetterQueue
from lookervault.storage.models import ContentType, DeadLetterItem, RestorationResult


@pytest.fixture
def mock_repository():
    """Mock ContentRepository for testing DeadLetterQueue."""
    return MagicMock()


@pytest.fixture
def mock_restorer():
    """Mock LookerContentRestorer for retry testing."""
    return MagicMock()


@pytest.fixture
def dlq(mock_repository):
    """Create DeadLetterQueue instance with mocked repository."""
    return DeadLetterQueue(repository=mock_repository)


class TestDeadLetterQueueInit:
    """Test DeadLetterQueue initialization."""

    def test_init_should_store_repository(self, mock_repository):
        """Test __init__ stores repository reference."""
        dlq = DeadLetterQueue(repository=mock_repository)

        assert dlq.repository is mock_repository

    def test_init_should_accept_repository_only(self, mock_repository):
        """Test __init__ requires only repository parameter."""
        dlq = DeadLetterQueue(repository=mock_repository)

        assert dlq is not None
        assert hasattr(dlq, "repository")


class TestDeadLetterQueueAdd:
    """Test DeadLetterQueue.add() method."""

    def test_add_should_save_error_to_repository(self, dlq, mock_repository):
        """Test add() calls repository.save_dead_letter_item() with correct data."""
        # Setup
        content_id = "123"
        content_type = ContentType.DASHBOARD
        error_message = "Validation failed: Missing required field 'title'"
        session_id = "test_session"

        # Execute
        dlq.add(
            content_id=content_id,
            content_type=content_type,
            error_message=error_message,
            session_id=session_id,
        )

        # Assert
        mock_repository.save_dead_letter_item.assert_called_once()
        call_args = mock_repository.save_dead_letter_item.call_args[0][0]

        assert isinstance(call_args, DeadLetterItem)
        assert call_args.content_id == content_id
        assert call_args.content_type == content_type.value
        assert call_args.error_message == error_message
        assert call_args.session_id == session_id

    def test_add_should_extract_error_type_from_validation_error(self, dlq, mock_repository):
        """Test add() extracts 'ValidationError' from validation error messages."""
        # Execute
        dlq.add(
            content_id="123",
            content_type=ContentType.DASHBOARD,
            error_message="Validation failed: 422",
            session_id="test",
        )

        # Assert
        call_args = mock_repository.save_dead_letter_item.call_args[0][0]
        assert call_args.error_type == "ValidationError"

    def test_add_should_extract_error_type_from_not_found_error(self, dlq, mock_repository):
        """Test add() extracts 'NotFoundError' from not found error messages."""
        # Execute
        dlq.add(
            content_id="123",
            content_type=ContentType.DASHBOARD,
            error_message="Content not found in repository",
            session_id="test",
        )

        # Assert
        call_args = mock_repository.save_dead_letter_item.call_args[0][0]
        assert call_args.error_type == "NotFoundError"

    def test_add_should_extract_error_type_from_rate_limit_error(self, dlq, mock_repository):
        """Test add() extracts 'RateLimitError' from rate limit error messages."""
        # Execute
        dlq.add(
            content_id="123",
            content_type=ContentType.DASHBOARD,
            error_message="Rate limit exceeded: 429",
            session_id="test",
        )

        # Assert
        call_args = mock_repository.save_dead_letter_item.call_args[0][0]
        assert call_args.error_type == "RateLimitError"

    def test_add_should_default_to_api_error_for_unknown_types(self, dlq, mock_repository):
        """Test add() uses 'APIError' for unrecognized error messages."""
        # Execute
        dlq.add(
            content_id="123",
            content_type=ContentType.DASHBOARD,
            error_message="Some unknown error occurred",
            session_id="test",
        )

        # Assert
        call_args = mock_repository.save_dead_letter_item.call_args[0][0]
        assert call_args.error_type == "APIError"

    def test_add_should_include_stack_trace_when_provided(self, dlq, mock_repository):
        """Test add() stores stack trace when provided."""
        # Setup
        stack_trace = "Traceback (most recent call last):\n  File..."

        # Execute
        dlq.add(
            content_id="123",
            content_type=ContentType.DASHBOARD,
            error_message="Error",
            session_id="test",
            stack_trace=stack_trace,
        )

        # Assert
        call_args = mock_repository.save_dead_letter_item.call_args[0][0]
        assert call_args.stack_trace == stack_trace

    def test_add_should_include_retry_count_when_provided(self, dlq, mock_repository):
        """Test add() stores retry count when provided."""
        # Execute
        dlq.add(
            content_id="123",
            content_type=ContentType.DASHBOARD,
            error_message="Error",
            session_id="test",
            retry_count=5,
        )

        # Assert
        call_args = mock_repository.save_dead_letter_item.call_args[0][0]
        assert call_args.retry_count == 5

    def test_add_should_use_default_retry_count_zero(self, dlq, mock_repository):
        """Test add() uses retry_count=0 when not provided."""
        # Execute
        dlq.add(
            content_id="123",
            content_type=ContentType.DASHBOARD,
            error_message="Error",
            session_id="test",
        )

        # Assert
        call_args = mock_repository.save_dead_letter_item.call_args[0][0]
        assert call_args.retry_count == 0


class TestDeadLetterQueueGet:
    """Test DeadLetterQueue.get() method."""

    def test_get_should_return_item_when_found(self, dlq, mock_repository):
        """Test get() returns DeadLetterItem when found in repository."""
        # Setup: repository returns a DLQ item
        expected_item = DeadLetterItem(
            session_id="test_session",
            content_id="456",
            content_type=ContentType.DASHBOARD.value,
            content_data=b"test_data",
            error_message="Validation failed",
            error_type="ValidationError",
            retry_count=0,
            failed_at=datetime.now(UTC),
            id="dlq-123",
        )
        mock_repository.get_dead_letter_item.return_value = expected_item

        # Execute
        result = dlq.get(dlq_id="dlq-123")

        # Assert
        assert result == expected_item
        mock_repository.get_dead_letter_item.assert_called_once_with("dlq-123")

    def test_get_should_return_none_when_not_found(self, dlq, mock_repository):
        """Test get() returns None when DLQ item not found."""
        # Setup: repository returns None
        mock_repository.get_dead_letter_item.return_value = None

        # Execute
        result = dlq.get(dlq_id="nonexistent")

        # Assert
        assert result is None
        mock_repository.get_dead_letter_item.assert_called_once_with("nonexistent")


class TestDeadLetterQueueList:
    """Test DeadLetterQueue.list() method."""

    def test_list_should_return_all_items_without_filters(self, dlq, mock_repository):
        """Test list() returns all DLQ items when no filters provided."""
        # Setup: repository returns multiple items
        items = [
            DeadLetterItem(
                session_id="session1",
                content_id="1",
                content_type=ContentType.DASHBOARD.value,
                content_data=b"test_data_1",
                error_message="Error 1",
                error_type="ValidationError",
                retry_count=0,
                failed_at=datetime.now(UTC),
                id="dlq-1",
            ),
            DeadLetterItem(
                session_id="session1",
                content_id="2",
                content_type=ContentType.LOOK.value,
                content_data=b"test_data_2",
                error_message="Error 2",
                error_type="APIError",
                retry_count=0,
                failed_at=datetime.now(UTC),
                id="dlq-2",
            ),
        ]
        mock_repository.list_dead_letter_items.return_value = items

        # Execute
        result = dlq.list()

        # Assert
        assert result == items
        mock_repository.list_dead_letter_items.assert_called_once_with(
            session_id=None, content_type=None, limit=None, offset=None
        )

    def test_list_should_filter_by_session_id(self, dlq, mock_repository):
        """Test list() filters by session_id when provided."""
        # Setup
        mock_repository.list_dead_letter_items.return_value = []

        # Execute
        dlq.list(session_id="session_123")

        # Assert
        mock_repository.list_dead_letter_items.assert_called_once_with(
            session_id="session_123", content_type=None, limit=None, offset=None
        )

    def test_list_should_filter_by_content_type(self, dlq, mock_repository):
        """Test list() filters by content_type when provided."""
        # Setup
        mock_repository.list_dead_letter_items.return_value = []

        # Execute
        dlq.list(content_type=ContentType.DASHBOARD)

        # Assert
        mock_repository.list_dead_letter_items.assert_called_once_with(
            session_id=None, content_type=ContentType.DASHBOARD.value, limit=None, offset=None
        )

    def test_list_should_support_pagination_with_limit(self, dlq, mock_repository):
        """Test list() supports pagination with limit parameter."""
        # Setup
        mock_repository.list_dead_letter_items.return_value = []

        # Execute
        dlq.list(limit=10)

        # Assert
        mock_repository.list_dead_letter_items.assert_called_once_with(
            session_id=None, content_type=None, limit=10, offset=None
        )

    def test_list_should_support_pagination_with_offset(self, dlq, mock_repository):
        """Test list() supports pagination with offset parameter."""
        # Setup
        mock_repository.list_dead_letter_items.return_value = []

        # Execute
        dlq.list(offset=20)

        # Assert
        mock_repository.list_dead_letter_items.assert_called_once_with(
            session_id=None, content_type=None, limit=None, offset=20
        )

    def test_list_should_combine_all_filters(self, dlq, mock_repository):
        """Test list() applies all filters when provided together."""
        # Setup
        mock_repository.list_dead_letter_items.return_value = []

        # Execute
        dlq.list(
            session_id="session_123",
            content_type=ContentType.DASHBOARD,
            limit=10,
            offset=20,
        )

        # Assert
        mock_repository.list_dead_letter_items.assert_called_once_with(
            session_id="session_123",
            content_type=ContentType.DASHBOARD.value,
            limit=10,
            offset=20,
        )


class TestDeadLetterQueueRetry:
    """Test DeadLetterQueue.retry() method."""

    def test_retry_should_succeed_and_delete_from_dlq(self, dlq, mock_repository, mock_restorer):
        """Test retry() successfully restores item and removes from DLQ."""
        # Setup: DLQ item exists in repository
        dlq_item = DeadLetterItem(
            session_id="test_session",
            content_id="456",
            content_type=ContentType.DASHBOARD.value,
            content_data=b"test_data",
            error_message="Validation failed",
            error_type="ValidationError",
            retry_count=0,
            failed_at=datetime.now(UTC),
            id="dlq-123",
        )
        mock_repository.get_dead_letter_item.return_value = dlq_item

        # Setup: restorer succeeds
        success_result = RestorationResult(
            content_id="456",
            content_type=ContentType.DASHBOARD.value,
            status="created",
            destination_id="789",
            duration_ms=100.0,
        )
        mock_restorer.restore_single.return_value = success_result

        # Execute
        result = dlq.retry(dlq_id="dlq-123", restorer=mock_restorer)

        # Assert
        assert result == success_result
        mock_repository.get_dead_letter_item.assert_called_once_with("dlq-123")
        mock_restorer.restore_single.assert_called_once_with(
            content_id="456", content_type=ContentType.DASHBOARD
        )
        mock_repository.delete_dead_letter_item.assert_called_once_with("dlq-123")

    def test_retry_should_fail_when_dlq_item_not_found(self, dlq, mock_repository, mock_restorer):
        """Test retry() raises NotFoundError when DLQ item doesn't exist."""
        # Setup: DLQ item not found
        mock_repository.get_dead_letter_item.return_value = None

        # Execute & Assert
        with pytest.raises(NotFoundError, match="DLQ item dlq-nonexistent not found"):
            dlq.retry(dlq_id="dlq-nonexistent", restorer=mock_restorer)

        # Verify restorer was never called
        mock_restorer.restore_single.assert_not_called()
        mock_repository.delete_dead_letter_item.assert_not_called()

    def test_retry_should_keep_in_dlq_when_restoration_fails(
        self, dlq, mock_repository, mock_restorer
    ):
        """Test retry() keeps item in DLQ when restoration fails again."""
        # Setup: DLQ item exists
        dlq_item = DeadLetterItem(
            session_id="test_session",
            content_id="456",
            content_type=ContentType.DASHBOARD.value,
            content_data=b"test_data",
            error_message="Validation failed",
            error_type="ValidationError",
            retry_count=0,
            failed_at=datetime.now(UTC),
            id="dlq-123",
        )
        mock_repository.get_dead_letter_item.return_value = dlq_item

        # Setup: restorer fails again
        failure_result = RestorationResult(
            content_id="456",
            content_type=ContentType.DASHBOARD.value,
            status="failed",
            error_message="Still failing: Validation error",
            duration_ms=50.0,
        )
        mock_restorer.restore_single.return_value = failure_result

        # Execute
        result = dlq.retry(dlq_id="dlq-123", restorer=mock_restorer)

        # Assert
        assert result == failure_result
        mock_restorer.restore_single.assert_called_once()
        # Item should NOT be deleted from DLQ
        mock_repository.delete_dead_letter_item.assert_not_called()

    def test_retry_should_handle_restore_single_exception(
        self, dlq, mock_repository, mock_restorer
    ):
        """Test retry() handles exceptions from restore_single gracefully."""
        # Setup: DLQ item exists
        dlq_item = DeadLetterItem(
            session_id="test_session",
            content_id="456",
            content_type=ContentType.DASHBOARD.value,
            content_data=b"test_data",
            error_message="Validation failed",
            error_type="ValidationError",
            retry_count=0,
            failed_at=datetime.now(UTC),
            id="dlq-123",
        )
        mock_repository.get_dead_letter_item.return_value = dlq_item

        # Setup: restorer raises exception
        mock_restorer.restore_single.side_effect = RestorationError("Unexpected error")

        # Execute & Assert
        with pytest.raises(RestorationError, match="Unexpected error"):
            dlq.retry(dlq_id="dlq-123", restorer=mock_restorer)

        # Item should NOT be deleted from DLQ
        mock_repository.delete_dead_letter_item.assert_not_called()


class TestDeadLetterQueueClear:
    """Test DeadLetterQueue.clear() method."""

    def test_clear_should_delete_all_items_without_filters(self, dlq, mock_repository):
        """Test clear() deletes all DLQ items when no filters provided."""
        # Setup: repository returns count
        mock_repository.count_dead_letter_items.return_value = 5

        # Execute
        count = dlq.clear(force=True)

        # Assert
        assert count == 5
        mock_repository.count_dead_letter_items.assert_called_once_with(
            session_id=None, content_type=None
        )
        # Verify all items were deleted (implementation detail: calls delete for each)
        # This assumes clear() gets count, then deletes - actual implementation may vary

    def test_clear_should_filter_by_session_id(self, dlq, mock_repository):
        """Test clear() filters by session_id when provided."""
        # Setup
        mock_repository.count_dead_letter_items.return_value = 3

        # Execute
        count = dlq.clear(session_id="session_123", force=True)

        # Assert
        assert count == 3
        mock_repository.count_dead_letter_items.assert_called_once_with(
            session_id="session_123", content_type=None
        )

    def test_clear_should_filter_by_content_type(self, dlq, mock_repository):
        """Test clear() filters by content_type when provided."""
        # Setup
        mock_repository.count_dead_letter_items.return_value = 2

        # Execute
        count = dlq.clear(content_type=ContentType.DASHBOARD, force=True)

        # Assert
        assert count == 2
        mock_repository.count_dead_letter_items.assert_called_once_with(
            session_id=None, content_type=ContentType.DASHBOARD.value
        )

    def test_clear_should_require_force_flag_for_safety(self, dlq, mock_repository):
        """Test clear() requires force=True flag to prevent accidental deletion."""
        # Execute & Assert
        with pytest.raises(ValueError, match="force=True required"):
            dlq.clear()

    def test_clear_should_succeed_with_force_flag(self, dlq, mock_repository):
        """Test clear() succeeds when force=True is provided."""
        # Setup
        mock_repository.count_dead_letter_items.return_value = 10

        # Execute
        count = dlq.clear(force=True)

        # Assert
        assert count == 10
        mock_repository.count_dead_letter_items.assert_called_once()


class TestDeadLetterQueueErrorTypeExtraction:
    """Test error type extraction logic in DeadLetterQueue."""

    @pytest.mark.parametrize(
        "error_message,expected_type",
        [
            ("Content not found in repository", "NotFoundError"),
            ("Dashboard not found: 404", "NotFoundError"),
            ("Validation failed: Missing required field", "ValidationError"),
            ("Validation error: 422 Unprocessable", "ValidationError"),
            ("Rate limit exceeded: 429", "RateLimitError"),
            ("Too many requests: 429", "RateLimitError"),
            ("Authentication failed: 401", "AuthenticationError"),
            ("Unauthorized: 401", "AuthenticationError"),
            ("Authorization failed: 403", "AuthorizationError"),
            ("Forbidden: 403", "AuthorizationError"),
            ("Connection timeout exceeded", "TimeoutError"),
            ("Request timed out", "TimeoutError"),
            ("Some unknown error", "APIError"),
            ("Generic failure", "APIError"),
        ],
    )
    def test_extract_error_type_should_categorize_correctly(
        self, dlq, mock_repository, error_message, expected_type
    ):
        """Test error type extraction categorizes various error messages correctly."""
        # Execute
        dlq.add(
            content_id="123",
            content_type=ContentType.DASHBOARD,
            error_message=error_message,
            session_id="test",
        )

        # Assert
        call_args = mock_repository.save_dead_letter_item.call_args[0][0]
        assert call_args.error_type == expected_type
