"""Retention policy enforcement and snapshot cleanup."""

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from google.api_core.exceptions import Forbidden, GoogleAPICallError
from google.cloud import storage
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from lookervault.snapshot.models import RetentionPolicy, SnapshotMetadata

if TYPE_CHECKING:
    from google.cloud.storage import Bucket

logger = logging.getLogger(__name__)


@dataclass
class DeleteResult:
    """Result of snapshot deletion operation."""

    deleted: int
    failed: int
    skipped: int
    size_freed_bytes: int


@dataclass
class RetentionEvaluation:
    """Result of retention policy evaluation."""

    snapshots_to_protect: list[SnapshotMetadata]
    snapshots_to_delete: list[SnapshotMetadata]
    protection_reasons: dict[str, str]  # snapshot_filename -> reason


class AuditLogger:
    """Audit logger for snapshot deletion operations.

    Logs all deletion operations to JSON Lines format for compliance and troubleshooting.
    Each log entry contains: timestamp, action, snapshot_filename, reason, user.
    """

    def __init__(self, log_path: str | None = None, gcs_bucket: str | None = None) -> None:
        """
        Initialize audit logger.

        Args:
            log_path: Path to local audit log file (default: ~/.lookervault/audit.log)
            gcs_bucket: Optional GCS bucket name for centralized audit logs
        """
        if log_path is None:
            log_path = str(Path.home() / ".lookervault" / "audit.log")

        self.log_path = Path(log_path).expanduser()
        self.gcs_bucket = gcs_bucket

        # Ensure audit log directory exists
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_deletion(
        self,
        snapshot_metadata: SnapshotMetadata,
        reason: str,
        success: bool = True,
        error_message: str | None = None,
    ) -> None:
        """
        Log a snapshot deletion operation.

        Args:
            snapshot_metadata: Metadata of the snapshot being deleted
            reason: Reason for deletion (e.g., "exceeds_max_age", "manual_deletion")
            success: Whether the deletion succeeded
            error_message: Error message if deletion failed
        """
        # Get user from environment (fallback to "unknown")
        user = os.environ.get("USER", os.environ.get("USERNAME", "unknown"))

        # Construct log entry
        log_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": "delete" if success else "delete_failed",
            "snapshot_filename": snapshot_metadata.filename,
            "snapshot_timestamp": snapshot_metadata.timestamp.isoformat(),
            "snapshot_size_bytes": snapshot_metadata.size_bytes,
            "reason": reason,
            "user": user,
            "success": success,
        }

        if error_message:
            log_entry["error"] = error_message

        # Append to JSON Lines file (append-only)
        with self.log_path.open("a") as f:
            f.write(json.dumps(log_entry) + "\n")

        logger.info(
            f"Audit log: {log_entry['action']} {snapshot_metadata.filename} (reason: {reason})"
        )

        # TODO: Optionally upload to GCS bucket for centralized logging
        # This would require implementing GCS upload logic (deferred for now)


