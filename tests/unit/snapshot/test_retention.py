"""Unit tests for snapshot retention module."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from google.api_core.exceptions import Forbidden, GoogleAPICallError

from lookervault.snapshot.models import RetentionPolicy, SnapshotMetadata
from lookervault.snapshot.retention import (
    AuditLogger,
    delete_old_snapshots,
    delete_snapshot,
    evaluate_retention_policy,
    preview_cleanup,
    protect_minimum_backups,
    validate_safety_threshold,
)


class TestAuditLogger:
    """Test audit logging functionality."""

    def test_audit_logger_creation(self, tmp_path):
        """Test audit logger creation and directory setup."""
        log_path = tmp_path / "audit" / "test.log"
        logger = AuditLogger(log_path=str(log_path))

        # Verify directory was created
        assert log_path.parent.exists()
        assert logger.log_path == log_path

    def test_audit_log_deletion_success(self, tmp_path):
        """Test logging successful deletion."""
        log_path = tmp_path / "audit.log"
        logger = AuditLogger(log_path=str(log_path))

        snapshot = SnapshotMetadata(
            sequential_index=1,
            filename="snapshots/looker-2025-12-14T10-30-00.db.gz",
            timestamp=datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
            size_bytes=1024,
            gcs_bucket="test-bucket",
            gcs_path="gs://test-bucket/snapshots/looker-2025-12-14T10-30-00.db.gz",
            crc32c="AAAAAA==",
            content_encoding="gzip",
            tags=[],
            created=datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
            updated=datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
        )

        logger.log_deletion(snapshot, reason="test_deletion", success=True)

        # Verify log file was created
        assert log_path.exists()

        # Verify log entry
        with log_path.open() as f:
            log_entry = json.loads(f.readline())

        assert log_entry["action"] == "delete"
        assert log_entry["snapshot_filename"] == snapshot.filename
        assert log_entry["reason"] == "test_deletion"
        assert log_entry["success"] is True
        assert "timestamp" in log_entry
        assert "user" in log_entry

    def test_audit_log_deletion_failure(self, tmp_path):
        """Test logging failed deletion."""
        log_path = tmp_path / "audit.log"
        logger = AuditLogger(log_path=str(log_path))

        snapshot = SnapshotMetadata(
            sequential_index=1,
            filename="snapshots/looker-2025-12-14T10-30-00.db.gz",
            timestamp=datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
            size_bytes=1024,
            gcs_bucket="test-bucket",
            gcs_path="gs://test-bucket/snapshots/looker-2025-12-14T10-30-00.db.gz",
            crc32c="AAAAAA==",
            content_encoding="gzip",
            tags=[],
            created=datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
            updated=datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
        )

        logger.log_deletion(
            snapshot,
            reason="test_deletion",
            success=False,
            error_message="Test error",
        )

        # Verify log entry
        with log_path.open() as f:
            log_entry = json.loads(f.readline())

        assert log_entry["action"] == "delete_failed"
        assert log_entry["success"] is False
        assert log_entry["error"] == "Test error"

    def test_audit_log_multiple_entries(self, tmp_path):
        """Test logging multiple deletion operations."""
        log_path = tmp_path / "audit.log"
        logger = AuditLogger(log_path=str(log_path))

        for i in range(1, 4):  # Changed to start from 1 (sequential_index must be positive)
            snapshot = SnapshotMetadata(
                sequential_index=i,
                filename=f"snapshots/looker-{i}.db.gz",
                timestamp=datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
                size_bytes=1024,
                gcs_bucket="test-bucket",
                gcs_path=f"gs://test-bucket/snapshots/looker-{i}.db.gz",
                crc32c="AAAAAA==",
                content_encoding="gzip",
                tags=[],
                created=datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
                updated=datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
            )

            logger.log_deletion(snapshot, reason="cleanup", success=True)

        # Verify all entries
        with log_path.open() as f:
            entries = [json.loads(line) for line in f]

        assert len(entries) == 3

    def test_audit_log_user_from_environment(self, tmp_path):
        """Test that user is captured from environment."""
        log_path = tmp_path / "audit.log"
        logger = AuditLogger(log_path=str(log_path))

        snapshot = SnapshotMetadata(
            sequential_index=1,
            filename="snapshots/looker-2025-12-14T10-30-00.db.gz",
            timestamp=datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
            size_bytes=1024,
            gcs_bucket="test-bucket",
            gcs_path="gs://test-bucket/snapshots/looker-2025-12-14T10-30-00.db.gz",
            crc32c="AAAAAA==",
            content_encoding="gzip",
            tags=[],
            created=datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
            updated=datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
        )

        with patch.dict(os.environ, {"USER": "testuser"}):
            logger.log_deletion(snapshot, reason="test", success=True)

        with log_path.open() as f:
            log_entry = json.loads(f.readline())

        assert log_entry["user"] == "testuser"


class TestEvaluateRetentionPolicy:
    """Test retention policy evaluation."""

    @pytest.fixture
    def snapshots(self):
        """Create mock snapshots with different ages."""
        now = datetime.now(UTC)
        return [
            self._create_snapshot(1, now - timedelta(days=1)),  # 1 day old
            self._create_snapshot(2, now - timedelta(days=5)),  # 5 days old
            self._create_snapshot(3, now - timedelta(days=35)),  # 35 days old
            self._create_snapshot(4, now - timedelta(days=60)),  # 60 days old
            self._create_snapshot(5, now - timedelta(days=100)),  # 100 days old
        ]

    def test_retention_policy_disabled(self, snapshots):
        """Test that all snapshots are protected when policy is disabled."""
        policy = RetentionPolicy(enabled=False)

        evaluation = evaluate_retention_policy(snapshots, policy)

        assert len(evaluation.snapshots_to_protect) == len(snapshots)
        assert len(evaluation.snapshots_to_delete) == 0

    def test_retention_policy_min_days_protection(self):
        """Test snapshots within min_days are protected."""
        now = datetime.now(UTC)
        snapshots = [
            self._create_snapshot(1, now - timedelta(days=1)),
            self._create_snapshot(2, now - timedelta(days=15)),
            self._create_snapshot(3, now - timedelta(days=45)),
        ]

        policy = RetentionPolicy(min_days=30, max_days=90, min_count=1)

        evaluation = evaluate_retention_policy(snapshots, policy)

        # First two should be protected (within min_days)
        protected_filenames = [s.filename for s in evaluation.snapshots_to_protect]
        assert "snapshot-1.db.gz" in protected_filenames
        assert "snapshot-2.db.gz" in protected_filenames

    def test_retention_policy_max_days_deletion(self):
        """Test snapshots older than max_days are deleted."""
        now = datetime.now(UTC)
        snapshots = [
            self._create_snapshot(1, now - timedelta(days=35)),
            self._create_snapshot(2, now - timedelta(days=60)),
            self._create_snapshot(3, now - timedelta(days=100)),
        ]

        policy = RetentionPolicy(min_days=30, max_days=90, min_count=1)

        evaluation = evaluate_retention_policy(snapshots, policy)

        # Snapshot 3 should be marked for deletion (>90 days)
        delete_filenames = [s.filename for s in evaluation.snapshots_to_delete]
        assert "snapshot-3.db.gz" in delete_filenames

    def test_retention_policy_min_count_protection(self):
        """Test minimum count protection."""
        now = datetime.now(UTC)
        snapshots = [
            self._create_snapshot(1, now - timedelta(days=100)),
            self._create_snapshot(2, now - timedelta(days=101)),
            self._create_snapshot(3, now - timedelta(days=102)),
        ]

        policy = RetentionPolicy(min_days=30, max_days=90, min_count=3)

        evaluation = evaluate_retention_policy(snapshots, policy)

        # All 3 should be protected by min_count (even though older than max_days)
        assert len(evaluation.snapshots_to_protect) == 3
        assert len(evaluation.snapshots_to_delete) == 0

    def test_retention_policy_protection_reasons(self, snapshots):
        """Test protection reasons are provided."""
        policy = RetentionPolicy(min_days=30, max_days=90, min_count=2)

        evaluation = evaluate_retention_policy(snapshots, policy)

        # Verify protection reasons exist
        assert len(evaluation.protection_reasons) > 0

        # Check for specific reason types
        reasons = list(evaluation.protection_reasons.values())
        assert any("minimum_backup_count" in r for r in reasons)

    @staticmethod
    def _create_snapshot(index, created_at):
        """Helper to create snapshot with specific creation time."""
        return SnapshotMetadata(
            sequential_index=index,
            filename=f"snapshot-{index}.db.gz",
            timestamp=created_at,
            size_bytes=1024 * index,
            gcs_bucket="test-bucket",
            gcs_path=f"gs://test-bucket/snapshots/snapshot-{index}.db.gz",
            crc32c="AAAAAA==",
            content_encoding="gzip",
            tags=[],
            created=created_at,
            updated=created_at,
        )


class TestProtectMinimumBackups:
    """Test minimum backup protection."""

    def test_protect_minimum_backups_sufficient(self):
        """Test protecting minimum backups when sufficient exist."""
        now = datetime.now(UTC)
        snapshots = [
            self._create_snapshot(1, now - timedelta(days=1)),
            self._create_snapshot(2, now - timedelta(days=2)),
            self._create_snapshot(3, now - timedelta(days=3)),
        ]

        protected_indices = protect_minimum_backups(snapshots, min_count=2)

        assert len(protected_indices) == 2
        assert 0 in protected_indices  # Most recent
        assert 1 in protected_indices  # Second most recent

    def test_protect_minimum_backups_fewer_than_min(self):
        """Test protecting when fewer snapshots exist than minimum."""
        now = datetime.now(UTC)
        snapshots = [
            self._create_snapshot(1, now - timedelta(days=1)),
            self._create_snapshot(2, now - timedelta(days=2)),
        ]

        protected_indices = protect_minimum_backups(snapshots, min_count=5)

        # Should protect all available snapshots
        assert len(protected_indices) == 2

    @staticmethod
    def _create_snapshot(index, created_at):
        """Helper to create snapshot."""
        return SnapshotMetadata(
            sequential_index=index,
            filename=f"snapshot-{index}.db.gz",
            timestamp=created_at,
            size_bytes=1024,
            gcs_bucket="test-bucket",
            gcs_path=f"gs://test-bucket/snapshots/snapshot-{index}.db.gz",
            crc32c="AAAAAA==",
            content_encoding="gzip",
            tags=[],
            created=created_at,
            updated=created_at,
        )


class TestDeleteOldSnapshots:
    """Test snapshot deletion functionality."""

    @pytest.fixture
    def mock_snapshots(self):
        """Create mock snapshots for deletion."""
        return [
            SnapshotMetadata(
                sequential_index=1,
                filename="snapshots/old-1.db.gz",
                timestamp=datetime(2025, 12, 1, 10, 0, 0, tzinfo=UTC),
                size_bytes=1024,
                gcs_bucket="test-bucket",
                gcs_path="gs://test-bucket/snapshots/old-1.db.gz",
                crc32c="AAAAAA==",
                content_encoding="gzip",
                tags=[],
                created=datetime(2025, 12, 1, 10, 0, 0, tzinfo=UTC),
                updated=datetime(2025, 12, 1, 10, 0, 0, tzinfo=UTC),
            ),
            SnapshotMetadata(
                sequential_index=2,
                filename="snapshots/old-2.db.gz",
                timestamp=datetime(2025, 12, 2, 10, 0, 0, tzinfo=UTC),
                size_bytes=2048,
                gcs_bucket="test-bucket",
                gcs_path="gs://test-bucket/snapshots/old-2.db.gz",
                crc32c="BBBBBB==",
                content_encoding="gzip",
                tags=[],
                created=datetime(2025, 12, 2, 10, 0, 0, tzinfo=UTC),
                updated=datetime(2025, 12, 2, 10, 0, 0, tzinfo=UTC),
            ),
        ]

    def test_delete_old_snapshots_dry_run(self, mock_snapshots):
        """Test deletion in dry run mode."""
        mock_client = MagicMock()

        result = delete_old_snapshots(
            client=mock_client,
            bucket_name="test-bucket",
            snapshots_to_delete=mock_snapshots,
            dry_run=True,
        )

        # Should report deletions without actually deleting
        assert result.deleted == 2
        assert result.failed == 0
        assert result.skipped == 0
        assert result.size_freed_bytes == 3072  # 1024 + 2048

    def test_delete_old_snapshots_success(self, mock_snapshots):
        """Test successful deletion."""
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        mock_blob.exists.return_value = True

        result = delete_old_snapshots(
            client=mock_client,
            bucket_name="test-bucket",
            snapshots_to_delete=mock_snapshots,
            dry_run=False,
        )

        # Verify deletion calls
        assert mock_blob.delete.call_count == 2
        assert result.deleted == 2
        assert result.failed == 0

    def test_delete_old_snapshots_protected(self, mock_snapshots):
        """Test handling of protected snapshots."""
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        mock_blob.exists.return_value = True
        mock_blob.delete.side_effect = Forbidden("Protected by retention policy")

        result = delete_old_snapshots(
            client=mock_client,
            bucket_name="test-bucket",
            snapshots_to_delete=mock_snapshots,
            dry_run=False,
        )

        # Should skip protected snapshots
        assert result.skipped == 2
        assert result.deleted == 0

    def test_delete_old_snapshots_with_audit_logger(self, mock_snapshots, tmp_path):
        """Test deletion with audit logging."""
        log_path = tmp_path / "audit.log"
        audit_logger = AuditLogger(log_path=str(log_path))

        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        mock_blob.exists.return_value = True

        result = delete_old_snapshots(
            client=mock_client,
            bucket_name="test-bucket",
            snapshots_to_delete=mock_snapshots,
            audit_logger=audit_logger,
            dry_run=False,
        )

        # Verify audit log entries
        assert log_path.exists()
        with log_path.open() as f:
            entries = [json.loads(line) for line in f]

        assert len(entries) == 2


class TestValidateSafetyThreshold:
    """Test safety threshold validation."""

    def test_validate_safety_threshold_passes(self):
        """Test validation passes when above threshold."""
        snapshots = [MagicMock() for _ in range(5)]

        # Should not raise
        validate_safety_threshold(snapshots, min_count=3)

    def test_validate_safety_threshold_fails(self):
        """Test validation fails when below threshold."""
        snapshots = [MagicMock() for _ in range(2)]

        with pytest.raises(ValueError) as exc_info:
            validate_safety_threshold(snapshots, min_count=5)

        assert "Safety check failed" in str(exc_info.value)

    def test_validate_safety_threshold_with_force(self):
        """Test validation bypassed with force flag."""
        snapshots = [MagicMock() for _ in range(2)]

        # Should not raise with force=True
        validate_safety_threshold(snapshots, min_count=5, force=True)


class TestPreviewCleanup:
    """Test cleanup preview functionality."""

    def test_preview_cleanup_statistics(self):
        """Test cleanup preview provides correct statistics."""
        now = datetime.now(UTC)
        snapshots_to_protect = [
            SnapshotMetadata(
                sequential_index=1,
                filename="keep-1.db.gz",
                timestamp=now,
                size_bytes=1024,
                gcs_bucket="test-bucket",
                gcs_path="gs://test-bucket/snapshots/keep-1.db.gz",
                crc32c="AAAAAA==",
                content_encoding="gzip",
                tags=[],
                created=now,
                updated=now,
            )
        ]

        snapshots_to_delete = [
            SnapshotMetadata(
                sequential_index=2,
                filename="delete-1.db.gz",
                timestamp=now - timedelta(days=100),
                size_bytes=2048,
                gcs_bucket="test-bucket",
                gcs_path="gs://test-bucket/snapshots/delete-1.db.gz",
                crc32c="BBBBBB==",
                content_encoding="gzip",
                tags=[],
                created=now - timedelta(days=100),
                updated=now - timedelta(days=100),
            ),
            SnapshotMetadata(
                sequential_index=3,
                filename="delete-2.db.gz",
                timestamp=now - timedelta(days=101),
                size_bytes=3072,
                gcs_bucket="test-bucket",
                gcs_path="gs://test-bucket/snapshots/delete-2.db.gz",
                crc32c="CCCCCC==",
                content_encoding="gzip",
                tags=[],
                created=now - timedelta(days=101),
                updated=now - timedelta(days=101),
            ),
        ]

        from lookervault.snapshot.retention import RetentionEvaluation

        evaluation = RetentionEvaluation(
            snapshots_to_protect=snapshots_to_protect,
            snapshots_to_delete=snapshots_to_delete,
            protection_reasons={},
        )

        policy = RetentionPolicy()
        preview = preview_cleanup(evaluation, policy)

        assert preview["total_snapshots"] == 3
        assert preview["protected_count"] == 1
        assert preview["delete_count"] == 2
        assert preview["size_to_free_bytes"] == 5120  # 2048 + 3072
        # 5120 bytes = 5.0 KB, which rounds to 0.0 MB (5120 / 1024 / 1024 = 0.00488 MB)
        assert preview["size_to_free_mb"] == 0.0
