"""Unit tests for snapshot downloader module."""

import base64
import gzip
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import google_crc32c
import pytest
from google.cloud import exceptions as gcs_exceptions

from lookervault.snapshot.downloader import (
    decompress_file,
    download_snapshot,
    verify_download_integrity,
)
from lookervault.snapshot.models import SnapshotMetadata


class TestVerifyDownloadIntegrity:
    """Test download integrity verification."""

    def test_verify_matching_checksum(self, tmp_path):
        """Test verification passes for matching checksum."""
        test_file = tmp_path / "downloaded.db"
        test_content = b"Downloaded file content"
        test_file.write_bytes(test_content)

        # Compute expected checksum
        crc32c_hash = google_crc32c.Checksum()
        crc32c_hash.update(test_content)
        expected_crc32c = base64.b64encode(crc32c_hash.digest()).decode("utf-8")

        # Should not raise
        result = verify_download_integrity(test_file, expected_crc32c)
        assert result is True

    def test_verify_mismatched_checksum(self, tmp_path):
        """Test verification fails for mismatched checksum."""
        test_file = tmp_path / "downloaded.db"
        test_file.write_bytes(b"Downloaded file content")

        wrong_checksum = "WRONG_CHECKSUM_HERE=="

        with pytest.raises(ValueError) as exc_info:
            verify_download_integrity(test_file, wrong_checksum)

        error_msg = str(exc_info.value)
        assert "checksum mismatch" in error_msg.lower()
        assert "Expected:" in error_msg
        assert "Actual:" in error_msg

    def test_verify_nonexistent_file(self, tmp_path):
        """Test verification fails for nonexistent file."""
        nonexistent_file = tmp_path / "nonexistent.db"

        with pytest.raises(FileNotFoundError) as exc_info:
            verify_download_integrity(nonexistent_file, "AAAAAA==")

        assert "Downloaded file not found" in str(exc_info.value)

    def test_verify_empty_file(self, tmp_path):
        """Test verification for empty file."""
        empty_file = tmp_path / "empty.db"
        empty_file.write_bytes(b"")

        # Compute checksum for empty file
        crc32c_hash = google_crc32c.Checksum()
        crc32c_hash.update(b"")
        expected_crc32c = base64.b64encode(crc32c_hash.digest()).decode("utf-8")

        result = verify_download_integrity(empty_file, expected_crc32c)
        assert result is True


class TestDecompressFile:
    """Test file decompression functionality."""

    def test_decompress_gzipped_file(self, tmp_path):
        """Test decompression of gzipped file."""
        original_content = b"Test content for decompression" * 100
        source_file = tmp_path / "compressed.db.gz"
        dest_file = tmp_path / "decompressed.db"

        # Create gzipped file
        with gzip.open(source_file, "wb") as f:
            f.write(original_content)

        decompressed_size = decompress_file(source_file, dest_file, show_progress=False)

        # Verify decompressed file exists
        assert dest_file.exists()

        # Verify size
        assert decompressed_size == len(original_content)

        # Verify content
        assert dest_file.read_bytes() == original_content

    def test_decompress_uncompressed_file(self, tmp_path):
        """Test decompression of uncompressed file (should copy)."""
        original_content = b"Not compressed content"
        source_file = tmp_path / "uncompressed.db"
        dest_file = tmp_path / "output.db"

        source_file.write_bytes(original_content)

        decompressed_size = decompress_file(source_file, dest_file, show_progress=False)

        # Verify file was copied
        assert dest_file.exists()
        assert dest_file.read_bytes() == original_content
        assert decompressed_size == len(original_content)

    def test_decompress_nonexistent_source(self, tmp_path):
        """Test decompression fails for nonexistent source file."""
        source_file = tmp_path / "nonexistent.db.gz"
        dest_file = tmp_path / "output.db"

        with pytest.raises(FileNotFoundError) as exc_info:
            decompress_file(source_file, dest_file, show_progress=False)

        assert "Source file not found" in str(exc_info.value)

    def test_decompress_cleanup_on_error(self, tmp_path):
        """Test that partial decompressed file is cleaned up on error."""
        source_file = tmp_path / "corrupted.db.gz"
        dest_file = tmp_path / "output.db"

        # Create file with gzip magic number but corrupted content
        source_file.write_bytes(b"\x1f\x8b" + b"corrupted")

        with pytest.raises(OSError) as exc_info:
            decompress_file(source_file, dest_file, show_progress=False)

        assert "Decompression failed" in str(exc_info.value)

        # Verify partial file was cleaned up
        assert not dest_file.exists()

    def test_decompress_with_progress(self, tmp_path):
        """Test decompression with progress bar (smoke test)."""
        original_content = b"Test content" * 100
        source_file = tmp_path / "compressed.db.gz"
        dest_file = tmp_path / "decompressed.db"

        with gzip.open(source_file, "wb") as f:
            f.write(original_content)

        # Should not crash with progress enabled
        decompressed_size = decompress_file(source_file, dest_file, show_progress=True)

        assert decompressed_size == len(original_content)
        assert dest_file.exists()


