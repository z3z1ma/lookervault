"""Data models for content storage."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any
from uuid import uuid4


class ContentType(IntEnum):
    """Enumeration of Looker content types."""

    DASHBOARD = 1
    LOOK = 2
    LOOKML_MODEL = 3
    EXPLORE = 4
    FOLDER = 5
    BOARD = 6
    USER = 7
    GROUP = 8
    ROLE = 9
    PERMISSION_SET = 10
    MODEL_SET = 11
    SCHEDULED_PLAN = 12


class SessionStatus(str):
    """Enumeration of extraction session statuses."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ContentItem:
    """Represents a single content item from Looker."""

    id: str
    content_type: int
    name: str
    created_at: datetime
    updated_at: datetime
    content_data: bytes
    owner_id: int | None = None
    owner_email: str | None = None
    synced_at: datetime | None = None
    deleted_at: datetime | None = None
    content_size: int | None = None
    folder_id: str | None = None

    def __post_init__(self):
        """Auto-calculate fields if not provided."""
        if self.synced_at is None:
            self.synced_at = datetime.now()
        if self.content_size is None:
            self.content_size = len(self.content_data)


@dataclass
class Checkpoint:
    """Represents an extraction checkpoint for resume capability."""

    content_type: int
    checkpoint_data: dict
    started_at: datetime = field(default_factory=datetime.now)
    id: int | None = None
    session_id: str | None = None
    completed_at: datetime | None = None
    item_count: int = 0
    error_message: str | None = None


@dataclass
class ExtractionSession:
    """Represents an extraction session for tracking and auditing."""

    id: str = field(default_factory=lambda: str(uuid4()))
    started_at: datetime = field(default_factory=datetime.now)
    status: str = SessionStatus.PENDING
    total_items: int = 0
    error_count: int = 0
    completed_at: datetime | None = None
    config: dict | None = None
    metadata: dict | None = None


@dataclass
class RestorationSession:
    """Represents a single restoration operation."""

    id: str = field(default_factory=lambda: str(uuid4()))
    started_at: datetime = field(default_factory=datetime.now)
    status: str = SessionStatus.PENDING
    total_items: int = 0
    success_count: int = 0
    error_count: int = 0
    destination_instance: str = ""
    source_instance: str | None = None
    completed_at: datetime | None = None
    config: dict | None = None
    metadata: dict | None = None

    def __post_init__(self):
        """Validate status is valid."""
        valid_statuses = {"pending", "running", "completed", "failed", "cancelled"}
        if self.status not in valid_statuses:
            raise ValueError(f"Invalid status: {self.status}")


@dataclass
class RestorationCheckpoint:
    """Tracks progress within a restoration session for resume capability."""

    content_type: int
    checkpoint_data: dict
    started_at: datetime = field(default_factory=datetime.now)
    id: int | None = None
    session_id: str | None = None
    completed_at: datetime | None = None
    item_count: int = 0
    error_count: int = 0


@dataclass
class IDMapping:
    """Maps source content IDs to destination content IDs for cross-instance migration."""

    source_instance: str
    content_type: int
    source_id: str
    destination_id: str
    created_at: datetime = field(default_factory=datetime.now)
    session_id: str | None = None


@dataclass
class DeadLetterItem:
    """Represents a content item that failed restoration after all retries."""

    session_id: str
    content_id: str
    content_type: int
    content_data: bytes
    error_message: str
    error_type: str
    retry_count: int
    failed_at: datetime = field(default_factory=datetime.now)
    id: int | None = None
    stack_trace: str | None = None
    metadata: dict | None = None


@dataclass
class RestorationTask:
    """Represents a single content item to be restored (in-memory work unit)."""

    content_id: str
    content_type: int
    content_data: bytes | None = None
    status: str = "pending"
    priority: int = 0
    retry_count: int = 0
    error_message: str | None = None
    name: str | None = None
    owner_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class RestorationResult:
    """Result of a single content restoration attempt.

    Attributes:
        content_id: Original content ID from backup
        content_type: ContentType enum value
        status: Result status - "success", "created", "updated", "failed", "skipped"
        destination_id: Looker ID in destination instance (populated on success)
        error_message: Error details if status is "failed"
        retry_count: Number of retry attempts made
        duration_ms: Time taken for restoration operation in milliseconds
        metadata: Optional dict containing additional restoration metadata (e.g., sub-resource counts)

    Examples:
        >>> # Successful creation
        >>> result = RestorationResult(
        ...     content_id="123",
        ...     content_type=ContentType.DASHBOARD,
        ...     status="created",
        ...     destination_id="456",
        ...     duration_ms=1234.5,
        ... )

        >>> # Failed restoration
        >>> result = RestorationResult(
        ...     content_id="789",
        ...     content_type=ContentType.LOOK,
        ...     status="failed",
        ...     error_message="Missing folder_id dependency",
        ...     retry_count=3,
        ... )

        >>> # Dashboard restoration with sub-resource metadata
        >>> result = RestorationResult(
        ...     content_id="42",
        ...     content_type=ContentType.DASHBOARD,
        ...     status="updated",
        ...     destination_id="42",
        ...     duration_ms=5678.9,
        ...     metadata={"subresources": {"filters": {"updated": 3}, "elements": {"created": 2}}},
        ... )
    """

    content_id: str
    content_type: int
    status: str  # "success", "created", "updated", "failed", "skipped"
    destination_id: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    duration_ms: float | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class RestorationSummary:
    """Summary of completed restoration session.

    Aggregates results from all restoration attempts in a session, providing
    high-level metrics and breakdowns by content type and error type.

    Attributes:
        session_id: Unique restoration session identifier
        total_items: Total items attempted (successful + failed + skipped)
        success_count: Successfully restored items (created + updated)
        created_count: Items created in destination instance
        updated_count: Items updated in destination instance
        error_count: Items that failed after all retries
        skipped_count: Items skipped (e.g., due to skip_if_modified)
        duration_seconds: Total session duration in seconds
        average_throughput: Average items restored per second
        content_type_breakdown: Count of items by content type
        error_breakdown: Count of errors by error type

    Examples:
        >>> # Successful bulk restoration
        >>> summary = RestorationSummary(
        ...     session_id="abc-123",
        ...     total_items=1000,
        ...     success_count=995,
        ...     created_count=800,
        ...     updated_count=195,
        ...     error_count=5,
        ...     skipped_count=0,
        ...     duration_seconds=10.5,
        ...     average_throughput=95.2,
        ...     content_type_breakdown={1: 500, 2: 500},
        ...     error_breakdown={"DependencyError": 3, "ValidationError": 2},
        ... )
    """

    session_id: str
    total_items: int
    success_count: int
    created_count: int
    updated_count: int
    error_count: int
    skipped_count: int
    duration_seconds: float
    average_throughput: float  # Items per second
    content_type_breakdown: dict[int, int]  # ContentType -> count
    error_breakdown: dict[str, int]  # Error type -> count


class DependencyOrder(IntEnum):
    """Defines restoration order based on Looker resource dependencies.

    Lower values are restored first (e.g., USERS before DASHBOARDS).
    """

    USERS = 1
    GROUPS = 2
    PERMISSION_SETS = 3
    MODEL_SETS = 4
    ROLES = 5
    FOLDERS = 6
    LOOKML_MODELS = 7
    LOOKS = 8
    DASHBOARDS = 9
    BOARDS = 10
    SCHEDULED_PLANS = 11