def evaluate_retention_policy(
    snapshots: list[SnapshotMetadata],
    policy: RetentionPolicy,
) -> RetentionEvaluation:
    """
    Evaluate retention policy and determine which snapshots to protect vs. delete.

    Policy Logic:
    1. Always protect snapshots newer than min_days
    2. Always delete snapshots older than max_days (unless protected by min_count)
    3. Always protect at least min_count most recent snapshots (even if older than max_days)

    Args:
        snapshots: List of snapshot metadata (should be sorted by creation time, newest first)
        policy: Retention policy configuration

    Returns:
        RetentionEvaluation with snapshots to protect and delete, plus reasons
    """
    if not policy.enabled:
        # Retention policy disabled - protect everything
        return RetentionEvaluation(
            snapshots_to_protect=snapshots,
            snapshots_to_delete=[],
            protection_reasons={s.filename: "retention_policy_disabled" for s in snapshots},
        )

    now = datetime.now(UTC)
    min_age_cutoff = now - timedelta(days=policy.min_days)
    max_age_cutoff = now - timedelta(days=policy.max_days)

    snapshots_to_protect: list[SnapshotMetadata] = []
    snapshots_to_delete: list[SnapshotMetadata] = []
    protection_reasons: dict[str, str] = {}

    # Sort snapshots by creation time (newest first) if not already sorted
    sorted_snapshots = sorted(snapshots, key=lambda s: s.created, reverse=True)

    # Step 1: Protect minimum count (most recent snapshots)
    protected_by_min_count = set()
    for idx, snapshot in enumerate(sorted_snapshots):
        if idx < policy.min_count:
            protected_by_min_count.add(snapshot.filename)
            protection_reasons[snapshot.filename] = (
                f"minimum_backup_count ({idx + 1}/{policy.min_count})"
            )

    # Step 2: Evaluate each snapshot against retention policy
    for snapshot in sorted_snapshots:
        snapshot_age = snapshot.created.replace(tzinfo=UTC)

        # Already protected by minimum count?
        if snapshot.filename in protected_by_min_count:
            snapshots_to_protect.append(snapshot)
            continue

        # Newer than min_days? Always protect
        if snapshot_age >= min_age_cutoff:
            snapshots_to_protect.append(snapshot)
            protection_reasons[snapshot.filename] = (
                f"within_minimum_retention ({snapshot.age_days} days < {policy.min_days} days)"
            )
            continue

        # Older than max_days? Delete
        if snapshot_age < max_age_cutoff:
            snapshots_to_delete.append(snapshot)
            continue

        # Between min_days and max_days: protect (grace period)
        snapshots_to_protect.append(snapshot)
        protection_reasons[snapshot.filename] = (
            f"within_grace_period ({snapshot.age_days} days between {policy.min_days}-{policy.max_days} days)"
        )

    return RetentionEvaluation(
        snapshots_to_protect=snapshots_to_protect,
        snapshots_to_delete=snapshots_to_delete,
        protection_reasons=protection_reasons,
    )


def protect_minimum_backups(
    snapshots: list[SnapshotMetadata],
    min_count: int,
) -> list[int]:
    """
    Identify indices of snapshots that must be protected to maintain minimum backup count.

    Args:
        snapshots: List of snapshots sorted by creation time (newest first)
        min_count: Minimum number of snapshots to always protect

    Returns:
        List of snapshot indices (0-based) that are protected by minimum count rule
    """
    # Sort by creation time if not already sorted
    sorted_snapshots = sorted(snapshots, key=lambda s: s.created, reverse=True)

    # Protect first min_count snapshots
    protected_indices = list(range(min(min_count, len(sorted_snapshots))))

    return protected_indices


@retry(
    retry=retry_if_exception_type((GoogleAPICallError,)),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    reraise=True,
)
def delete_old_snapshots(
    client: storage.Client,
    bucket_name: str,
    snapshots_to_delete: list[SnapshotMetadata],
    audit_logger: AuditLogger | None = None,
    dry_run: bool = False,
) -> DeleteResult:
    """
    Delete old snapshots from GCS bucket.

    Args:
        client: Authenticated GCS storage client
        bucket_name: GCS bucket name
        snapshots_to_delete: List of snapshots to delete
        audit_logger: Optional audit logger for recording deletions
        dry_run: If True, skip actual deletion (preview only)

    Returns:
        DeleteResult with counts of deleted, failed, and skipped snapshots

    Error Handling:
        - Network errors: Retry with exponential backoff
        - Protected snapshots (403 Forbidden): Skip deletion, log warning, continue
        - Other errors: Log error, continue with remaining snapshots
    """
    bucket = client.bucket(bucket_name)

    deleted = 0
    failed = 0
    skipped = 0
    size_freed_bytes = 0

    for snapshot in snapshots_to_delete:
        blob_name = snapshot.filename

        try:
            if dry_run:
                logger.info(f"[DRY RUN] Would delete: {blob_name}")
                deleted += 1
                size_freed_bytes += snapshot.size_bytes
                continue

            # Delete blob from GCS
            blob = bucket.blob(blob_name)

            # Check if blob exists before attempting deletion
            if not blob.exists():
                logger.warning(
                    f"Snapshot not found (may have been deleted externally): {blob_name}"
                )
                skipped += 1
                continue

            # Attempt deletion
            blob.delete()

            logger.info(f"Deleted snapshot: {blob_name} ({snapshot.size_mb} MB)")
            deleted += 1
            size_freed_bytes += snapshot.size_bytes

            # Audit log successful deletion
            if audit_logger:
                audit_logger.log_deletion(
                    snapshot,
                    reason="retention_policy_cleanup",
                    success=True,
                )

        except Forbidden as e:
            # Protected snapshot (e.g., object lock, retention policy)
            logger.warning(f"Skipped protected snapshot: {blob_name} (GCS protection enabled: {e})")
            skipped += 1

            if audit_logger:
                audit_logger.log_deletion(
                    snapshot,
                    reason="retention_policy_cleanup",
                    success=False,
                    error_message=f"Protected by GCS: {str(e)}",
                )

        except GoogleAPICallError as e:
            # Network or API error - will be retried by tenacity
            logger.error(f"Failed to delete {blob_name}: {e}")
            failed += 1

            if audit_logger:
                audit_logger.log_deletion(
                    snapshot,
                    reason="retention_policy_cleanup",
                    success=False,
                    error_message=str(e),
                )

        except Exception as e:
            # Unexpected error - log and continue
            logger.error(f"Unexpected error deleting {blob_name}: {e}")
            failed += 1

            if audit_logger:
                audit_logger.log_deletion(
                    snapshot,
                    reason="retention_policy_cleanup",
                    success=False,
                    error_message=str(e),
                )

    return DeleteResult(
        deleted=deleted,
        failed=failed,
        skipped=skipped,
        size_freed_bytes=size_freed_bytes,
    )