class TestDownloadSnapshot:
    """Test snapshot download functionality."""

    @pytest.fixture
    def mock_snapshot(self):
        """Create mock snapshot metadata."""
        return SnapshotMetadata(
            sequential_index=1,
            filename="snapshots/looker-2025-12-14T10-30-00.db.gz",
            timestamp=datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
            size_bytes=1024 * 1024,  # 1 MB
            gcs_bucket="test-bucket",
            gcs_path="gs://test-bucket/snapshots/looker-2025-12-14T10-30-00.db.gz",
            crc32c="AAAAAA==",
            content_encoding="gzip",
            tags=[],
            created=datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
            updated=datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC),
        )

    def test_download_compressed_snapshot(self, tmp_path, mock_snapshot):
        """Test downloading compressed snapshot."""
        output_path = tmp_path / "downloaded.db"
        original_content = b"Database content" * 100

        # Create compressed content
        compressed_content = gzip.compress(original_content)

        # Mock GCS client and blob
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        mock_blob.exists.return_value = True
        mock_blob.size = len(compressed_content)

        # Mock chunked download
        def mock_download_as_bytes(start, end, retry):
            return compressed_content[start : end + 1]

        mock_blob.download_as_bytes.side_effect = mock_download_as_bytes

        # Mock checksum verification
        with patch("lookervault.snapshot.downloader.verify_download_integrity") as mock_verify:
            mock_verify.return_value = True

            result = download_snapshot(
                client=mock_client,
                snapshot=mock_snapshot,
                output_path=output_path,
                verify_checksum=True,
                show_progress=False,
            )

        # Verify download succeeded
        assert result["filename"] == str(output_path)
        assert result["checksum_verified"] is True
        assert output_path.exists()

        # Verify decompressed content
        assert output_path.read_bytes() == original_content

    def test_download_uncompressed_snapshot(self, tmp_path, mock_snapshot):
        """Test downloading uncompressed snapshot."""
        # Modify mock to be uncompressed
        mock_snapshot.content_encoding = None
        mock_snapshot.filename = "snapshots/looker-2025-12-14T10-30-00.db"

        output_path = tmp_path / "downloaded.db"
        test_content = b"Database content" * 100

        # Mock GCS client and blob
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        mock_blob.exists.return_value = True
        mock_blob.size = len(test_content)

        # Mock chunked download
        def mock_download_as_bytes(start, end, retry):
            return test_content[start : end + 1]

        mock_blob.download_as_bytes.side_effect = mock_download_as_bytes

        # Mock checksum verification
        with patch("lookervault.snapshot.downloader.verify_download_integrity") as mock_verify:
            mock_verify.return_value = True

            result = download_snapshot(
                client=mock_client,
                snapshot=mock_snapshot,
                output_path=output_path,
                verify_checksum=True,
                show_progress=False,
            )

        # Verify download succeeded
        assert result["filename"] == str(output_path)
        assert output_path.exists()
        assert output_path.read_bytes() == test_content

    def test_download_snapshot_not_found(self, tmp_path, mock_snapshot):
        """Test download fails when snapshot doesn't exist in GCS."""
        output_path = tmp_path / "downloaded.db"

        # Mock GCS client and blob
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        mock_blob.exists.return_value = False

        with pytest.raises(RuntimeError) as exc_info:
            download_snapshot(
                client=mock_client,
                snapshot=mock_snapshot,
                output_path=output_path,
                verify_checksum=True,
                show_progress=False,
            )

        assert "Snapshot not found" in str(exc_info.value)

    def test_download_snapshot_permission_denied(self, tmp_path, mock_snapshot):
        """Test download fails when permission denied."""
        output_path = tmp_path / "downloaded.db"

        # Mock GCS client and blob
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        mock_blob.exists.side_effect = gcs_exceptions.Forbidden("Permission denied")

        with pytest.raises(RuntimeError) as exc_info:
            download_snapshot(
                client=mock_client,
                snapshot=mock_snapshot,
                output_path=output_path,
                verify_checksum=True,
                show_progress=False,
            )

        assert "permission" in str(exc_info.value).lower()

    def test_download_snapshot_network_error(self, tmp_path, mock_snapshot):
        """Test download handles network errors."""
        output_path = tmp_path / "downloaded.db"

        # Mock GCS client and blob
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        mock_blob.exists.return_value = True
        mock_blob.size = 1024
        mock_blob.download_as_bytes.side_effect = ConnectionError("Network timeout")

        with pytest.raises(OSError) as exc_info:
            download_snapshot(
                client=mock_client,
                snapshot=mock_snapshot,
                output_path=output_path,
                verify_checksum=True,
                show_progress=False,
            )

        assert "network error" in str(exc_info.value).lower()

    def test_download_snapshot_checksum_verification_failure(self, tmp_path, mock_snapshot):
        """Test download fails when checksum verification fails."""
        output_path = tmp_path / "downloaded.db"
        test_content = b"Database content"

        # Mock GCS client and blob
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        mock_blob.exists.return_value = True
        mock_blob.size = len(test_content)

        # Mock chunked download
        def mock_download_as_bytes(start, end, retry):
            return test_content[start : end + 1]

        mock_blob.download_as_bytes.side_effect = mock_download_as_bytes

        # Mock checksum verification to fail
        with patch("lookervault.snapshot.downloader.verify_download_integrity") as mock_verify:
            mock_verify.side_effect = ValueError("Checksum mismatch")

            with pytest.raises(ValueError) as exc_info:
                download_snapshot(
                    client=mock_client,
                    snapshot=mock_snapshot,
                    output_path=output_path,
                    verify_checksum=True,
                    show_progress=False,
                )

        assert "checksum mismatch" in str(exc_info.value).lower()

    def test_download_snapshot_without_checksum_verification(self, tmp_path, mock_snapshot):
        """Test download without checksum verification."""
        mock_snapshot.content_encoding = None
        output_path = tmp_path / "downloaded.db"
        test_content = b"Database content"

        # Mock GCS client and blob
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        mock_blob.exists.return_value = True
        mock_blob.size = len(test_content)

        # Mock chunked download
        def mock_download_as_bytes(start, end, retry):
            return test_content[start : end + 1]

        mock_blob.download_as_bytes.side_effect = mock_download_as_bytes

        result = download_snapshot(
            client=mock_client,
            snapshot=mock_snapshot,
            output_path=output_path,
            verify_checksum=False,
            show_progress=False,
        )

        # Verify download succeeded without verification
        assert result["checksum_verified"] is False
        assert output_path.exists()

    def test_download_snapshot_rate_limit_error(self, tmp_path, mock_snapshot):
        """Test download handles rate limit errors."""
        output_path = tmp_path / "downloaded.db"

        # Mock GCS client and blob
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        mock_blob.exists.return_value = True
        mock_blob.size = 1024
        mock_blob.download_as_bytes.side_effect = gcs_exceptions.TooManyRequests(
            "Rate limit exceeded"
        )

        with pytest.raises(OSError) as exc_info:
            download_snapshot(
                client=mock_client,
                snapshot=mock_snapshot,
                output_path=output_path,
                verify_checksum=True,
                show_progress=False,
            )

        assert "rate limit" in str(exc_info.value).lower()
