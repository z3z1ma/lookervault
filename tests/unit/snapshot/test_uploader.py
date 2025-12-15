"""Unit tests for snapshot uploader module."""

import base64
import gzip
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import google_crc32c
import pytest
from google.cloud import exceptions as gcs_exceptions

from lookervault.snapshot.models import GCSStorageProvider
from lookervault.snapshot.uploader import (
    compress_file,
    compute_crc32c,
    generate_snapshot_filename,
    upload_snapshot,
)


class TestGenerateSnapshotFilename:
    """Test snapshot filename generation."""

    def test_filename_with_compression(self):
        """Test filename generation with compression enabled."""
        filename = generate_snapshot_filename("looker", compress=True)

        # Should match format: looker-YYYY-MM-DDTHH-MM-SS.db.gz
        assert filename.startswith("looker-")
        assert filename.endswith(".db.gz")
        assert "T" in filename  # Timestamp separator

        # Verify timestamp part is valid
        timestamp_part = filename.replace("looker-", "").replace(".db.gz", "")
        datetime.strptime(timestamp_part, "%Y-%m-%dT%H-%M-%S")

    def test_filename_without_compression(self):
        """Test filename generation without compression."""
        filename = generate_snapshot_filename("looker", compress=False)

        assert filename.startswith("looker-")
        assert filename.endswith(".db")
        assert not filename.endswith(".gz")

    def test_filename_with_custom_prefix(self):
        """Test filename generation with custom prefix."""
        filename = generate_snapshot_filename("custom-prefix", compress=True)

        assert filename.startswith("custom-prefix-")
        assert filename.endswith(".db.gz")

    def test_filename_timestamp_precision(self):
        """Test that filename timestamp has second precision."""
        filename1 = generate_snapshot_filename("looker", compress=True)
        generate_snapshot_filename("looker", compress=True)

        # Filenames generated within same second might be identical
        # But should always have valid timestamp format
        assert "-" in filename1.split("looker-")[1].split(".db")[0]


class TestComputeCRC32C:
    """Test CRC32C checksum computation."""

    def test_compute_crc32c_small_file(self, tmp_path):
        """Test CRC32C computation for small file."""
        test_file = tmp_path / "test.db"
        test_content = b"Hello, World!"
        test_file.write_bytes(test_content)

        checksum = compute_crc32c(test_file)

        # Verify checksum is base64-encoded
        assert isinstance(checksum, str)
        # Base64 strings are multiples of 4 in length
        assert len(checksum) % 4 == 0

        # Manually compute expected checksum
        expected_hash = google_crc32c.Checksum()
        expected_hash.update(test_content)
        expected_checksum = base64.b64encode(expected_hash.digest()).decode("utf-8")

        assert checksum == expected_checksum

    def test_compute_crc32c_large_file(self, tmp_path):
        """Test CRC32C computation for large file (multi-chunk)."""
        test_file = tmp_path / "large.db"
        # Create file larger than CHUNK_SIZE (8 MB)
        chunk_size = 8 * 1024 * 1024
        test_content = b"x" * (chunk_size + 1000)
        test_file.write_bytes(test_content)

        checksum = compute_crc32c(test_file)

        # Verify checksum is valid
        assert isinstance(checksum, str)
        assert len(checksum) > 0

        # Manually verify
        expected_hash = google_crc32c.Checksum()
        expected_hash.update(test_content)
        expected_checksum = base64.b64encode(expected_hash.digest()).decode("utf-8")

        assert checksum == expected_checksum

    def test_compute_crc32c_nonexistent_file(self, tmp_path):
        """Test CRC32C computation for nonexistent file raises FileNotFoundError."""
        nonexistent_file = tmp_path / "nonexistent.db"

        with pytest.raises(FileNotFoundError) as exc_info:
            compute_crc32c(nonexistent_file)

        assert "File not found" in str(exc_info.value)

    def test_compute_crc32c_empty_file(self, tmp_path):
        """Test CRC32C computation for empty file."""
        empty_file = tmp_path / "empty.db"
        empty_file.write_bytes(b"")

        checksum = compute_crc32c(empty_file)

        # Empty file should have valid checksum
        assert isinstance(checksum, str)
        assert len(checksum) > 0


