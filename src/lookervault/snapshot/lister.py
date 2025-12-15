"""Snapshot listing and lookup functionality for cloud storage."""

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from google.cloud import storage

from lookervault.snapshot.models import SnapshotMetadata

if TYPE_CHECKING:
    from google.cloud.storage import Blob


class BlobCache:
    """Local cache for GCS blob listings with TTL expiration.

    Caches snapshot metadata to reduce API calls to Google Cloud Storage.
    Default TTL is 5 minutes.
    """

    def __init__(self, cache_path: str | None = None, ttl_minutes: int = 5) -> None:
        """
        Initialize blob cache.

        Args:
            cache_path: Path to cache file. Defaults to ~/.lookervault/snapshot_cache.json
            ttl_minutes: Time-to-live for cached data in minutes. 0 disables caching.
        """
        if cache_path is None:
            cache_path = str(Path.home() / ".lookervault" / "snapshot_cache.json")

        self.cache_path = Path(cache_path)
        self.ttl_minutes = ttl_minutes
        self._cache_dir = self.cache_path.parent

    def get(self) -> list[SnapshotMetadata] | None:
        """
        Retrieve cached snapshot metadata if not expired.

        Returns:
            List of snapshot metadata if cache is valid, None if expired or doesn't exist
        """
        if self.ttl_minutes == 0:
            # Caching disabled
            return None

        if not self.cache_path.exists():
            return None

        try:
            with self.cache_path.open() as f:
                data = json.load(f)

            # Check expiration
            cached_at = datetime.fromisoformat(data["cached_at"])
            now = datetime.now(UTC)
            age = now - cached_at

            if age > timedelta(minutes=self.ttl_minutes):
                # Cache expired
                return None

            # Deserialize snapshot metadata
            snapshots = [SnapshotMetadata(**item) for item in data["snapshots"]]
            return snapshots

        except (json.JSONDecodeError, KeyError, ValueError, FileNotFoundError):
            # Cache corrupted or invalid, ignore
            return None

    def set(self, snapshots: list[SnapshotMetadata]) -> None:
        """
        Store snapshot metadata in cache.

        Args:
            snapshots: List of snapshot metadata to cache
        """
        if self.ttl_minutes == 0:
            # Caching disabled
            return

        # Ensure cache directory exists
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        # Serialize snapshot metadata
        data = {
            "cached_at": datetime.now(UTC).isoformat(),
            "snapshots": [snapshot.model_dump(mode="json") for snapshot in snapshots],
        }

        with self.cache_path.open("w") as f:
            json.dump(data, f, indent=2)

    def clear(self) -> None:
        """Clear the cache by deleting the cache file."""
        if self.cache_path.exists():
            self.cache_path.unlink()


def parse_timestamp_from_filename(filename: str) -> datetime:
    """
    Parse UTC timestamp from snapshot filename.

    Expected format: {prefix}-YYYY-MM-DDTHH-MM-SS.db[.gz]

    Args:
        filename: Snapshot filename (e.g., "looker-2025-12-13T14-30-00.db.gz")

    Returns:
        UTC datetime parsed from filename

    Raises:
        ValueError: If filename doesn't match expected format
    """
    # Remove directory prefix if present (e.g., "snapshots/looker-...")
    basename = filename.split("/")[-1]

    # Pattern: {prefix}-YYYY-MM-DDTHH-MM-SS.db or .db.gz
    pattern = r"^[a-z0-9_-]+-(\d{4})-(\d{2})-(\d{2})T(\d{2})-(\d{2})-(\d{2})\.db(?:\.gz)?$"
    match = re.match(pattern, basename)

    if not match:
        raise ValueError(
            f"Invalid snapshot filename format: {filename}. "
            f"Expected format: {{prefix}}-YYYY-MM-DDTHH-MM-SS.db[.gz]"
        )

    year, month, day, hour, minute, second = map(int, match.groups())

    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=UTC)
    except ValueError as e:
        raise ValueError(f"Invalid timestamp in filename {filename}: {e}") from e


