"""Tests for idempotent upsert operations in SQLiteContentRepository.

This test suite validates that all repository upsert operations are idempotent:
- Running the same operation twice should update instead of duplicating
- Different natural keys should create separate records
- Primary keys should remain consistent across upserts

Test Coverage:
- Checkpoint upserts (natural key: session_id + content_type)
- ExtractionSession upserts (natural key: id)
- DeadLetterItem upserts (natural key: session_id + content_id + content_type + retry_count)
- RestorationCheckpoint upserts (natural key: session_id + content_type)
- RestorationSession upserts (natural key: id)
"""

from datetime import datetime

import pytest

from lookervault.storage.models import (
    Checkpoint,
    ContentType,
    DeadLetterItem,
    ExtractionSession,
    RestorationCheckpoint,
    RestorationSession,
)
from lookervault.storage.repository import SQLiteContentRepository


@pytest.fixture
def repo(tmp_path):
    """Create temporary repository for testing."""
    db_path = tmp_path / "test.db"
    return SQLiteContentRepository(db_path)


class TestCheckpointUpsert:
    """Test idempotent upsert operations for Checkpoint."""

    def test_save_checkpoint_twice_upserts(self, repo):
        """Saving same checkpoint twice should update, not duplicate."""
        checkpoint = Checkpoint(
            session_id="test-session",
            content_type=ContentType.DASHBOARD.value,
            checkpoint_data={"offset": 0},
            started_at=datetime.now(),
            item_count=100,
        )

        # First save
        id1 = repo.save_checkpoint(checkpoint)

        # Second save with updated data
        checkpoint.item_count = 200
        checkpoint.checkpoint_data = {"offset": 200}
        id2 = repo.save_checkpoint(checkpoint)

        # Should return same ID (update, not insert)
        assert id1 == id2

        # Verify only one checkpoint exists
        latest = repo.get_latest_checkpoint(ContentType.DASHBOARD.value, "test-session")
        assert latest.id == id1
        assert latest.item_count == 200
        assert latest.checkpoint_data == {"offset": 200}

    def test_save_checkpoint_different_content_type_creates_new(self, repo):
        """Different content types should create separate checkpoints."""
        checkpoint1 = Checkpoint(
            session_id="test-session",
            content_type=ContentType.DASHBOARD.value,
            checkpoint_data={"offset": 0},
            started_at=datetime.now(),
            item_count=100,
        )

        checkpoint2 = Checkpoint(
            session_id="test-session",
            content_type=ContentType.LOOK.value,  # Different type
            checkpoint_data={"offset": 0},
            started_at=datetime.now(),
            item_count=50,
        )

        id1 = repo.save_checkpoint(checkpoint1)
        id2 = repo.save_checkpoint(checkpoint2)

        # Should create two separate checkpoints
        assert id1 != id2


class TestSessionUpsert:
    """Test idempotent upsert operations for ExtractionSession."""

    def test_create_session_twice_upserts(self, repo):
        """Creating same session twice should update, not fail."""
        session = ExtractionSession(
            id="test-session-id",
            started_at=datetime.now(),
            status="running",
            total_items=0,
            error_count=0,
        )

        # First create
        repo.create_session(session)

        # Second create with updated data
        session.total_items = 1000
        session.status = "completed"
        repo.create_session(session)  # Should not raise

        # Verify session was updated
        loaded = repo.get_extraction_session("test-session-id")
        assert loaded.total_items == 1000
        assert loaded.status == "completed"
        assert loaded.started_at == session.started_at  # Preserved