class TestCompressFile:
    """Test file compression functionality."""

    def test_compress_file_basic(self, tmp_path):
        """Test basic file compression."""
        source_file = tmp_path / "source.db"
        dest_file = tmp_path / "compressed.db.gz"
        test_content = b"Test content for compression" * 1000
        source_file.write_bytes(test_content)

        compressed_size = compress_file(
            source_file, dest_file, compression_level=6, show_progress=False
        )

        # Verify compressed file exists
        assert dest_file.exists()

        # Verify compressed size is returned
        assert compressed_size == dest_file.stat().st_size

        # Verify compressed size is smaller than original
        assert compressed_size < source_file.stat().st_size

        # Verify decompressed content matches original
        with gzip.open(dest_file, "rb") as f:
            decompressed = f.read()
        assert decompressed == test_content

    def test_compress_file_compression_levels(self, tmp_path):
        """Test different compression levels."""
        source_file = tmp_path / "source.db"
        test_content = b"Test content for compression" * 1000
        source_file.write_bytes(test_content)

        sizes = {}
        for level in [1, 6, 9]:
            dest_file = tmp_path / f"compressed_level_{level}.db.gz"
            compressed_size = compress_file(
                source_file, dest_file, compression_level=level, show_progress=False
            )
            sizes[level] = compressed_size

        # Level 9 should produce smallest file (best compression)
        assert sizes[9] <= sizes[6] <= sizes[1]

    def test_compress_file_nonexistent_source(self, tmp_path):
        """Test compression fails for nonexistent source file."""
        source_file = tmp_path / "nonexistent.db"
        dest_file = tmp_path / "compressed.db.gz"

        with pytest.raises(FileNotFoundError) as exc_info:
            compress_file(source_file, dest_file, show_progress=False)

        assert "Source file not found" in str(exc_info.value)

    def test_compress_file_invalid_compression_level(self, tmp_path):
        """Test compression fails for invalid compression level."""
        source_file = tmp_path / "source.db"
        dest_file = tmp_path / "compressed.db.gz"
        source_file.write_bytes(b"test")

        with pytest.raises(ValueError) as exc_info:
            compress_file(source_file, dest_file, compression_level=0, show_progress=False)

        assert "Compression level must be 1-9" in str(exc_info.value)

    def test_compress_file_cleanup_on_error(self, tmp_path):
        """Test that partial compressed file is cleaned up on error."""
        source_file = tmp_path / "source.db"
        dest_file = tmp_path / "compressed.db.gz"
        source_file.write_bytes(b"test")

        # Mock gzip.open to raise error after partial write
        with patch("gzip.open", side_effect=OSError("Simulated compression error")):
            with pytest.raises(OSError) as exc_info:
                compress_file(source_file, dest_file, show_progress=False)

            assert "Compression failed" in str(exc_info.value)

        # Verify partial file was cleaned up
        assert not dest_file.exists()

    def test_compress_file_with_progress(self, tmp_path):
        """Test compression with progress bar enabled (smoke test)."""
        source_file = tmp_path / "source.db"
        dest_file = tmp_path / "compressed.db.gz"
        test_content = b"Test content" * 100
        source_file.write_bytes(test_content)

        # Should not crash with progress enabled
        compressed_size = compress_file(
            source_file, dest_file, compression_level=6, show_progress=True
        )

        assert compressed_size > 0
        assert dest_file.exists()