def configure_gcs_retention_policy(
    bucket: "Bucket",
    retention_seconds: int,
    lock_policy: bool = False,
) -> None:
    """
    Configure GCS bucket-level retention policy.

    This sets a minimum retention period for all objects in the bucket.
    Objects cannot be deleted until the retention period expires.

    WARNING: Locking the retention policy is IRREVERSIBLE. Once locked, the retention
    period can only be increased, never decreased or removed.

    Args:
        bucket: GCS bucket instance
        retention_seconds: Minimum retention period in seconds
        lock_policy: Whether to lock the retention policy (IRREVERSIBLE)

    Raises:
        RuntimeError: If policy configuration fails
    """
    try:
        # Set retention period
        bucket.retention_period = retention_seconds
        bucket.patch()

        logger.info(
            f"Configured GCS retention policy: {retention_seconds} seconds "
            f"({retention_seconds // 86400} days)"
        )

        # Lock policy if requested (IRREVERSIBLE!)
        if lock_policy:
            bucket.lock_retention_policy()
            logger.warning(
                "⚠️  LOCKED GCS retention policy (IRREVERSIBLE). "
                "Retention period can only be increased from now on."
            )

    except Exception as e:
        raise RuntimeError(f"Failed to configure GCS retention policy: {e}") from e


def configure_gcs_lifecycle_policy(
    bucket: "Bucket",
    max_age_days: int,
) -> None:
    """
    Configure GCS lifecycle policy for automatic age-based deletion.

    This sets a lifecycle rule that automatically deletes objects older than max_age_days.
    Lifecycle policies are evaluated daily by GCS.

    Args:
        bucket: GCS bucket instance
        max_age_days: Maximum age in days (objects older than this are auto-deleted)

    Raises:
        RuntimeError: If lifecycle policy configuration fails
    """
    try:
        # Define lifecycle rule: delete objects older than max_age_days
        lifecycle_rule = {
            "action": {"type": "Delete"},
            "condition": {"age": max_age_days},
        }

        # Update bucket lifecycle rules
        bucket.lifecycle_rules = [lifecycle_rule]
        bucket.patch()

        logger.info(
            f"Configured GCS lifecycle policy: auto-delete objects older than {max_age_days} days"
        )

    except Exception as e:
        raise RuntimeError(f"Failed to configure GCS lifecycle policy: {e}") from e


def preview_cleanup(
    evaluation: RetentionEvaluation,
    policy: RetentionPolicy,
) -> dict[str, int | float]:
    """
    Generate preview summary of cleanup operation.

    Args:
        evaluation: Retention policy evaluation result
        policy: Retention policy configuration

    Returns:
        Dictionary with preview statistics:
        - total_snapshots: Total number of snapshots
        - protected_count: Number of snapshots to protect
        - delete_count: Number of snapshots to delete
        - size_to_free_mb: Total size to be freed in MB
    """
    protected_count = len(evaluation.snapshots_to_protect)
    delete_count = len(evaluation.snapshots_to_delete)
    total_snapshots = protected_count + delete_count

    # Calculate total size to free
    size_to_free_bytes = sum(s.size_bytes for s in evaluation.snapshots_to_delete)
    size_to_free_mb = round(size_to_free_bytes / (1024 * 1024), 1)

    return {
        "total_snapshots": total_snapshots,
        "protected_count": protected_count,
        "delete_count": delete_count,
        "size_to_free_mb": size_to_free_mb,
        "size_to_free_bytes": size_to_free_bytes,
    }