class TestDLQUpsert:
    """Test idempotent upsert operations for DeadLetterItem."""

    def test_save_dlq_same_retry_count_upserts(self, repo):
        """Saving same content+retry_count should update, not duplicate."""
        session = RestorationSession(
            id="test-restore-session",
            started_at=datetime.now(),
            status="running",
            destination_instance="https://example.looker.com",
        )
        repo.create_restoration_session(session)

        dlq_item = DeadLetterItem(
            session_id="test-restore-session",
            content_id="dashboard-123",
            content_type=ContentType.DASHBOARD.value,
            content_data=b"serialized data",
            error_message="Network timeout",
            error_type="NetworkError",
            retry_count=1,
            failed_at=datetime.now(),
        )

        # First save
        id1 = repo.save_dead_letter_item(dlq_item)

        # Second save with updated error message (same retry_count)
        dlq_item.error_message = "Network timeout (retry 1)"
        id2 = repo.save_dead_letter_item(dlq_item)

        # Should update existing (same ID)
        assert id1 == id2

        # Verify error message was updated
        loaded = repo.get_dead_letter_item(id1)
        assert loaded.error_message == "Network timeout (retry 1)"

    def test_save_dlq_different_retry_count_creates_new(self, repo):
        """Different retry_count should create separate DLQ entries."""
        session = RestorationSession(
            id="test-restore-session",
            started_at=datetime.now(),
            status="running",
            destination_instance="https://example.looker.com",
        )
        repo.create_restoration_session(session)

        dlq_item1 = DeadLetterItem(
            session_id="test-restore-session",
            content_id="dashboard-123",
            content_type=ContentType.DASHBOARD.value,
            content_data=b"serialized data",
            error_message="Network timeout",
            error_type="NetworkError",
            retry_count=1,
            failed_at=datetime.now(),
        )

        dlq_item2 = DeadLetterItem(
            session_id="test-restore-session",
            content_id="dashboard-123",
            content_type=ContentType.DASHBOARD.value,
            content_data=b"serialized data",
            error_message="Network timeout again",
            error_type="NetworkError",
            retry_count=2,  # Different retry count
            failed_at=datetime.now(),
        )

        id1 = repo.save_dead_letter_item(dlq_item1)
        id2 = repo.save_dead_letter_item(dlq_item2)

        # Should create two separate entries
        assert id1 != id2

        # Verify both exist
        items = repo.list_dead_letter_items(session_id="test-restore-session")
        assert len(items) == 2


class TestRestorationCheckpointUpsert:
    """Test idempotent upsert operations for RestorationCheckpoint."""

    def test_save_restoration_checkpoint_twice_upserts(self, repo):
        """Saving same restoration checkpoint twice should update."""
        checkpoint = RestorationCheckpoint(
            session_id="test-restore-session",
            content_type=ContentType.DASHBOARD.value,
            checkpoint_data={"processed_ids": ["id1", "id2"]},
            started_at=datetime.now(),
            item_count=2,
            error_count=0,
        )

        # First save
        id1 = repo.save_restoration_checkpoint(checkpoint)

        # Second save with updated data
        checkpoint.item_count = 5
        checkpoint.checkpoint_data = {"processed_ids": ["id1", "id2", "id3", "id4", "id5"]}
        id2 = repo.save_restoration_checkpoint(checkpoint)

        # Should return same ID (update, not insert)
        assert id1 == id2

        # Verify checkpoint was updated
        latest = repo.get_latest_restoration_checkpoint(
            ContentType.DASHBOARD.value, "test-restore-session"
        )
        assert latest.id == id1
        assert latest.item_count == 5


class TestRestorationSessionUpsert:
    """Test idempotent upsert operations for RestorationSession."""

    def test_create_restoration_session_twice_upserts(self, repo):
        """Creating same restoration session twice should update."""
        session = RestorationSession(
            id="test-restore-id",
            started_at=datetime.now(),
            status="running",
            total_items=0,
            success_count=0,
            error_count=0,
            destination_instance="https://example.looker.com",
        )

        # First create
        repo.create_restoration_session(session)

        # Second create with updated data
        session.total_items = 500
        session.success_count = 450
        session.error_count = 50
        session.status = "completed"
        repo.create_restoration_session(session)

        # Verify session was updated
        loaded = repo.get_restoration_session("test-restore-id")
        assert loaded.total_items == 500
        assert loaded.success_count == 450
        assert loaded.error_count == 50
        assert loaded.status == "completed"
        assert loaded.started_at == session.started_at  # Preserved