class TestUploadSnapshot:
    """Test snapshot upload functionality."""

    @patch("lookervault.snapshot.uploader.create_storage_client")
    @patch("lookervault.snapshot.uploader.validate_bucket_access")
    def test_upload_snapshot_dry_run(self, mock_validate_bucket, mock_create_client, tmp_path):
        """Test upload snapshot in dry run mode."""
        source_file = tmp_path / "looker.db"
        source_file.write_bytes(b"test database content")

        provider_config = GCSStorageProvider(
            bucket_name="test-bucket",
            region="us-central1",
            compression_enabled=False,
        )

        metadata = upload_snapshot(
            provider_config=provider_config,
            source_path=source_file,
            dry_run=True,
            show_progress=False,
        )

        # Verify client was created and bucket was validated
        mock_create_client.assert_called_once()
        mock_validate_bucket.assert_called_once()

        # Verify metadata is returned
        assert metadata.filename.startswith("looker-")
        assert metadata.size_bytes == source_file.stat().st_size
        assert metadata.gcs_bucket == "test-bucket"

    @patch("lookervault.snapshot.uploader.create_storage_client")
    @patch("lookervault.snapshot.uploader.validate_bucket_access")
    def test_upload_snapshot_nonexistent_file(
        self, mock_validate_bucket, mock_create_client, tmp_path
    ):
        """Test upload fails for nonexistent source file."""
        source_file = tmp_path / "nonexistent.db"

        provider_config = GCSStorageProvider(
            bucket_name="test-bucket",
            region="us-central1",
        )

        with pytest.raises(FileNotFoundError) as exc_info:
            upload_snapshot(
                provider_config=provider_config,
                source_path=source_file,
                dry_run=False,
                show_progress=False,
            )

        assert "Source file not found" in str(exc_info.value)

    @patch("lookervault.snapshot.uploader.create_storage_client")
    @patch("lookervault.snapshot.uploader.validate_bucket_access")
    @patch("lookervault.snapshot.uploader.compress_file")
    def test_upload_snapshot_with_compression(
        self, mock_compress, mock_validate_bucket, mock_create_client, tmp_path
    ):
        """Test upload snapshot with compression enabled."""
        source_file = tmp_path / "looker.db"
        source_file.write_bytes(b"test database content" * 1000)

        compressed_file = tmp_path / "looker.db.gz.tmp"
        compressed_file.write_bytes(b"compressed content")

        # Mock GCS client and blob
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_blob.size = 100
        mock_blob.crc32c = "AAAAAA=="
        mock_blob.time_created = datetime.now(UTC)
        mock_blob.updated = datetime.now(UTC)

        mock_create_client.return_value = mock_client
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        # Mock compression
        mock_compress.return_value = compressed_file.stat().st_size

        provider_config = GCSStorageProvider(
            bucket_name="test-bucket",
            region="us-central1",
            compression_enabled=True,
            compression_level=6,
        )

        # Mock compute_crc32c
        with patch("lookervault.snapshot.uploader.compute_crc32c") as mock_crc:
            mock_crc.return_value = "AAAAAA=="

            metadata = upload_snapshot(
                provider_config=provider_config,
                source_path=source_file,
                dry_run=False,
                show_progress=False,
            )

        # Verify compression was called
        mock_compress.assert_called_once()
        args, kwargs = mock_compress.call_args
        assert args[0] == source_file
        # Positional arguments, not keyword arguments
        assert args[2] == 6  # compression_level is 3rd argument

        # Verify metadata
        assert metadata.content_encoding == "gzip"

    @patch("lookervault.snapshot.uploader.create_storage_client")
    @patch("lookervault.snapshot.uploader.validate_bucket_access")
    def test_upload_snapshot_checksum_mismatch(
        self, mock_validate_bucket, mock_create_client, tmp_path
    ):
        """Test upload fails on checksum mismatch."""
        source_file = tmp_path / "looker.db"
        source_file.write_bytes(b"test content")

        # Mock GCS client and blob
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_blob.size = 100
        mock_blob.crc32c = "WRONG_CHECKSUM=="  # Mismatch
        mock_blob.time_created = datetime.now(UTC)
        mock_blob.updated = datetime.now(UTC)

        mock_create_client.return_value = mock_client
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        provider_config = GCSStorageProvider(
            bucket_name="test-bucket",
            region="us-central1",
            compression_enabled=False,
        )

        with patch("lookervault.snapshot.uploader.compute_crc32c") as mock_crc:
            mock_crc.return_value = "CORRECT_CHECKSUM=="

            with pytest.raises(ValueError) as exc_info:
                upload_snapshot(
                    provider_config=provider_config,
                    source_path=source_file,
                    dry_run=False,
                    show_progress=False,
                )

        assert "checksum mismatch" in str(exc_info.value).lower()

    @patch("lookervault.snapshot.uploader.create_storage_client")
    @patch("lookervault.snapshot.uploader.validate_bucket_access")
    def test_upload_snapshot_rate_limit_error(
        self, mock_validate_bucket, mock_create_client, tmp_path
    ):
        """Test upload handles rate limit errors."""
        source_file = tmp_path / "looker.db"
        source_file.write_bytes(b"test content")

        # Mock GCS client to raise rate limit error
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_create_client.return_value = mock_client
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        # Mock upload to raise TooManyRequests
        mock_blob.upload_from_file.side_effect = gcs_exceptions.TooManyRequests("Rate limit")

        provider_config = GCSStorageProvider(
            bucket_name="test-bucket",
            region="us-central1",
            compression_enabled=False,
        )

        with patch("lookervault.snapshot.uploader.compute_crc32c") as mock_crc:
            mock_crc.return_value = "AAAAAA=="

            with pytest.raises(OSError) as exc_info:
                upload_snapshot(
                    provider_config=provider_config,
                    source_path=source_file,
                    dry_run=False,
                    show_progress=False,
                )

        assert "rate limit" in str(exc_info.value).lower()

    @patch("lookervault.snapshot.uploader.create_storage_client")
    @patch("lookervault.snapshot.uploader.validate_bucket_access")
    def test_upload_snapshot_permission_error(
        self, mock_validate_bucket, mock_create_client, tmp_path
    ):
        """Test upload handles permission errors."""
        source_file = tmp_path / "looker.db"
        source_file.write_bytes(b"test content")

        # Mock GCS client to raise permission error
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_create_client.return_value = mock_client
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        # Mock upload to raise Forbidden
        mock_blob.upload_from_file.side_effect = gcs_exceptions.Forbidden("Permission denied")

        provider_config = GCSStorageProvider(
            bucket_name="test-bucket",
            region="us-central1",
            compression_enabled=False,
        )

        with patch("lookervault.snapshot.uploader.compute_crc32c") as mock_crc:
            mock_crc.return_value = "AAAAAA=="

            with pytest.raises(RuntimeError) as exc_info:
                upload_snapshot(
                    provider_config=provider_config,
                    source_path=source_file,
                    dry_run=False,
                    show_progress=False,
                )

        assert "permission" in str(exc_info.value).lower()
