"""Snapshot upload functionality with compression and integrity verification."""

import gzip
import logging
from datetime import UTC, datetime
from pathlib import Path

import google_crc32c
from google.api_core import exceptions as api_exceptions
from google.api_core import retry
from google.cloud import exceptions as gcs_exceptions
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TransferSpeedColumn,
)
from tenacity import (
    retry as tenacity_retry,
)
from tenacity import (
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from lookervault.cli.rich_logging import console
from lookervault.constants import (
    CHUNK_SIZE_GCS,
    DEFAULT_COMPRESSION_LEVEL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_MAX_WAIT_SECONDS,
    GCS_TOTAL_TIMEOUT_SECONDS,
    GCS_UPLOAD_TIMEOUT_SECONDS,
)
from lookervault.snapshot.client import create_storage_client, validate_bucket_access
from lookervault.snapshot.models import GCSStorageProvider, SnapshotMetadata

logger = logging.getLogger(__name__)

# Chunk size for compression and upload (8 MB recommended by GCS)
CHUNK_SIZE = CHUNK_SIZE_GCS

# Production retry policy for GCS operations
PRODUCTION_RETRY = retry.Retry(
    initial=1.0,  # 1 second initial delay
    maximum=float(DEFAULT_RETRY_MAX_WAIT_SECONDS),  # Max 60 seconds between retries
    multiplier=2.0,  # Exponential backoff
    deadline=float(GCS_TOTAL_TIMEOUT_SECONDS),  # 10 minute total timeout
    predicate=retry.if_exception_type(
        Exception,  # Retry on any transient error
    ),
)


def generate_snapshot_filename(prefix: str, compress: bool) -> str:
    """
    Generate snapshot filename using UTC timestamp.

    Args:
        prefix: Filename prefix (e.g., "looker")
        compress: Whether compression is enabled (adds .gz extension)

    Returns:
        Filename in format: {prefix}-YYYY-MM-DDTHH-MM-SS.db[.gz]

    Examples:
        >>> generate_snapshot_filename("looker", True)
        'looker-2025-12-13T14-30-00.db.gz'
        >>> generate_snapshot_filename("looker", False)
        'looker-2025-12-13T14-30-00.db'
    """
    now = datetime.now(UTC)
    timestamp = now.strftime("%Y-%m-%dT%H-%M-%S")
    extension = ".db.gz" if compress else ".db"
    return f"{prefix}-{timestamp}{extension}"


def compute_crc32c(file_path: Path) -> str:
    """
    Compute CRC32C checksum for file integrity verification.

    Args:
        file_path: Path to file to checksum

    Returns:
        Base64-encoded CRC32C checksum (compatible with GCS)

    Raises:
        FileNotFoundError: If file doesn't exist
        IOError: If file cannot be read
    """
    import base64

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    crc32c_hash = google_crc32c.Checksum()

    with file_path.open("rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            crc32c_hash.update(chunk)

    # GCS expects base64-encoded checksum
    return base64.b64encode(crc32c_hash.digest()).decode("utf-8")


def compress_file(
    source_path: Path,
    dest_path: Path,
    compression_level: int = DEFAULT_COMPRESSION_LEVEL,
    show_progress: bool = True,
) -> int:
    """
    Compress file using gzip with progress tracking.

    Args:
        source_path: Path to source file
        dest_path: Path to compressed output file
        compression_level: Gzip compression level (1=fastest, 9=best)
        show_progress: Whether to show progress bar

    Returns:
        Size of compressed file in bytes

    Raises:
        FileNotFoundError: If source file doesn't exist
        IOError: If compression fails
        ValueError: If compression level is invalid
    """
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    if not 1 <= compression_level <= 9:
        raise ValueError(f"Compression level must be 1-9, got {compression_level}")

    source_size = source_path.stat().st_size
    compressed_size = 0

    # Create progress bar for compression
    if show_progress:
        progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeElapsedColumn(),
            console=console,
        )
        task_id: TaskID | None = None
    else:
        progress = None
        task_id = None

    try:
        if progress:
            progress.start()
            task_id = progress.add_task(f"Compressing {source_path.name}...", total=source_size)

        with source_path.open("rb") as f_in:
            with gzip.open(dest_path, "wb", compresslevel=compression_level) as f_out:
                while chunk := f_in.read(CHUNK_SIZE):
                    f_out.write(chunk)
                    compressed_size += len(chunk)
                    if progress and task_id is not None:
                        progress.update(task_id, advance=len(chunk))

        if progress:
            progress.stop()

        # Get actual compressed size
        actual_compressed_size = dest_path.stat().st_size

        logger.info(
            f"Compressed {source_path.name}: {source_size:,} → {actual_compressed_size:,} bytes "
            f"({(1 - actual_compressed_size / source_size) * 100:.1f}% reduction)"
        )

        return actual_compressed_size

    except Exception as e:
        # Clean up partial compressed file on error
        if dest_path.exists():
            dest_path.unlink()
        raise OSError(f"Compression failed: {e}") from e


@tenacity_retry(
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    stop=stop_after_attempt(DEFAULT_MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=1, max=DEFAULT_RETRY_MAX_WAIT_SECONDS),
    reraise=True,
)
def upload_snapshot(
    provider_config: GCSStorageProvider,
    source_path: Path,
    dry_run: bool = False,
    show_progress: bool = True,
) -> SnapshotMetadata:
    """
    Upload snapshot to GCS with compression and integrity verification.

    This function handles the complete upload workflow:
    1. Compress source file (if compression enabled)
    2. Compute CRC32C checksum
    3. Upload to GCS with resumable upload (automatic for files >8MB)
    4. Verify server-side checksum matches
    5. Return snapshot metadata

    Args:
        provider_config: GCS storage provider configuration
        source_path: Path to local database file to upload
        dry_run: If True, validate configuration but skip actual upload
        show_progress: Whether to show progress bars

    Returns:
        SnapshotMetadata with upload details

    Raises:
        FileNotFoundError: If source file doesn't exist
        RuntimeError: If authentication fails or bucket is inaccessible
        IOError: If compression or upload fails
        ValueError: If checksum verification fails
    """
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    # Create GCS client and validate bucket access
    client = create_storage_client(provider_config.project_id)
    validate_bucket_access(client, provider_config.bucket_name)

    # Generate snapshot filename
    snapshot_filename = generate_snapshot_filename(
        provider_config.filename_prefix, provider_config.compression_enabled
    )
    blob_name = f"{provider_config.prefix}{snapshot_filename}"

    if dry_run:
        logger.info(
            f"[DRY RUN] Would upload {source_path} to gs://{provider_config.bucket_name}/{blob_name}"
        )

        # Return mock metadata for dry run
        now = datetime.now(UTC)
        return SnapshotMetadata(
            sequential_index=1,  # Placeholder
            filename=snapshot_filename,
            timestamp=now,
            size_bytes=source_path.stat().st_size,
            gcs_bucket=provider_config.bucket_name,
            gcs_path=f"gs://{provider_config.bucket_name}/{blob_name}",
            crc32c="AAAAAA==",  # Placeholder
            content_encoding="gzip" if provider_config.compression_enabled else None,
            tags=[],
            created=now,
            updated=now,
        )

    # Compress file if enabled
    if provider_config.compression_enabled:
        compressed_path = source_path.parent / f"{source_path.name}.gz.tmp"
        try:
            compress_file(
                source_path,
                compressed_path,
                provider_config.compression_level,
                show_progress=show_progress,
            )
            upload_path = compressed_path
            content_encoding = "gzip"
        except Exception as e:
            if compressed_path.exists():
                compressed_path.unlink()
            raise OSError(f"Compression failed: {e}") from e
    else:
        upload_path = source_path
        content_encoding = None

    try:
        # Compute CRC32C checksum
        logger.info(f"Computing CRC32C checksum for {upload_path.name}...")
        expected_crc32c = compute_crc32c(upload_path)

        # Upload to GCS with resumable upload
        bucket = client.bucket(provider_config.bucket_name)
        blob = bucket.blob(blob_name)

        # Set content encoding for transparent decompression
        if content_encoding:
            blob.content_encoding = content_encoding

        upload_size = upload_path.stat().st_size
        bytes_uploaded = 0

        # Create progress bar for upload
        if show_progress:
            progress = Progress(
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeElapsedColumn(),
                console=console,
            )
            progress.start()
            task_id = progress.add_task(f"Uploading {snapshot_filename}...", total=upload_size)
        else:
            progress = None
            task_id = None

        # Upload file with progress tracking using a custom file-like wrapper
        # For files >8MB, GCS automatically uses resumable upload
        try:
            if show_progress:
                # Wrap file in progress-tracking wrapper
                from io import BufferedReader

                class ProgressFileReader(BufferedReader):
                    """File reader that updates progress bar during upload."""

                    def __init__(self, file, progress, task_id):
                        super().__init__(file)
                        self._progress = progress
                        self._task_id = task_id
                        self.bytes_uploaded = 0

                    def read(self, size=-1):
                        chunk = super().read(size)
                        if chunk and self._progress and self._task_id is not None:
                            self._progress.update(self._task_id, advance=len(chunk))
                            self.bytes_uploaded += len(chunk)
                        return chunk

                with upload_path.open("rb") as f:
                    progress_reader = ProgressFileReader(f, progress, task_id)
                    blob.upload_from_file(
                        progress_reader,
                        checksum="crc32c",  # Server-side checksum verification
                        retry=PRODUCTION_RETRY,
                        timeout=GCS_UPLOAD_TIMEOUT_SECONDS,  # 1 hour timeout for large files
                    )
                    bytes_uploaded = progress_reader.bytes_uploaded

                if progress:
                    progress.stop()
            else:
                # No progress tracking, upload directly
                with upload_path.open("rb") as f:
                    blob.upload_from_file(
                        f,
                        checksum="crc32c",  # Server-side checksum verification
                        retry=PRODUCTION_RETRY,
                        timeout=GCS_UPLOAD_TIMEOUT_SECONDS,  # 1 hour timeout for large files
                    )

        except (ConnectionError, TimeoutError, OSError) as e:
            if progress:
                progress.stop()
            raise OSError(
                f"Network error during upload to GCS.\n\n"
                f"Upload may have failed partway through (progress: {bytes_uploaded:,} of {upload_size:,} bytes).\n\n"
                f"Common causes:\n"
                f"  - Network connectivity lost during upload\n"
                f"  - Upload timeout (files >{upload_size // 1024 // 1024}MB may take longer)\n"
                f"  - Firewall blocking persistent connections to Google Cloud\n"
                f"  - VPN disconnected during upload\n\n"
                f"Solutions:\n"
                f"  1. Retry the upload - GCS resumable upload may resume from checkpoint\n"
                f"  2. Check network stability:\n"
                f"     ping -c 5 storage.googleapis.com\n\n"
                f"  3. Verify firewall allows outbound HTTPS (port 443)\n\n"
                f"  4. If using VPN/proxy, ensure stable connection during upload\n\n"
                f"  5. For large files, consider increasing timeout in code\n\n"
                f"  Error details: {e}\n"
            ) from e

        except gcs_exceptions.TooManyRequests as e:
            if progress:
                progress.stop()
            raise OSError(
                f"Rate limit exceeded during upload to GCS.\n\n"
                f"You have exceeded the API rate limit for Google Cloud Storage.\n\n"
                f"Solutions:\n"
                f"  1. Wait a few minutes and retry the upload\n\n"
                f"  2. Check your GCS quota limits:\n"
                f"     https://console.cloud.google.com/apis/api/storage.googleapis.com/quotas\n\n"
                f"  3. If uploads are frequent, consider requesting quota increase:\n"
                f"     https://cloud.google.com/docs/quota\n\n"
                f"  4. Implement exponential backoff between uploads\n\n"
                f"  Error details: {e}\n"
            ) from e

        except (gcs_exceptions.Forbidden, gcs_exceptions.Unauthorized) as e:
            if progress:
                progress.stop()
            raise RuntimeError(
                f"Permission denied during upload to GCS bucket '{provider_config.bucket_name}'.\n\n"
                f"Your credentials lack permission to upload objects.\n\n"
                f"Required permissions:\n"
                f"  - storage.objects.create\n\n"
                f"Solutions:\n"
                f"  1. Grant Storage Object Admin role:\n"
                f"     gcloud storage buckets add-iam-policy-binding gs://{provider_config.bucket_name} \\\n"
                f"       --member='serviceAccount:YOUR_SA@PROJECT.iam.gserviceaccount.com' \\\n"
                f"       --role='roles/storage.objectAdmin'\n\n"
                f"  2. Verify current permissions:\n"
                f"     gcloud storage buckets get-iam-policy gs://{provider_config.bucket_name}\n\n"
                f"  Error details: {e}\n"
            ) from e

        except api_exceptions.RetryError as e:
            if progress:
                progress.stop()
            raise OSError(
                f"Upload failed after multiple retry attempts.\n\n"
                f"The upload was retried multiple times but continued to fail.\n\n"
                f"Common causes:\n"
                f"  - Persistent network connectivity issues\n"
                f"  - GCS service degradation or outage\n"
                f"  - Quota or rate limit exceeded\n"
                f"  - Insufficient permissions\n\n"
                f"Solutions:\n"
                f"  1. Check GCS service status:\n"
                f"     https://status.cloud.google.com/\n\n"
                f"  2. Verify network connectivity:\n"
                f"     curl -I https://storage.googleapis.com\n\n"
                f"  3. Check API quotas and limits:\n"
                f"     https://console.cloud.google.com/apis/api/storage.googleapis.com/quotas\n\n"
                f"  4. Review error details below for specific cause\n\n"
                f"  Error details: {e}\n"
            ) from e

        # Reload blob to get server-computed metadata
        try:
            blob.reload()
        except Exception as e:
            logger.warning(f"Failed to reload blob metadata after upload: {e}")
            logger.warning("Upload may have succeeded, but metadata verification skipped")

        # Verify checksum matches
        if blob.crc32c != expected_crc32c:
            logger.error(f"Checksum mismatch! Expected: {expected_crc32c}, Got: {blob.crc32c}")
            raise ValueError(
                "Upload verification failed: CRC32C checksum mismatch.\n\n"
                "The uploaded file's checksum does not match the local file.\n\n"
                "Possible causes:\n"
                "  - File was corrupted during upload\n"
                "  - Network errors introduced data corruption\n"
                "  - Storage system error\n\n"
                "Solutions:\n"
                "  1. Retry the upload - this may have been a transient error\n"
                "  2. Verify local file integrity before upload\n"
                "  3. Check network stability during upload\n"
                "  4. If issue persists, contact Google Cloud Support\n"
            )

        logger.info(f"Upload complete: gs://{provider_config.bucket_name}/{blob_name}")
        logger.info(f"CRC32C checksum verified: {blob.crc32c}")

        # Parse timestamp from filename
        # Format: looker-2025-12-14T16-21-09.db.gz or looker-2025-12-14T16-21-09.db
        # Extract timestamp part between prefix and first dot
        timestamp_str = snapshot_filename.split("-", 1)[1].split(".")[0]
        timestamp = datetime.strptime(timestamp_str, "%Y-%m-%dT%H-%M-%S").replace(tzinfo=UTC)

        # Return snapshot metadata
        return SnapshotMetadata(
            sequential_index=1,  # Will be assigned by lister
            filename=snapshot_filename,
            timestamp=timestamp,
            size_bytes=blob.size,
            gcs_bucket=provider_config.bucket_name,
            gcs_path=f"gs://{provider_config.bucket_name}/{blob_name}",
            crc32c=blob.crc32c,
            content_encoding=content_encoding,
            tags=[],
            created=blob.time_created.replace(tzinfo=UTC),
            updated=blob.updated.replace(tzinfo=UTC),
        )

    finally:
        # Clean up temporary compressed file
        if provider_config.compression_enabled and upload_path != source_path:
            if upload_path.exists():
                upload_path.unlink()