def validate_safety_threshold(
    snapshots_to_protect: list[SnapshotMetadata],
    min_count: int,
    force: bool = False,
) -> None:
    """
    Validate that cleanup won't delete below minimum backup count threshold.

    Args:
        snapshots_to_protect: List of snapshots that will be protected after cleanup
        min_count: Minimum number of snapshots required
        force: Whether to override safety check

    Raises:
        ValueError: If cleanup would delete below threshold and force=False
    """
    if len(snapshots_to_protect) < min_count and not force:
        raise ValueError(
            f"Safety check failed: Cleanup would leave only {len(snapshots_to_protect)} snapshots, "
            f"but minimum count is {min_count}.\n\n"
            f"This would delete ALL snapshots below the safety threshold.\n\n"
            f"Options:\n"
            f"  1. Adjust retention policy to retain more snapshots\n"
            f"  2. Use --force flag to override this safety check (DANGEROUS)\n"
        )


@retry(
    retry=retry_if_exception_type((GoogleAPICallError,)),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    reraise=True,
)
def delete_snapshot(
    client: storage.Client,
    bucket_name: str,
    snapshot: SnapshotMetadata,
    audit_logger: AuditLogger | None = None,
    reason: str = "manual_deletion",
    dry_run: bool = False,
) -> bool:
    """
    Delete a single snapshot from GCS bucket.

    Args:
        client: Authenticated GCS storage client
        bucket_name: GCS bucket name
        snapshot: Snapshot metadata to delete
        audit_logger: Optional audit logger for recording deletion
        reason: Reason for deletion (for audit log)
        dry_run: If True, skip actual deletion (preview only)

    Returns:
        True if deletion succeeded or was skipped (dry run), False if failed

    Raises:
        RuntimeError: If deletion fails after retries

    Error Handling:
        - Network errors: Retry with exponential backoff
        - Protected snapshots (403 Forbidden): Raise RuntimeError with helpful message
        - Snapshot not found: Log warning and return True (already deleted)
        - Other errors: Raise RuntimeError
    """
    blob_name = snapshot.filename

    try:
        if dry_run:
            logger.info(f"[DRY RUN] Would delete: {blob_name}")
            return True

        # Delete blob from GCS
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        # Check if blob exists before attempting deletion
        if not blob.exists():
            logger.warning(f"Snapshot not found (may have been deleted externally): {blob_name}")
            return True

        # Attempt deletion
        blob.delete()

        logger.info(f"Deleted snapshot: {blob_name} ({snapshot.size_mb} MB)")

        # Audit log successful deletion
        if audit_logger:
            audit_logger.log_deletion(
                snapshot,
                reason=reason,
                success=True,
            )

        return True

    except Forbidden as e:
        # Protected snapshot (e.g., object lock, retention policy)
        error_msg = f"Cannot delete protected snapshot: {blob_name}\n\nGCS protection enabled: {e}"
        logger.error(error_msg)

        if audit_logger:
            audit_logger.log_deletion(
                snapshot,
                reason=reason,
                success=False,
                error_message=f"Protected by GCS: {str(e)}",
            )

        raise RuntimeError(error_msg) from e

    except GoogleAPICallError as e:
        # Network or API error - will be retried by tenacity
        error_msg = f"Failed to delete {blob_name}: {e}"
        logger.error(error_msg)

        if audit_logger:
            audit_logger.log_deletion(
                snapshot,
                reason=reason,
                success=False,
                error_message=str(e),
            )

        raise RuntimeError(error_msg) from e

    except Exception as e:
        # Unexpected error
        error_msg = f"Unexpected error deleting {blob_name}: {e}"
        logger.error(error_msg)

        if audit_logger:
            audit_logger.log_deletion(
                snapshot,
                reason=reason,
                success=False,
                error_message=str(e),
            )

        raise RuntimeError(error_msg) from e
