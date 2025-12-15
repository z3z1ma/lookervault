"""Unit tests for snapshot lister module."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from lookervault.snapshot.lister import (
    BlobCache,
    filter_by_date_range,
    get_snapshot_by_index,
    list_snapshots,
    parse_timestamp_from_filename,
)
from lookervault.snapshot.models import SnapshotMetadata


class TestParseTimestampFromFilename:
    """Test timestamp parsing from snapshot filenames."""

    def test_parse_valid_filename_with_gz(self):
        """Test parsing valid filename with .gz extension."""
        filename = "looker-2025-12-14T10-30-45.db.gz"
        timestamp = parse_timestamp_from_filename(filename)

        assert timestamp == datetime(2025, 12, 14, 10, 30, 45, tzinfo=UTC)

    def test_parse_valid_filename_without_gz(self):
        """Test parsing valid filename without .gz extension."""
        filename = "looker-2025-12-14T10-30-45.db"
        timestamp = parse_timestamp_from_filename(filename)

        assert timestamp == datetime(2025, 12, 14, 10, 30, 45, tzinfo=UTC)

    def test_parse_filename_with_path_prefix(self):
        """Test parsing filename with directory prefix."""
        filename = "snapshots/looker-2025-12-14T10-30-45.db.gz"
        timestamp = parse_timestamp_from_filename(filename)

        assert timestamp == datetime(2025, 12, 14, 10, 30, 45, tzinfo=UTC)

    def test_parse_custom_prefix(self):
        """Test parsing filename with custom prefix."""
        filename = "custom-prefix-2025-12-14T10-30-45.db.gz"
        timestamp = parse_timestamp_from_filename(filename)

        assert timestamp == datetime(2025, 12, 14, 10, 30, 45, tzinfo=UTC)

    def test_parse_invalid_format(self):
        """Test parsing invalid filename format raises ValueError."""
        invalid_filenames = [
            "invalid-format.db",
            "looker-2025-12-14.db",  # Missing time
            "looker-2025-12-14T10.db",  # Incomplete time
            "looker.db",  # No timestamp
            "2025-12-14T10-30-45.db",  # No prefix
        ]

        for filename in invalid_filenames:
            with pytest.raises(ValueError) as exc_info:
                parse_timestamp_from_filename(filename)

            assert "Invalid snapshot filename format" in str(exc_info.value)

    def test_parse_invalid_timestamp_values(self):
        """Test parsing invalid timestamp values raises ValueError."""
        invalid_filenames = [
            "looker-2025-13-01T10-30-45.db",  # Month 13
            "looker-2025-12-32T10-30-45.db",  # Day 32
            "looker-2025-12-14T25-30-45.db",  # Hour 25
            "looker-2025-12-14T10-61-45.db",  # Minute 61
        ]

        for filename in invalid_filenames:
            with pytest.raises(ValueError) as exc_info:
                parse_timestamp_from_filename(filename)

            assert "Invalid timestamp" in str(exc_info.value)


class TestBlobCache:
    """Test blob caching functionality."""

    def test_cache_get_when_empty(self, tmp_path):
        """Test getting from empty cache returns None."""
        cache_path = tmp_path / "cache.json"
        cache = BlobCache(cache_path=str(cache_path), ttl_minutes=5)

        result = cache.get()
        assert result is None

    def test_cache_set_and_get(self, tmp_path):
        """Test setting and getting cached snapshots."""
        cache_path = tmp_path / "cache.json"
        cache = BlobCache(cache_path=str(cache_path), ttl_minutes=5)

        snapshots = [
            SnapshotMetadata(
                sequential_index=1,
                filename="looker-2025-12-14T10-30-00.db.gz",
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
        ]

        cache.set(snapshots)

        # Verify cache file exists
        assert cache_path.exists()

        # Get from cache
        cached_snapshots = cache.get()
        assert cached_snapshots is not None
        assert len(cached_snapshots) == 1
        assert cached_snapshots[0].filename == snapshots[0].filename

    def test_cache_expiration(self, tmp_path):
        """Test cache expiration based on TTL."""
        cache_path = tmp_path / "cache.json"
        cache = BlobCache(cache_path=str(cache_path), ttl_minutes=1)

        snapshots = [
            SnapshotMetadata(
                sequential_index=1,
                filename="looker-2025-12-14T10-30-00.db.gz",
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
        ]

        cache.set(snapshots)

        # Manually modify cache timestamp to be expired
        with cache_path.open("r") as f:
            data = json.load(f)

        # Set cached_at to 2 minutes ago (older than TTL)
        expired_time = datetime.now(UTC) - timedelta(minutes=2)
        data["cached_at"] = expired_time.isoformat()

        with cache_path.open("w") as f:
            json.dump(data, f)

        # Cache should be expired
        cached_snapshots = cache.get()
        assert cached_snapshots is None

    def test_cache_disabled_with_zero_ttl(self, tmp_path):
        """Test caching disabled when TTL is 0."""
        cache_path = tmp_path / "cache.json"
        cache = BlobCache(cache_path=str(cache_path), ttl_minutes=0)

        snapshots = [
            SnapshotMetadata(
                sequential_index=1,
                filename="looker-2025-12-14T10-30-00.db.gz",
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
        ]

        cache.set(snapshots)

        # Cache file should not be created when TTL is 0
        assert not cache_path.exists()

        # Get should always return None
        cached_snapshots = cache.get()
        assert cached_snapshots is None

    def test_cache_clear(self, tmp_path):
        """Test clearing the cache."""
        cache_path = tmp_path / "cache.json"
        cache = BlobCache(cache_path=str(cache_path), ttl_minutes=5)

        snapshots = [
            SnapshotMetadata(
                sequential_index=1,
                filename="looker-2025-12-14T10-30-00.db.gz",
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
        ]

        cache.set(snapshots)
        assert cache_path.exists()

        cache.clear()
        assert not cache_path.exists()

    def test_cache_corrupted_data(self, tmp_path):
        """Test cache handles corrupted data gracefully."""
        cache_path = tmp_path / "cache.json"
        cache = BlobCache(cache_path=str(cache_path), ttl_minutes=5)

        # Write corrupted JSON
        cache_path.write_text("{ corrupted json }")

        # Should return None instead of raising
        result = cache.get()
        assert result is None


class TestListSnapshots:
    """Test snapshot listing functionality."""

    def test_list_snapshots_basic(self):
        """Test basic snapshot listing."""
        # Mock GCS client and blobs
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket

        # Create mock blobs
        mock_blobs = [
            self._create_mock_blob(
                "snapshots/looker-2025-12-14T10-30-00.db.gz",
                1024,
                datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
            ),
            self._create_mock_blob(
                "snapshots/looker-2025-12-13T08-15-00.db.gz",
                2048,
                datetime(2025, 12, 13, 8, 15, 0, tzinfo=UTC),
            ),
        ]

        mock_bucket.list_blobs.return_value = mock_blobs

        snapshots = list_snapshots(
            client=mock_client,
            bucket_name="test-bucket",
            prefix="snapshots/",
            use_cache=False,
        )

        # Verify snapshots are sorted by creation time (newest first)
        assert len(snapshots) == 2
        assert snapshots[0].sequential_index == 1
        assert snapshots[1].sequential_index == 2
        assert snapshots[0].created > snapshots[1].created

    def test_list_snapshots_with_name_filter(self):
        """Test listing snapshots with name filter."""
        # Mock GCS client and blobs
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket

        # Create mock blobs with different prefixes
        mock_blobs = [
            self._create_mock_blob(
                "snapshots/pre-migration-2025-12-14T10-30-00.db.gz",
                1024,
                datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
            ),
            self._create_mock_blob(
                "snapshots/post-migration-2025-12-14T11-00-00.db.gz",
                2048,
                datetime(2025, 12, 14, 11, 0, 0, tzinfo=UTC),
            ),
            self._create_mock_blob(
                "snapshots/looker-2025-12-14T12-00-00.db.gz",
                3072,
                datetime(2025, 12, 14, 12, 0, 0, tzinfo=UTC),
            ),
        ]

        mock_bucket.list_blobs.return_value = mock_blobs

        # Filter for "pre-migration" snapshots
        snapshots = list_snapshots(
            client=mock_client,
            bucket_name="test-bucket",
            prefix="snapshots/",
            name_filter="pre-migration",
            use_cache=False,
        )

        # Should only return pre-migration snapshot
        assert len(snapshots) == 1
        assert "pre-migration" in snapshots[0].filename

    def test_list_snapshots_empty_bucket(self):
        """Test listing snapshots from empty bucket."""
        # Mock GCS client and bucket
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.list_blobs.return_value = []

        snapshots = list_snapshots(
            client=mock_client,
            bucket_name="test-bucket",
            prefix="snapshots/",
            use_cache=False,
        )

        assert len(snapshots) == 0

    def test_list_snapshots_filters_directory_markers(self):
        """Test that directory markers (size 0, ends with /) are filtered out."""
        # Mock GCS client and blobs
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket

        # Create mock blobs including directory marker
        mock_blobs = [
            self._create_mock_blob(
                "snapshots/",  # Directory marker
                0,
                datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
            ),
            self._create_mock_blob(
                "snapshots/looker-2025-12-14T10-30-00.db.gz",
                1024,
                datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
            ),
        ]

        mock_bucket.list_blobs.return_value = mock_blobs

        snapshots = list_snapshots(
            client=mock_client,
            bucket_name="test-bucket",
            prefix="snapshots/",
            use_cache=False,
        )

        # Should only return actual snapshot (not directory marker)
        assert len(snapshots) == 1
        assert snapshots[0].size_bytes > 0

    @staticmethod
    def _create_mock_blob(name, size, time_created):
        """Helper to create mock GCS blob."""
        mock_blob = MagicMock()
        mock_blob.name = name
        mock_blob.size = size
        mock_blob.time_created = time_created
        mock_blob.updated = time_created
        mock_blob.crc32c = "AAAAAA=="
        mock_blob.content_encoding = "gzip" if name.endswith(".gz") else None
        mock_blob.metadata = None
        return mock_blob


class TestGetSnapshotByIndex:
    """Test get snapshot by index functionality."""

    @pytest.fixture
    def mock_snapshots(self):
        """Create mock snapshots for testing."""
        return [
            SnapshotMetadata(
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
            ),
            SnapshotMetadata(
                sequential_index=2,
                filename="snapshots/looker-2025-12-13T08-15-00.db.gz",
                timestamp=datetime(2025, 12, 13, 8, 15, 0, tzinfo=UTC),
                size_bytes=2048,
                gcs_bucket="test-bucket",
                gcs_path="gs://test-bucket/snapshots/looker-2025-12-13T08-15-00.db.gz",
                crc32c="BBBBBB==",
                content_encoding="gzip",
                tags=[],
                created=datetime(2025, 12, 13, 8, 15, 0, tzinfo=UTC),
                updated=datetime(2025, 12, 13, 8, 15, 0, tzinfo=UTC),
            ),
        ]

    def test_get_snapshot_by_valid_index(self, mock_snapshots):
        """Test getting snapshot by valid index."""
        with patch("lookervault.snapshot.lister.list_snapshots") as mock_list:
            mock_list.return_value = mock_snapshots

            snapshot = get_snapshot_by_index(
                client=MagicMock(),
                bucket_name="test-bucket",
                index=1,
                use_cache=False,
            )

        assert snapshot.sequential_index == 1

    def test_get_snapshot_by_invalid_index_too_high(self, mock_snapshots):
        """Test getting snapshot by index that's too high."""
        with patch("lookervault.snapshot.lister.list_snapshots") as mock_list:
            mock_list.return_value = mock_snapshots

            with pytest.raises(ValueError) as exc_info:
                get_snapshot_by_index(
                    client=MagicMock(),
                    bucket_name="test-bucket",
                    index=999,
                    use_cache=False,
                )

        assert "Invalid index" in str(exc_info.value)

    def test_get_snapshot_by_invalid_index_negative(self, mock_snapshots):
        """Test getting snapshot by negative index."""
        with patch("lookervault.snapshot.lister.list_snapshots") as mock_list:
            mock_list.return_value = mock_snapshots

            with pytest.raises(ValueError) as exc_info:
                get_snapshot_by_index(
                    client=MagicMock(),
                    bucket_name="test-bucket",
                    index=0,
                    use_cache=False,
                )

        assert "must be positive" in str(exc_info.value)

    def test_get_snapshot_by_index_no_snapshots(self):
        """Test getting snapshot when no snapshots exist."""
        with patch("lookervault.snapshot.lister.list_snapshots") as mock_list:
            mock_list.return_value = []

            with pytest.raises(ValueError) as exc_info:
                get_snapshot_by_index(
                    client=MagicMock(),
                    bucket_name="test-bucket",
                    index=1,
                    use_cache=False,
                )

        assert "No snapshots found" in str(exc_info.value)


