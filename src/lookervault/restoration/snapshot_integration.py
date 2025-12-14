"""Integration module for restoring Looker content directly from cloud snapshots.

This module provides functionality to:
- Download snapshots from GCS to temporary locations
- Integrate snapshot downloads with the restoration workflow
- Cleanup temporary snapshot files after restoration

Typical workflow:
1. User specifies --from-snapshot INDEX or TIMESTAMP
2. download_snapshot_to_temp() downloads to /tmp/
3. Restoration proceeds using temporary database
4. cleanup_temp_snapshot() removes temporary file
"""

import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from lookervault.config.loader import load_config
from lookervault.snapshot.downloader import download_snapshot
from lookervault.snapshot.lister import get_snapshot_by_index, get_snapshot_by_timestamp
from lookervault.snapshot.models import SnapshotMetadata

logger = logging.getLogger(__name__)


def parse_snapshot_reference(snapshot_ref: str) -> tuple[str, int | datetime]:
    """
    Parse snapshot reference into type (index or timestamp) and value.

    Snapshot reference can be:
    - Integer index (1, 2, 3...) for sequential snapshot lookup
    - Special keyword "latest" (alias for index 1, the most recent snapshot)
    - ISO timestamp (2025-12-14T10:30:00) for exact timestamp lookup

    Args:
        snapshot_ref: Snapshot reference string (index, "latest", or timestamp)

    Returns:
        Tuple of (reference_type, parsed_value):
        - ("index", int) if integer index or "latest"
        - ("timestamp", datetime) if ISO timestamp

    Raises:
        ValueError: If snapshot reference format is invalid

    Examples:
        >>> parse_snapshot_reference("1")
        ("index", 1)
        >>> parse_snapshot_reference("latest")
        ("index", 1)
        >>> parse_snapshot_reference("2025-12-14T10:30:00")
        ("timestamp", datetime(2025, 12, 14, 10, 30, 0, tzinfo=UTC))
    """
    # Handle "latest" alias
    if snapshot_ref.lower() == "latest":
        return ("index", 1)

    # Try parsing as integer index first
    try:
        index = int(snapshot_ref)
        if index < 1:
            raise ValueError(f"Snapshot index must be positive (got {index})")
        return ("index", index)
    except ValueError:
        pass

    # Try parsing as ISO timestamp
    try:
        # Support both with and without timezone
        if "T" in snapshot_ref:
            # ISO format: YYYY-MM-DDTHH:MM:SS
            timestamp = datetime.fromisoformat(snapshot_ref)
            # Ensure UTC timezone
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            return ("timestamp", timestamp)
    except ValueError:
        pass

    # Invalid format
    raise ValueError(
        f"Invalid snapshot reference: '{snapshot_ref}'.\n\n"
        f"Supported formats:\n"
        f"  - Integer index (e.g., '1', '2', '3')\n"
        f"  - Keyword 'latest' (most recent snapshot)\n"
        f"  - ISO timestamp (e.g., '2025-12-14T10:30:00')\n\n"
        f"Run 'lookervault snapshot list' to see available snapshots."
    )


