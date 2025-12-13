"""Data models for content storage."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
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
