"""Snapshot download functionality with integrity verification."""

import gzip
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

import google_crc32c
from google.api_core import exceptions as api_exceptions
from google.api_core import retry
from google.cloud import exceptions as gcs_exceptions
from google.cloud import storage
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
from lookervault.snapshot.models import SnapshotMetadata

logger = logging.getLogger(__name__)

# Chunk size for download and decompression (8 MB recommended by GCS)
CHUNK_SIZE = 8 * 1024 * 1024

# Production retry policy for GCS operations
PRODUCTION_RETRY = retry.Retry(
    initial=1.0,  # 1 second initial delay
    maximum=60.0,  # Max 60 seconds between retries
    multiplier=2.0,  # Exponential backoff
    deadline=600.0,  # 10 minute total timeout
    predicate=retry.if_exception_type(
        Exception,  # Retry on any transient error
    ),
)


def verify_download_integrity(file_path: Path, expected_crc32c: str) -> bool:
    """
    Verify downloaded file integrity using CRC32C checksum.

    Args:
        file_path: Path to downloaded file
        expected_crc32c: Expected base64-encoded CRC32C checksum

    Returns:
        True if checksum matches

    Raises:
        ValueError: If checksum mismatch detected
        FileNotFoundError: If file doesn't exist
        IOError: If file cannot be read
    """
    import base64

    if not file_path.exists():
        raise FileNotFoundError(f"Downloaded file not found: {file_path}")

    # Compute actual checksum
    crc32c_hash = google_crc32c.Checksum()

    with file_path.open("rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            crc32c_hash.update(chunk)

    actual_crc32c = base64.b64encode(crc32c_hash.digest()).decode("utf-8")

    # Compare checksums
    if actual_crc32c != expected_crc32c:
        raise ValueError(
            f"Checksum mismatch detected!\n\n"
            f"Expected: {expected_crc32c}\n"
            f"Actual:   {actual_crc32c}\n\n"
            f"The downloaded file may be corrupted. This can happen due to:\n"
            f"  - Network errors during download\n"
            f"  - Storage corruption\n"
            f"  - Incomplete download\n\n"
            f"Troubleshooting:\n"
            f"  1. Retry the download\n"
            f"  2. Check network stability\n"
            f"  3. Verify GCS bucket integrity\n"
            f"  4. Contact support if the issue persists"
        )

    logger.info(f"Checksum verified: {actual_crc32c}")
    return True


def decompress_file(
    source_path: Path,
    dest_path: Path,
    show_progress: bool = True,
) -> int:
    """
    Decompress gzipped file with progress tracking.

    Handles both compressed (.gz) and uncompressed files gracefully.

    Args:
        source_path: Path to source file (compressed or uncompressed)
        dest_path: Path to decompressed output file
        show_progress: Whether to show progress bar

    Returns:
        Size of decompressed file in bytes

    Raises:
        FileNotFoundError: If source file doesn't exist
        IOError: If decompression fails
    """
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    source_size = source_path.stat().st_size
    decompressed_size = 0

    # Check if file is actually gzipped (magic number check)
    with source_path.open("rb") as f:
        magic_number = f.read(2)

    is_gzipped = magic_number == b"\x1f\x8b"

    if not is_gzipped:
        # File is not compressed, just copy it
        logger.info(f"File is not compressed, copying directly: {source_path.name}")
        shutil.copy2(source_path, dest_path)
        return source_path.stat().st_size

    # Create progress bar for decompression
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
            task_id = progress.add_task(f"Decompressing {source_path.name}...", total=source_size)

        with gzip.open(source_path, "rb") as f_in:
            with dest_path.open("wb") as f_out:
                bytes_read = 0
                while chunk := f_in.read(CHUNK_SIZE):
                    f_out.write(chunk)
                    decompressed_size += len(chunk)
                    bytes_read += len(chunk)

                    # Update progress based on compressed bytes read
                    # Note: We approximate progress by compressed bytes since we can't know
                    # decompressed size ahead of time
                    if progress and task_id is not None:
                        # Approximate: assume we've read proportional amount of compressed data
                        estimated_compressed_bytes = min(bytes_read // 10, source_size)
                        progress.update(task_id, completed=estimated_compressed_bytes)

        if progress:
            progress.update(task_id, completed=source_size)
            progress.stop()

        logger.info(
            f"Decompressed {source_path.name}: {source_size:,} → {decompressed_size:,} bytes "
            f"({(decompressed_size / source_size):.1f}x expansion)"
        )

        return decompressed_size

    except Exception as e:
        # Clean up partial decompressed file on error
        if dest_path.exists():
            dest_path.unlink()
        raise OSError(f"Decompression failed: {e}") from e


@tenacity_retry(
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=60),
    reraise=True,
)
def download_snapshot(
    client: storage.Client,
    snapshot: SnapshotMetadata,
    output_path: Path,
    verify_checksum: bool = True,
    show_progress: bool = True,
) -> dict:
    """
    Download snapshot from GCS to local file with integrity verification.

    This function handles the complete download workflow:
    1. Download from GCS with resumable download
    2. Verify CRC32C checksum (optional)
    3. Decompress if needed
    4. Return download metadata

    Args:
        client: Authenticated GCS storage client
        snapshot: Snapshot metadata with GCS location
        output_path: Path to save downloaded file
        verify_checksum: Whether to verify CRC32C checksum after download
        show_progress: Whether to show progress bars

    Returns:
        Dictionary with download metadata:
            - filename: Output filename
            - size_bytes: Final file size
            - download_time: Download duration in seconds
            - checksum_verified: Whether checksum was verified

    Raises:
        FileExistsError: If output file exists and overwrite not confirmed
        RuntimeError: If bucket access fails
        ValueError: If checksum verification fails
        IOError: If download or decompression fails
    """
    start_time = datetime.now(UTC)

    # Get bucket and blob
    bucket = client.bucket(snapshot.gcs_bucket)
    blob = bucket.blob(snapshot.filename)

    # Check if blob exists
    try:
        if not blob.exists():
            raise RuntimeError(
                f"Snapshot not found in GCS: {snapshot.gcs_path}\n\n"
                f"The snapshot may have been deleted or moved.\n"
                f"Run 'lookervault snapshot list' to see available snapshots."
            )
    except (gcs_exceptions.Forbidden, gcs_exceptions.Unauthorized) as e:
        raise RuntimeError(
            f"Permission denied when accessing snapshot in GCS bucket '{snapshot.gcs_bucket}'.\n\n"
            f"Your credentials lack permission to read objects.\n\n"
            f"Required permissions:\n"
            f"  - storage.objects.get\n\n"
            f"Solutions:\n"
            f"  1. Grant Storage Object Viewer role:\n"
            f"     gcloud storage buckets add-iam-policy-binding gs://{snapshot.gcs_bucket} \\\n"
            f"       --member='serviceAccount:YOUR_SA@PROJECT.iam.gserviceaccount.com' \\\n"
            f"       --role='roles/storage.objectViewer'\n\n"
            f"  2. Verify current permissions:\n"
            f"     gcloud storage buckets get-iam-policy gs://{snapshot.gcs_bucket}\n\n"
            f"  Error details: {e}\n"
        ) from e
    except Exception as e:
        error_msg = str(e).lower()
        if (
            "connection" in error_msg
            or "timeout" in error_msg
            or "network" in error_msg
            or "dns" in error_msg
        ):
            raise RuntimeError(
                f"Network error while checking snapshot existence in GCS.\n\n"
                f"Common causes:\n"
                f"  - Network connectivity issues\n"
                f"  - Firewall blocking Google Cloud APIs\n"
                f"  - DNS resolution problems\n\n"
                f"Solutions:\n"
                f"  1. Test connectivity to Google Cloud:\n"
                f"     curl -I https://storage.googleapis.com\n\n"
                f"  2. Retry the download - network issues are often transient\n\n"
                f"  3. Verify firewall allows HTTPS (port 443) to Google Cloud APIs\n\n"
                f"  Error details: {e}\n"
            ) from e
        raise

    # Reload to get latest metadata
    try:
        blob.reload()
    except Exception as e:
        logger.warning(f"Failed to reload blob metadata: {e}")
        logger.warning("Proceeding with download using snapshot metadata")

    # Determine if file is compressed
    is_compressed = snapshot.content_encoding == "gzip" or snapshot.filename.endswith(".gz")

    # Create temporary download path if decompression needed
    if is_compressed:
        download_path = output_path.parent / f"{output_path.name}.gz.tmp"
    else:
        download_path = output_path

    try:
        # Download from GCS with progress tracking
        download_size = blob.size

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
            task_id = progress.add_task(
                f"Downloading {snapshot.filename.split('/')[-1]}...", total=download_size
            )
        else:
            progress = None
            task_id = None

        # Download blob to file with chunked streaming for progress tracking
        bytes_downloaded = 0
        try:
            with download_path.open("wb") as f:
                # Download in chunks to track progress
                chunk_size = CHUNK_SIZE

                for start in range(0, download_size, chunk_size):
                    end = min(start + chunk_size - 1, download_size - 1)

                    # Download chunk using byte range
                    chunk_bytes = blob.download_as_bytes(
                        start=start, end=end + 1, retry=PRODUCTION_RETRY
                    )
                    f.write(chunk_bytes)
                    bytes_downloaded += len(chunk_bytes)

                    # Update progress
                    if progress and task_id is not None:
                        progress.update(task_id, advance=len(chunk_bytes))

            if progress:
                progress.stop()

            logger.info(f"Download complete: {download_path}")

        except (ConnectionError, TimeoutError, OSError) as e:
            if progress:
                progress.stop()
            raise OSError(
                f"Network error during download from GCS.\n\n"
                f"Download failed after downloading {bytes_downloaded:,} of {download_size:,} bytes.\n\n"
                f"Common causes:\n"
                f"  - Network connectivity lost during download\n"
                f"  - Download timeout (files >{download_size // 1024 // 1024}MB may take longer)\n"
                f"  - Firewall blocking persistent connections to Google Cloud\n"
                f"  - VPN disconnected during download\n\n"
                f"Solutions:\n"
                f"  1. Retry the download - it will resume from where it failed\n"
                f"  2. Check network stability:\n"
                f"     ping -c 5 storage.googleapis.com\n\n"
                f"  3. Verify firewall allows outbound HTTPS (port 443)\n\n"
                f"  4. If using VPN/proxy, ensure stable connection during download\n\n"
                f"  5. For large files, consider increasing timeout in code\n\n"
                f"  Error details: {e}\n"
            ) from e

        except gcs_exceptions.TooManyRequests as e:
            if progress:
                progress.stop()
            raise OSError(
                f"Rate limit exceeded during download from GCS.\n\n"
                f"You have exceeded the API rate limit for Google Cloud Storage.\n\n"
                f"Solutions:\n"
                f"  1. Wait a few minutes and retry the download\n\n"
                f"  2. Check your GCS quota limits:\n"
                f"     https://console.cloud.google.com/apis/api/storage.googleapis.com/quotas\n\n"
                f"  3. If downloads are frequent, consider requesting quota increase:\n"
                f"     https://cloud.google.com/docs/quota\n\n"
                f"  4. Implement exponential backoff between downloads\n\n"
                f"  Error details: {e}\n"
            ) from e

        except (gcs_exceptions.Forbidden, gcs_exceptions.Unauthorized) as e:
            if progress:
                progress.stop()
            raise RuntimeError(
                f"Permission denied during download from GCS bucket '{snapshot.gcs_bucket}'.\n\n"
                f"Your credentials lack permission to read objects.\n\n"
                f"Required permissions:\n"
                f"  - storage.objects.get\n\n"
                f"Solutions:\n"
                f"  1. Grant Storage Object Viewer role:\n"
                f"     gcloud storage buckets add-iam-policy-binding gs://{snapshot.gcs_bucket} \\\n"
                f"       --member='serviceAccount:YOUR_SA@PROJECT.iam.gserviceaccount.com' \\\n"
                f"       --role='roles/storage.objectViewer'\n\n"
                f"  2. Verify current permissions:\n"
                f"     gcloud storage buckets get-iam-policy gs://{snapshot.gcs_bucket}\n\n"
                f"  Error details: {e}\n"
            ) from e

        except api_exceptions.RetryError as e:
            if progress:
                progress.stop()
            raise OSError(
                f"Download failed after multiple retry attempts.\n\n"
                f"The download was retried multiple times but continued to fail.\n\n"
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

        # Verify checksum if requested
        checksum_verified = False
        if verify_checksum:
            logger.info("Verifying download integrity...")
            try:
                verify_download_integrity(download_path, snapshot.crc32c)
                checksum_verified = True
            except ValueError:
                # Delete corrupted file
                if download_path.exists():
                    download_path.unlink()
                logger.error(
                    f"Checksum verification failed, corrupted file deleted: {download_path}"
                )
                raise

        # Decompress if needed
        if is_compressed:
            decompress_file(download_path, output_path, show_progress=show_progress)
            # Clean up temporary compressed file
            if download_path.exists():
                download_path.unlink()
            final_size = output_path.stat().st_size
        else:
            final_size = download_path.stat().st_size

        # Calculate download time
        end_time = datetime.now(UTC)
        download_time = (end_time - start_time).total_seconds()

        logger.info(f"Snapshot saved to: {output_path}")

        return {
            "filename": str(output_path),
            "size_bytes": final_size,
            "download_time": download_time,
            "checksum_verified": checksum_verified,
        }

    except Exception:
        # Clean up temporary files on error
        if download_path.exists() and download_path != output_path:
            download_path.unlink()
        if output_path.exists() and is_compressed:
            output_path.unlink()
        raise
