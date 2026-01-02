"""Content repository for SQLite storage operations.

This module provides the abstract base class and concrete implementation
for content storage using SQLite. The implementation uses a modular
mixin-based architecture where each domain (content, checkpoints, sessions,
etc.) is implemented as a separate mixin class.

The main SQLiteContentRepository class inherits from all mixins, providing
a unified API while keeping the implementation organized and maintainable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from typing import TypeVar

from lookervault.storage._mixins.base import DatabaseConnectionMixin
from lookervault.storage._mixins.content import ContentMixin
from lookervault.storage._mixins.dead_letter_queue import DeadLetterQueueMixin
from lookervault.storage._mixins.extraction_checkpoints import ExtractionCheckpointsMixin
from lookervault.storage._mixins.extraction_sessions import ExtractionSessionsMixin
from lookervault.storage._mixins.id_mappings import IDMappingsMixin
from lookervault.storage._mixins.restoration_checkpoints import RestorationCheckpointsMixin
from lookervault.storage._mixins.restoration_sessions import RestorationSessionsMixin
from lookervault.storage._mixins.utils import StorageUtilsMixin
from lookervault.storage.models import (
    Checkpoint,
    ContentItem,
    DeadLetterItem,
    ExtractionSession,
    RestorationCheckpoint,
)

T = TypeVar("T")


class ContentRepository(ABC):
    """Abstract base class for content storage operations."""

    @abstractmethod
    def save_content(self, item: ContentItem) -> None:
        """Save or update a content item in the storage repository.

        This method provides an idempotent way to persist content items. If an item with the same
        ID already exists, it will be updated with the new content details. If no existing item is
        found, a new item will be created.

        This method is typically used during content extraction and syncing processes to maintain
        a comprehensive local representation of Looker content.

        Args:
            item: A ContentItem object representing the Looker content to be saved.
                  This includes metadata like ID, name, owner, timestamps, and the actual content data.

        Raises:
            StorageError: If the save operation encounters a database-related error,
                          such as connection issues, constraint violations, or transaction failures.

        Examples:
            >>> repository.save_content(
            ...     ContentItem(
            ...         id="dashboard_123",
            ...         name="Sales Performance Dashboard",
            ...         content_type=ContentType.DASHBOARD.value,
            ...         content_data=dashboard_json,
            ...         created_at=datetime.now(),
            ...         updated_at=datetime.now(),
            ...     )
            ... )
        """
        ...

    @abstractmethod
    def get_content(self, content_id: str) -> ContentItem | None:
        """Retrieve a specific content item from the storage repository by its unique identifier.

        This method allows for fetching a single content item using its unique ID. It returns the full
        content details if found, or None if no matching content exists.

        Args:
            content_id: A unique string identifier for the content item.
                        This is typically the original Looker content ID.

        Returns:
            A ContentItem object containing the full details of the requested content,
            or None if no content is found with the given ID.

        Raises:
            StorageError: If there's an error accessing the storage during retrieval.

        Examples:
            >>> dashboard = repository.get_content("dashboard_123")
            >>> if dashboard:
            ...     print(f"Dashboard Name: {dashboard.name}")
            >>> # If no dashboard found, returns None

            >>> # Handling potential storage errors
            >>> try:
            ...     content = repository.get_content("dashboard_456")
            ... except StorageError as e:
            ...     print(f"Could not retrieve content: {e}")
        """
        ...

    @abstractmethod
    def list_content(
        self,
        content_type: int,
        include_deleted: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> Sequence[ContentItem]:
        """Retrieve a list of content items filtered by content type with optional pagination.

        This method allows fetching a collection of content items with flexible filtering and
        pagination support. By default, it returns only non-deleted items, but can be configured
        to include soft-deleted items as well.

        The method is typically used for bulk content retrieval, supporting scenarios like content
        export, migration, or comprehensive content analysis.

        Args:
            content_type: An integer representing the content type (e.g., DASHBOARD, LOOK).
                          Use ContentType enum values to specify the desired content type.
            include_deleted: If True, includes soft-deleted items in the result.
                             If False (default), only returns active (non-deleted) items.
            limit: Maximum number of items to return. Useful for pagination and
                   preventing large memory allocations. If None, returns all matching items.
            offset: Number of items to skip before starting to return results.
                    Used for pagination to implement page-based content retrieval.

        Returns:
            A sequence of ContentItem objects matching the specified criteria.
            Items are ordered by their update timestamp in descending order.

        Raises:
            StorageError: If there's an error accessing the storage during retrieval.

        Examples:
            >>> # Retrieve all active dashboards
            >>> dashboards = repository.list_content(
            ...     content_type=ContentType.DASHBOARD.value, limit=100, offset=0
            ... )
            >>> print(f"Found {len(dashboards)} dashboards")

            >>> # Include soft-deleted looks with pagination
            >>> deleted_looks = repository.list_content(
            ...     content_type=ContentType.LOOK.value, include_deleted=True, limit=50, offset=100
            ... )
            >>> for look in deleted_looks:
            ...     print(f"Deleted Look: {look.name}")
        """
        ...

    @abstractmethod
    def count_content(
        self,
        content_type: int,
        include_deleted: bool = False,
    ) -> int:
        """Count the number of content items for a specific content type.

        This method provides a quick way to determine the total number of items
        for a given content type. By default, it only counts active (non-deleted) items,
        but can be configured to include soft-deleted items as well.

        Useful for generating statistics, understanding content volume, or
        implementing pagination logic in content retrieval workflows.

        Args:
            content_type: An integer representing the content type (e.g., DASHBOARD, LOOK).
                          Use ContentType enum values to specify the desired content type.
            include_deleted: If True, includes soft-deleted items in the count.
                             If False (default), only counts active (non-deleted) items.

        Returns:
            The total number of content items matching the specified criteria.

        Raises:
            StorageError: If there's an error accessing the storage during counting.

        Examples:
            >>> # Count active dashboards
            >>> dashboard_count = repository.count_content(content_type=ContentType.DASHBOARD.value)
            >>> print(f"Total active dashboards: {dashboard_count}")

            >>> # Count all dashboards, including soft-deleted
            >>> total_dashboard_count = repository.count_content(
            ...     content_type=ContentType.DASHBOARD.value, include_deleted=True
            ... )
            >>> print(f"Total dashboards (including deleted): {total_dashboard_count}")
        """
        ...

    @abstractmethod
    def delete_content(self, content_id: str, soft: bool = True) -> None:
        """Delete a content item from the storage repository.

        This method provides two deletion strategies:
        1. Soft Delete (default): Marks the content as deleted without removing it from the database.
           Allows for potential recovery and maintains historical record.
        2. Hard Delete: Permanently removes the content item from the database.

        Soft delete is recommended in most cases to preserve data integrity and
        support potential restoration or auditing workflows.

        Args:
            content_id: A unique string identifier for the content item to be deleted.
                        This is typically the original Looker content ID.
            soft: Deletion strategy flag:
                  - True (default): Performs a soft delete by setting a deletion timestamp
                  - False: Permanently removes the content item from the database

        Raises:
            NotFoundError: If no content item is found with the specified content_id.
                           This prevents silent failures when attempting to delete
                           non-existent content.
            StorageError: If there's an error during the deletion process, such as
                          database connection issues or transaction failures.

        Examples:
            >>> # Soft delete a dashboard
            >>> repository.delete_content("dashboard_123")
            >>> # Hard delete a look
            >>> repository.delete_content("look_456", soft=False)

            >>> # Handling potential errors
            >>> try:
            ...     repository.delete_content("nonexistent_789")
            ... except NotFoundError as e:
            ...     print(f"Deletion failed: {e}")
        """
        ...

    @abstractmethod
    def save_checkpoint(self, checkpoint: Checkpoint) -> int:
        """Save an extraction checkpoint to enable resumable content synchronization.

        This method allows storing detailed information about a specific extraction process,
        capturing its progress, state, and potential errors. It supports resumable extraction
        by providing a mechanism to track and recover interrupted sync processes.

        Key features:
        - Idempotent checkpoint saving
        - Captures comprehensive extraction state
        - Supports retrying or resuming interrupted extractions
        - Thread-safe with optimized transaction handling

        Args:
            checkpoint: A Checkpoint object containing extraction session metadata.
                        This includes:
                        - session_id: Unique identifier for the extraction session
                        - content_type: Type of content being extracted
                        - checkpoint_data: Arbitrary JSON-serializable state data
                        - started_at: Timestamp when extraction began
                        - completed_at: Optional timestamp of extraction completion
                        - item_count: Number of items processed during this checkpoint
                        - error_message: Optional error details if extraction encountered issues

        Returns:
            An integer representing the unique database ID of the saved checkpoint.
            This ID can be used for future reference, updating, or resuming the checkpoint.

        Raises:
            StorageError: If the checkpoint cannot be saved due to:
                          - Database connection issues
                          - Transaction failures
                          - Constraint violations
                          - Other database-related errors

        Examples:
            >>> # Save a checkpoint during dashboard extraction
            >>> checkpoint = Checkpoint(
            ...     session_id="extraction_2025_06_15",
            ...     content_type=ContentType.DASHBOARD.value,
            ...     checkpoint_data={"last_processed_id": "dashboard_456"},
            ...     started_at=datetime.now(),
            ...     item_count=50,
            ... )
            >>> checkpoint_id = repository.save_checkpoint(checkpoint)
            >>> print(f"Checkpoint saved with ID: {checkpoint_id}")

            >>> # Handling potential storage errors
            >>> try:
            ...     repository.save_checkpoint(checkpoint)
            ... except StorageError as e:
            ...     print(f"Checkpoint save failed: {e}")
        """
        ...

    @abstractmethod
    def get_latest_checkpoint(
        self, content_type: int, session_id: str | None = None
    ) -> Checkpoint | None:
        """Get most recent incomplete checkpoint for content type.

        Args:
            content_type: ContentType enum value
            session_id: Optional session filter

        Returns:
            Latest Checkpoint or None
        """
        ...

    @abstractmethod
    def update_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Update existing checkpoint.

        Args:
            checkpoint: Checkpoint object with updated values

        Raises:
            StorageError: If update fails
        """
        ...

    @abstractmethod
    def create_session(self, session: ExtractionSession) -> None:
        """Create new extraction session."""
        ...

    @abstractmethod
    def update_session(self, session: ExtractionSession) -> None:
        """Update existing extraction session."""
        ...

    @abstractmethod
    def get_last_sync_timestamp(self, content_type: int) -> datetime | None:
        """Get the timestamp of the last successful extraction for a content type.

        Args:
            content_type: ContentType enum value

        Returns:
            Datetime of last sync, or None if never synced
        """
        ...

    @abstractmethod
    def get_content_ids(self, content_type: int) -> set[str]:
        """Get all content IDs for a content type (excluding deleted).

        Args:
            content_type: ContentType enum value

        Returns:
            Set of content IDs
        """
        ...

    @abstractmethod
    def get_content_ids_in_folders(
        self, content_type: int, folder_ids: set[str], include_deleted: bool = False
    ) -> set[str]:
        """Get content IDs belonging to specified folders.

        Args:
            content_type: ContentType enum value
            folder_ids: Set of folder IDs to filter by
            include_deleted: Include soft-deleted items

        Returns:
            Set of content IDs in the specified folders

        Raises:
            ValueError: If content_type doesn't support folder filtering
        """
        ...

    @abstractmethod
    def list_content_in_folders(
        self,
        content_type: int,
        folder_ids: set[str],
        include_deleted: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> Sequence[ContentItem]:
        """List content items within specified folders.

        Args:
            content_type: ContentType enum value
            folder_ids: Set of folder IDs to filter by
            include_deleted: Include soft-deleted items
            limit: Maximum items to return
            offset: Pagination offset

        Returns:
            Sequence of ContentItem objects in the specified folders

        Raises:
            ValueError: If content_type doesn't support folder filtering
        """
        ...

    @abstractmethod
    def get_schema_version(self) -> int:
        """Get current database schema version.

        Returns:
            Current schema version number

        Raises:
            StorageError: If schema version cannot be retrieved
        """
        ...

    # Dead letter queue methods
    @abstractmethod
    def save_dead_letter_item(self, item: DeadLetterItem) -> int:
        """Save or update failed restoration item to DLQ."""
        ...

    @abstractmethod
    def get_dead_letter_item(self, dlq_id: int) -> DeadLetterItem | None:
        """Retrieve DLQ entry by ID."""
        ...

    @abstractmethod
    def list_dead_letter_items(
        self,
        session_id: str | None = None,
        content_type: int | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> Sequence[DeadLetterItem]:
        """List DLQ entries with optional filters."""
        ...

    @abstractmethod
    def delete_dead_letter_item(self, dlq_id: int) -> None:
        """Permanently delete DLQ entry."""
        ...

    @abstractmethod
    def count_dead_letter_items(
        self,
        session_id: str | None = None,
        content_type: int | None = None,
    ) -> int:
        """Count DLQ entries matching filters."""
        ...

    # Restoration checkpoint methods
    @abstractmethod
    def save_restoration_checkpoint(self, checkpoint: RestorationCheckpoint) -> int:
        """Save or update restoration checkpoint."""
        ...

    @abstractmethod
    def get_latest_restoration_checkpoint(
        self, content_type: int, session_id: str | None = None
    ) -> RestorationCheckpoint | None:
        """Get most recent incomplete checkpoint for content type."""
        ...

    # Thread-local connection management
    @abstractmethod
    def close_thread_connection(self) -> None:
        """Close database connection for current thread."""
        ...


class SQLiteContentRepository(
    DatabaseConnectionMixin,
    ContentMixin,
    ExtractionCheckpointsMixin,
    ExtractionSessionsMixin,
    RestorationCheckpointsMixin,
    RestorationSessionsMixin,
    DeadLetterQueueMixin,
    IDMappingsMixin,
    StorageUtilsMixin,
    ContentRepository,
):
    """Thread-safe SQLite-based content repository implementation.

    Uses thread-local connections to enable parallel access from multiple worker threads.
    Each thread gets its own SQLite connection to prevent concurrency issues.

    The implementation is composed of multiple mixins, each handling a specific domain:
    - DatabaseConnectionMixin: Connection management and retry logic
    - ContentMixin: Content CRUD operations
    - ExtractionCheckpointsMixin: Extraction checkpoint operations
    - ExtractionSessionsMixin: Extraction session operations
    - RestorationCheckpointsMixin: Restoration checkpoint operations
    - RestorationSessionsMixin: Restoration session operations
    - DeadLetterQueueMixin: Dead letter queue operations
    - IDMappingsMixin: ID mapping operations
    - StorageUtilsMixin: Utility methods

    This modular architecture keeps the code organized and maintainable while
    providing a unified API through the ContentRepository interface.
    """

    pass