def list_snapshots(
    client: storage.Client,
    bucket_name: str,
    prefix: str = "snapshots/",
    name_filter: str | None = None,
    use_cache: bool = True,
    cache_ttl_minutes: int = 5,
) -> list[SnapshotMetadata]:
    """
    List all snapshots in GCS bucket sorted by creation time (newest first).

    Assigns sequential indices (1, 2, 3...) to snapshots with 1 being most recent.

    Args:
        client: Authenticated GCS storage client
        bucket_name: GCS bucket name
        prefix: Object name prefix for snapshots (default: "snapshots/")
        name_filter: Filter snapshots by filename prefix (e.g., "pre-migration")
        use_cache: Whether to use local cache (default: True)
        cache_ttl_minutes: Cache TTL in minutes (default: 5, 0 disables caching)

    Returns:
        List of snapshot metadata sorted by creation time (newest first) with indices

    Raises:
        RuntimeError: If bucket doesn't exist or client lacks permissions
    """
    # Check cache first
    cache = BlobCache(ttl_minutes=cache_ttl_minutes)
    if use_cache:
        cached = cache.get()
        if cached is not None:
            return cached

    # Fetch from GCS
    try:
        bucket = client.bucket(bucket_name)

        # List all blobs with prefix
        blobs = list(bucket.list_blobs(prefix=prefix))

        # Filter out directory markers (blobs with size 0 and ending with /)
        blobs = [blob for blob in blobs if blob.size > 0 and not blob.name.endswith("/")]

        # Filter by name if specified
        if name_filter:
            # Extract filename from full path (e.g., "snapshots/pre-migration-2025-12-14...")
            blobs = [
                blob for blob in blobs if blob.name.split("/")[-1].startswith(f"{name_filter}-")
            ]

        # Sort by creation time (newest first)
        sorted_blobs = sorted(blobs, key=lambda b: b.time_created, reverse=True)

        # Convert to SnapshotMetadata with sequential indices
        snapshots = [
            _blob_to_snapshot_metadata(blob, bucket_name, index)
            for index, blob in enumerate(sorted_blobs, start=1)
        ]

        # Update cache
        cache.set(snapshots)

        return snapshots

    except Exception as e:
        if "does not exist" in str(e).lower():
            raise RuntimeError(
                f"GCS bucket '{bucket_name}' does not exist.\n\n"
                f"Create the bucket:\n"
                f"  gcloud storage buckets create gs://{bucket_name} --location=us-central1"
            ) from e

        if "permission" in str(e).lower() or "forbidden" in str(e).lower():
            raise RuntimeError(
                f"Insufficient permissions for GCS bucket '{bucket_name}'.\n\n"
                f"Grant required permissions:\n"
                f"  - storage.objects.get\n"
                f"  - storage.objects.list"
            ) from e

        raise RuntimeError(f"Failed to list snapshots: {e}") from e


def get_snapshot_by_index(
    client: storage.Client,
    bucket_name: str,
    index: int,
    prefix: str = "snapshots/",
    name_filter: str | None = None,
    use_cache: bool = True,
    cache_ttl_minutes: int = 5,
) -> SnapshotMetadata:
    """
    Retrieve specific snapshot by sequential index.

    Args:
        client: Authenticated GCS storage client
        bucket_name: GCS bucket name
        index: Sequential index (1-based, 1 = most recent)
        prefix: Object name prefix for snapshots (default: "snapshots/")
        name_filter: Filter snapshots by filename prefix (e.g., "pre-migration")
        use_cache: Whether to use local cache (default: True)
        cache_ttl_minutes: Cache TTL in minutes (default: 5)

    Returns:
        Snapshot metadata for the specified index

    Raises:
        ValueError: If index is invalid or out of range
        RuntimeError: If bucket operation fails
    """
    # List all snapshots (uses cache if available)
    snapshots = list_snapshots(
        client=client,
        bucket_name=bucket_name,
        prefix=prefix,
        name_filter=name_filter,
        use_cache=use_cache,
        cache_ttl_minutes=cache_ttl_minutes,
    )

    # Validate index
    if index < 1:
        raise ValueError(f"Index must be positive (got {index})")

    if index > len(snapshots):
        if len(snapshots) == 0:
            raise ValueError(
                f"No snapshots found in gs://{bucket_name}/{prefix}\n\n"
                f"Run 'lookervault snapshot upload' to create a snapshot."
            )
        else:
            raise ValueError(
                f"Invalid index {index}. Valid range: 1-{len(snapshots)}\n\n"
                f"Run 'lookervault snapshot list' to see available snapshots."
            )

    # Index is 1-based (user-facing)
    return snapshots[index - 1]