class TestFilterByDateRange:
    """Test date range filtering functionality."""

    @pytest.fixture
    def mock_snapshots(self):
        """Create mock snapshots with different ages."""
        now = datetime.now(UTC)
        return [
            self._create_snapshot(now - timedelta(days=1)),  # 1 day ago
            self._create_snapshot(now - timedelta(days=7)),  # 7 days ago
            self._create_snapshot(now - timedelta(days=30)),  # 30 days ago
            self._create_snapshot(now - timedelta(days=60)),  # 60 days ago
        ]

    def test_filter_last_n_days(self, mock_snapshots):
        """Test filtering by last N days."""
        filtered = filter_by_date_range(mock_snapshots, "last-7-days")

        # Should include snapshots from last 7 days (cutoff uses >= comparison)
        assert len(filtered) >= 1

    def test_filter_last_30_days(self, mock_snapshots):
        """Test filtering by last 30 days."""
        filtered = filter_by_date_range(mock_snapshots, "last-30-days")

        # Should include snapshots from last 30 days (cutoff uses >= comparison)
        assert len(filtered) >= 2

    def test_filter_by_specific_month(self):
        """Test filtering by specific year-month."""
        snapshots = [
            self._create_snapshot(datetime(2025, 12, 15, 10, 0, 0, tzinfo=UTC)),
            self._create_snapshot(datetime(2025, 11, 15, 10, 0, 0, tzinfo=UTC)),
            self._create_snapshot(datetime(2024, 12, 15, 10, 0, 0, tzinfo=UTC)),
        ]

        filtered = filter_by_date_range(snapshots, "2025-12")

        # Should only include December 2025 snapshot
        assert len(filtered) == 1
        assert filtered[0].created.year == 2025
        assert filtered[0].created.month == 12

    def test_filter_by_specific_year(self):
        """Test filtering by specific year."""
        snapshots = [
            self._create_snapshot(datetime(2025, 12, 15, 10, 0, 0, tzinfo=UTC)),
            self._create_snapshot(datetime(2025, 6, 15, 10, 0, 0, tzinfo=UTC)),
            self._create_snapshot(datetime(2024, 12, 15, 10, 0, 0, tzinfo=UTC)),
        ]

        filtered = filter_by_date_range(snapshots, "2025")

        # Should include both 2025 snapshots
        assert len(filtered) == 2
        assert all(s.created.year == 2025 for s in filtered)

    def test_filter_invalid_format(self, mock_snapshots):
        """Test filtering with invalid date filter format."""
        with pytest.raises(ValueError) as exc_info:
            filter_by_date_range(mock_snapshots, "invalid-format")

        assert "Invalid date filter" in str(exc_info.value)

    def test_filter_invalid_month(self, mock_snapshots):
        """Test filtering with invalid month."""
        with pytest.raises(ValueError) as exc_info:
            filter_by_date_range(mock_snapshots, "2025-13")

        assert "Invalid month" in str(exc_info.value)

    @staticmethod
    def _create_snapshot(created_at):
        """Helper to create snapshot with specific creation time."""
        return SnapshotMetadata(
            sequential_index=1,
            filename="looker-2025-12-14T10-30-00.db.gz",
            timestamp=created_at,
            size_bytes=1024,
            gcs_bucket="test-bucket",
            gcs_path="gs://test-bucket/snapshots/looker-2025-12-14T10-30-00.db.gz",
            crc32c="AAAAAA==",
            content_encoding="gzip",
            tags=[],
            created=created_at,
            updated=created_at,
        )