def download_snapshot_to_temp(
    snapshot_ref: str,
    verify_checksum: bool = True,
    show_progress: bool = True,
) -> tuple[Path, SnapshotMetadata]:
    """
    Download snapshot from GCS to temporary location for restoration.

    This function:
    1. Parses snapshot reference (index, "latest", or timestamp)
    2. Looks up snapshot metadata from GCS
    3. Downloads snapshot to /tmp/lookervault-snapshot-{timestamp}.db
    4. Returns path to temporary file and snapshot metadata

    Args:
        snapshot_ref: Snapshot reference (index like "1", "latest", or timestamp like "2025-12-14T10:30:00")
        verify_checksum: Whether to verify CRC32C checksum after download
        show_progress: Whether to show progress bars during download

    Returns:
        Tuple of (temp_file_path, snapshot_metadata):
        - temp_file_path: Path to downloaded temporary file
        - snapshot_metadata: SnapshotMetadata with snapshot details

    Raises:
        ValueError: If snapshot reference is invalid or snapshot not found
        RuntimeError: If GCS authentication or download fails
        OSError: If temporary file creation fails

    Examples:
        >>> # Download by index
        >>> temp_path, metadata = download_snapshot_to_temp("1")
        >>> print(temp_path)
        PosixPath('/tmp/lookervault-snapshot-2025-12-14T10-30-00.db')

        >>> # Download latest snapshot
        >>> temp_path, metadata = download_snapshot_to_temp("latest")
        >>> print(temp_path)
        PosixPath('/tmp/lookervault-snapshot-2025-12-14T10-30-00.db')

        >>> # Download by timestamp
        >>> temp_path, metadata = download_snapshot_to_temp("2025-12-14T10:30:00")
        >>> print(metadata.filename)
        'snapshots/looker-2025-12-14T10-30-00.db.gz'
    """
    logger.info(f"Downloading snapshot from reference: {snapshot_ref}")

    # Step 1: Parse snapshot reference
    ref_type, ref_value = parse_snapshot_reference(snapshot_ref)
    logger.debug(f"Parsed snapshot reference: type={ref_type}, value={ref_value}")

    # Step 2: Load configuration for GCS client
    cfg = load_config(config_path=None)

    if not cfg.snapshot:
        raise ValueError(
            "Snapshot configuration not found.\n\n"
            "Please configure snapshot settings in lookervault.toml:\n"
            "[snapshot.provider]\n"
            'gcs_bucket = "your-bucket-name"\n'
        )

    bucket_name = cfg.snapshot.provider.bucket_name

    # Step 3: Create GCS client
    try:
        from lookervault.snapshot.client import create_storage_client

        client = create_storage_client()
    except Exception as e:
        raise RuntimeError(
            f"Failed to create GCS client: {e}\n\n"
            f"Troubleshooting:\n"
            f"  1. Verify Google Cloud credentials are configured\n"
            f"  2. Run 'gcloud auth application-default login'\n"
            f"  3. Ensure GOOGLE_APPLICATION_CREDENTIALS is set if using service account"
        ) from e

    # Step 4: Lookup snapshot metadata from GCS
    try:
        if ref_type == "index":
            snapshot = get_snapshot_by_index(
                client=client,
                bucket_name=bucket_name,
                index=ref_value,  # type: ignore
                prefix="snapshots/",
                use_cache=True,
            )
        else:  # timestamp
            snapshot = get_snapshot_by_timestamp(
                client=client,
                bucket_name=bucket_name,
                timestamp=ref_value,  # type: ignore
                filename_prefix="looker",
                prefix="snapshots/",
            )
    except ValueError as e:
        raise ValueError(f"Snapshot lookup failed: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Failed to lookup snapshot from GCS: {e}") from e

    logger.info(
        f"Found snapshot: {snapshot.filename} "
        f"({snapshot.size_bytes:,} bytes, created {snapshot.created.isoformat()})"
    )

    # Step 5: Create temporary file path
    # Format: /tmp/lookervault-snapshot-{timestamp}.db
    timestamp_str = snapshot.timestamp.strftime("%Y-%m-%dT%H-%M-%S")
    temp_dir = Path(tempfile.gettempdir())
    temp_path = temp_dir / f"lookervault-snapshot-{timestamp_str}.db"

    # Step 6: Download snapshot to temporary location
    try:
        download_snapshot(
            client=client,
            snapshot=snapshot,
            output_path=temp_path,
            verify_checksum=verify_checksum,
            show_progress=show_progress,
        )
    except Exception as e:
        # Clean up partial download if exists
        if temp_path.exists():
            temp_path.unlink()
        raise RuntimeError(f"Snapshot download failed: {e}") from e

    logger.info(f"Snapshot downloaded to temporary location: {temp_path}")

    return temp_path, snapshot


def cleanup_temp_snapshot(temp_path: Path) -> None:
    """
    Clean up temporary snapshot file after restoration.

    This function safely deletes temporary snapshot files downloaded during
    restore-from-snapshot operations. Errors are logged but do not raise
    exceptions to ensure restoration can complete even if cleanup fails.

    Args:
        temp_path: Path to temporary snapshot file to delete

    Examples:
        >>> temp_path = Path("/tmp/lookervault-snapshot-2025-12-14T10-30-00.db")
        >>> cleanup_temp_snapshot(temp_path)
        # File deleted if exists, errors logged but not raised
    """
    if not temp_path.exists():
        logger.debug(f"Temporary snapshot file already deleted: {temp_path}")
        return

    try:
        temp_path.unlink()
        logger.info(f"Cleaned up temporary snapshot file: {temp_path}")
    except Exception as e:
        logger.warning(f"Failed to cleanup temporary snapshot file {temp_path}: {e}")
        # Do not raise - cleanup failure should not block restoration success