def get_snapshot_by_timestamp(
    client: storage.Client,
    bucket_name: str,
    timestamp: datetime,
    filename_prefix: str = "looker",
    prefix: str = "snapshots/",
) -> SnapshotMetadata:
    """
    Retrieve specific snapshot by exact timestamp.

    Args:
        client: Authenticated GCS storage client
        bucket_name: GCS bucket name
        timestamp: UTC timestamp to search for
        filename_prefix: Snapshot filename prefix (default: "looker")
        prefix: Object name prefix for snapshots (default: "snapshots/")

    Returns:
        Snapshot metadata for the specified timestamp

    Raises:
        ValueError: If no snapshot found with that timestamp
        RuntimeError: If bucket operation fails
    """
    # Construct expected filenames (try both .db.gz and .db)
    timestamp_str = timestamp.strftime("%Y-%m-%dT%H-%M-%S")
    filenames = [
        f"{prefix}{filename_prefix}-{timestamp_str}.db.gz",
        f"{prefix}{filename_prefix}-{timestamp_str}.db",
    ]

    bucket = client.bucket(bucket_name)

    for filename in filenames:
        blob = bucket.blob(filename)

        if blob.exists():
            blob.reload()  # Fetch metadata
            return _blob_to_snapshot_metadata(blob, bucket_name, sequential_index=None)

    raise ValueError(
        f"Snapshot not found for timestamp {timestamp.isoformat()}.\n\n"
        f"Searched for:\n"
        f"  - {filenames[0]}\n"
        f"  - {filenames[1]}\n\n"
        f"Run 'lookervault snapshot list' to see available snapshots."
    )


def filter_by_date_range(
    snapshots: list[SnapshotMetadata],
    date_filter: str,
) -> list[SnapshotMetadata]:
    """
    Filter snapshots by date range.

    Supports multiple filter formats:
    - "last-N-days": Snapshots from last N days (e.g., "last-7-days", "last-30-days")
    - "YYYY-MM": Snapshots from specific month (e.g., "2025-12")
    - "YYYY": Snapshots from specific year (e.g., "2025")

    Args:
        snapshots: List of snapshot metadata to filter
        date_filter: Date filter string

    Returns:
        Filtered list of snapshots matching the date range

    Raises:
        ValueError: If date_filter format is invalid
    """
    now = datetime.now(UTC)

    # Pattern 1: "last-N-days"
    last_days_pattern = r"^last-(\d+)-days?$"
    match = re.match(last_days_pattern, date_filter.lower())
    if match:
        days = int(match.group(1))
        cutoff = now - timedelta(days=days)
        return [s for s in snapshots if s.created >= cutoff]

    # Pattern 2: "YYYY-MM" (specific month)
    month_pattern = r"^(\d{4})-(\d{2})$"
    match = re.match(month_pattern, date_filter)
    if match:
        year, month = int(match.group(1)), int(match.group(2))

        if not (1 <= month <= 12):
            raise ValueError(f"Invalid month: {month}. Must be 1-12.")

        return [s for s in snapshots if s.created.year == year and s.created.month == month]

    # Pattern 3: "YYYY" (specific year)
    year_pattern = r"^(\d{4})$"
    match = re.match(year_pattern, date_filter)
    if match:
        year = int(match.group(1))
        return [s for s in snapshots if s.created.year == year]

    # Invalid format
    raise ValueError(
        f"Invalid date filter: '{date_filter}'.\n\n"
        f"Supported formats:\n"
        f"  - last-N-days (e.g., 'last-7-days', 'last-30-days')\n"
        f"  - YYYY-MM (e.g., '2025-12')\n"
        f"  - YYYY (e.g., '2025')"
    )


def _blob_to_snapshot_metadata(
    blob: "Blob",
    bucket_name: str,
    sequential_index: int | None,
) -> SnapshotMetadata:
    """
    Convert GCS blob to SnapshotMetadata.

    Args:
        blob: GCS blob object
        bucket_name: GCS bucket name
        sequential_index: Sequential index (1-based) or None if not assigned yet

    Returns:
        SnapshotMetadata instance
    """
    # Parse timestamp from filename
    blob_name = blob.name or ""
    try:
        timestamp = parse_timestamp_from_filename(blob_name)
    except ValueError:
        # If filename doesn't match pattern, use blob creation time
        timestamp = blob.time_created.replace(tzinfo=UTC)

    # Construct GCS path
    gcs_path = f"gs://{bucket_name}/{blob_name}"

    # Extract tags from custom metadata if present
    tags = []
    if blob.metadata:
        tag_value = blob.metadata.get("tags", "")
        if tag_value:
            tags = [tag.strip() for tag in tag_value.split(",")]

    return SnapshotMetadata(
        sequential_index=sequential_index if sequential_index is not None else 0,
        filename=blob_name,
        timestamp=timestamp,
        size_bytes=blob.size or 0,
        gcs_bucket=bucket_name,
        gcs_path=gcs_path,
        crc32c=blob.crc32c or "",
        content_encoding=blob.content_encoding,
        tags=tags,
        created=blob.time_created.replace(tzinfo=UTC),
        updated=blob.updated.replace(tzinfo=UTC),
    )
