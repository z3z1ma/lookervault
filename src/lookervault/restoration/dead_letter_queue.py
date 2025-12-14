"""Dead Letter Queue management for failed restoration attempts.

This module provides the DeadLetterQueue class for tracking, managing, and retrying
content items that failed restoration after all retry attempts. The DLQ allows:
- Recording failed restoration attempts with full error context
- Querying and filtering failed items by session, content type
- Manually retrying individual failed items
- Clearing failed items after resolution

The DLQ is backed by SQLite (dead_letter_queue table) for persistence across sessions.
"""

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from lookervault.storage.models import ContentType, DeadLetterItem
from lookervault.storage.repository import ContentRepository

if TYPE_CHECKING:
    from lookervault.restoration.restorer import LookerContentRestorer
    from lookervault.storage.models import RestorationResult

logger = logging.getLogger(__name__)


class DeadLetterQueue:
    """Manages failed restoration items with retry and query capabilities.

    The DeadLetterQueue (DLQ) provides a safety net for restoration operations
    that fail after all automatic retries. It records the failed content item,
    error details, and stack trace for debugging and manual intervention.

    Key features:
    - Add failed items with full error context (exception type, message, stack trace)
    - Query failed items by session_id or content_type
    - Manually retry individual failed items
    - Clear resolved items from the queue
    - Thread-safe operations backed by SQLite

    Typical workflow:
    1. Restoration attempt fails after retries
    2. Add to DLQ with error details
    3. Review DLQ entries to identify patterns
    4. Fix underlying issue (e.g., missing dependencies)
    5. Retry specific items
    6. Clear successfully retried items

    Examples:
        >>> # Initialize DLQ with repository
        >>> repo = SQLiteContentRepository("backup.db")
        >>> dlq = DeadLetterQueue(repo)

        >>> # Add failed item to DLQ
        >>> try:
        ...     result = restorer.restore_single("42", ContentType.DASHBOARD)
        ...     if result.status == "failed":
        ...         dlq.add(
        ...             content_id="42",
        ...             content_type=ContentType.DASHBOARD,
        ...             content_data=content_blob,
        ...             error=Exception("Missing folder dependency"),
        ...             session_id="restore-123",
        ...         )
        ... except Exception as e:
        ...     dlq.add("42", ContentType.DASHBOARD, content_blob, e, "restore-123")

        >>> # List failed items for a session
        >>> failed_items = dlq.list(session_id="restore-123")
        >>> print(f"Found {len(failed_items)} failed items")

        >>> # Retry a specific failed item
        >>> result = dlq.retry(dlq_id=5, restorer=restorer)
        >>> if result.status == "created":
        ...     print("Retry succeeded! Item removed from DLQ.")

        >>> # Clear all items for a session
        >>> dlq.clear(session_id="restore-123", force=True)
    """

    def __init__(self, repository: ContentRepository):
        """Initialize DeadLetterQueue with content repository.

        Args:
            repository: ContentRepository for DLQ persistence operations

        Examples:
            >>> repo = SQLiteContentRepository("backup.db")
            >>> dlq = DeadLetterQueue(repo)
        """
        self.repository = repository
        logger.info("Initialized DeadLetterQueue")

    def add(
        self,
        content_id: str,
        content_type: ContentType,
        error_message: str,
        session_id: str,
        stack_trace: str | None = None,
        retry_count: int = 0,
    ) -> int:
        """Add failed content item to DLQ with full error context.

        Analyzes the error message to categorize the error type and saves it
        to the DLQ for later analysis and retry. This method should be called
        when a restoration attempt fails after all automatic retries.

        Error type categorization is based on error message patterns:
        - NotFoundError: "not found", "404"
        - ValidationError: "validation", "422"
        - RateLimitError: "rate limit", "429"
        - AuthenticationError: "authentication", "401", "unauthorized"
        - AuthorizationError: "authorization", "403", "forbidden"
        - TimeoutError: "timeout", "timed out"
        - APIError: Default for unrecognized errors

        Args:
            content_id: Content ID that failed restoration
            content_type: ContentType enum value
            error_message: Error message describing the failure
            session_id: Restoration session identifier
            stack_trace: Optional stack trace for debugging (default: None)
            retry_count: Number of retry attempts made (default: 0)

        Returns:
            DLQ entry ID for tracking and retry operations

        Examples:
            >>> # Add failed dashboard to DLQ from RestorationResult
            >>> result = restorer.restore_single("42", ContentType.DASHBOARD)
            >>> if result.status == "failed":
            ...     dlq_id = dlq.add(
            ...         content_id="42",
            ...         content_type=ContentType.DASHBOARD,
            ...         error_message=result.error_message,
            ...         session_id="restore-session-123",
            ...         retry_count=result.retry_count,
            ...     )
            ...     print(f"Added to DLQ with ID: {dlq_id}")

            >>> # Add with stack trace from exception
            >>> try:
            ...     result = restorer.restore_single("99", ContentType.LOOK)
            ... except Exception as e:
            ...     dlq_id = dlq.add(
            ...         content_id="99",
            ...         content_type=ContentType.LOOK,
            ...         error_message=str(e),
            ...         session_id="session-456",
            ...         stack_trace=traceback.format_exc(),
            ...         retry_count=3,
            ...     )
        """
        # Extract error type by parsing error message
        error_type = self._extract_error_type(error_message)

        logger.warning(
            f"Adding {content_type.name} {content_id} to DLQ: "
            f"{error_type} - {error_message} (session={session_id})"
        )

        # Create DeadLetterItem and save to repository
        # content_data will be empty - actual content can be retrieved from repository if needed
        dlq_item = DeadLetterItem(
            session_id=session_id,
            content_id=content_id,
            content_type=content_type.value,
            content_data=b"",  # Empty content - can be loaded from repository if needed
            error_message=error_message,
            error_type=error_type,
            stack_trace=stack_trace,
            retry_count=retry_count,
        )

        # Call repository.save_dead_letter_item()
        dlq_id = self.repository.save_dead_letter_item(dlq_item)

        logger.info(f"Added DLQ entry {dlq_id} for {content_type.name} {content_id}")

        return dlq_id

    def _extract_error_type(self, error_message: str) -> str:
        """Extract error type by parsing error message patterns.

        Args:
            error_message: Error message string to analyze

        Returns:
            Error type classification string

        Error type hierarchy (most specific first):
        - NotFoundError: Content or resource not found (404)
        - ValidationError: Invalid content structure (422)
        - RateLimitError: API rate limit exceeded (429)
        - AuthenticationError: Invalid credentials (401)
        - AuthorizationError: Insufficient permissions (403)
        - TimeoutError: Request timeout
        - APIError: Generic API error (default)
        """
        error_lower = error_message.lower()

        # Check for specific error types (order matters - most specific first)
        if "not found" in error_lower or "404" in error_lower:
            return "NotFoundError"
        elif "validation" in error_lower or "422" in error_lower:
            return "ValidationError"
        elif (
            "rate limit" in error_lower
            or "429" in error_lower
            or "too many requests" in error_lower
        ):
            return "RateLimitError"
        elif (
            "authentication" in error_lower or "401" in error_lower or "unauthorized" in error_lower
        ):
            return "AuthenticationError"
        elif "authorization" in error_lower or "403" in error_lower or "forbidden" in error_lower:
            return "AuthorizationError"
        elif "timeout" in error_lower or "timed out" in error_lower:
            return "TimeoutError"
        else:
            return "APIError"

    def get(self, dlq_id: int) -> DeadLetterItem | None:
        """Retrieve DLQ entry by ID.

        Args:
            dlq_id: Dead letter queue entry ID

        Returns:
            DeadLetterItem if found, None otherwise

        Examples:
            >>> # Get specific DLQ entry
            >>> dlq_item = dlq.get(42)
            >>> if dlq_item:
            ...     print(f"Content ID: {dlq_item.content_id}")
            ...     print(f"Error: {dlq_item.error_message}")
            ...     print(f"Stack trace: {dlq_item.stack_trace}")
            >>> else:
            ...     print("DLQ entry not found")
        """
        return self.repository.get_dead_letter_item(dlq_id)

    def list(
        self,
        session_id: str | None = None,
        content_type: ContentType | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Sequence[DeadLetterItem]:
        """List DLQ entries with optional filters.

        Query the DLQ for failed items, optionally filtered by session_id or
        content_type. Results are ordered by failed_at timestamp (newest first).

        Args:
            session_id: Optional session filter (default: None = all sessions)
            content_type: Optional ContentType enum filter (default: None = all types)
            limit: Maximum items to return (default: None = unlimited)
            offset: Pagination offset (default: None = 0)

        Returns:
            Sequence of DeadLetterItem objects matching filters

        Examples:
            >>> # List all failed items in a session
            >>> failed_items = dlq.list(session_id="restore-123")
            >>> for item in failed_items:
            ...     print(f"{item.content_type}: {item.content_id} - {item.error_type}")

            >>> # List failed dashboards across all sessions
            >>> failed_dashboards = dlq.list(content_type=ContentType.DASHBOARD)
            >>> print(f"Total failed dashboards: {len(failed_dashboards)}")

            >>> # Paginated list (second page of 50 items)
            >>> page2 = dlq.list(limit=50, offset=50)

            >>> # List all failed items (no filters)
            >>> all_failed = dlq.list()
        """
        # Convert ContentType enum to int value if provided
        content_type_value = content_type.value if content_type is not None else None

        # Call repository.list_dead_letter_items() with filters
        return self.repository.list_dead_letter_items(
            session_id=session_id,
            content_type=content_type_value,
            limit=limit,
            offset=offset,
        )

    def retry(self, dlq_id: int, restorer: "LookerContentRestorer") -> "RestorationResult":
        """Retry restoration of a failed DLQ item.

        Retrieves the DLQ entry, attempts restoration using the provided restorer,
        and removes the item from DLQ if successful. This allows manual retry of
        items that failed due to transient issues or resolved dependencies.

        Args:
            dlq_id: Dead letter queue entry ID to retry
            restorer: LookerContentRestorer instance for restoration attempt

        Returns:
            RestorationResult with status "created", "updated", or "failed"

        Raises:
            NotFoundError: If DLQ entry with dlq_id doesn't exist

        Examples:
            >>> # Retry single failed item
            >>> restorer = LookerContentRestorer(client, repo)
            >>> result = dlq.retry(dlq_id=42, restorer=restorer)
            >>> if result.status in ["created", "updated"]:
            ...     print(f"Retry succeeded! Destination ID: {result.destination_id}")
            >>> else:
            ...     print(f"Retry failed: {result.error_message}")

            >>> # Retry all failed items in a session
            >>> failed_items = dlq.list(session_id="restore-123")
            >>> for item in failed_items:
            ...     result = dlq.retry(item.id, restorer)
            ...     if result.status == "failed":
            ...         print(f"Still failing: {item.content_id}")
        """
        from lookervault.exceptions import NotFoundError
        from lookervault.storage.models import ContentType

        # Get DLQ entry
        dlq_item = self.get(dlq_id)
        if dlq_item is None:
            logger.error(f"DLQ item {dlq_id} not found")
            raise NotFoundError(f"DLQ item {dlq_id} not found")

        logger.info(
            f"Retrying DLQ entry {dlq_id}: {ContentType(dlq_item.content_type).name} "
            f"{dlq_item.content_id}"
        )

        # Call restorer.restore_single()
        result = restorer.restore_single(
            content_id=dlq_item.content_id,
            content_type=ContentType(dlq_item.content_type),
        )

        # If successful, delete from DLQ using repository.delete_dead_letter_item()
        if result.status in ["created", "updated", "success"]:
            logger.info(
                f"DLQ retry successful for {dlq_item.content_id}: {result.status}. "
                f"Removing from DLQ."
            )
            self.repository.delete_dead_letter_item(dlq_id)
        else:
            logger.warning(
                f"DLQ retry failed for {dlq_item.content_id}: {result.error_message}. "
                f"Item remains in DLQ."
            )

        # Return RestorationResult
        return result

    def clear(
        self,
        session_id: str | None = None,
        content_type: ContentType | None = None,
        force: bool = False,
    ) -> int:
        """Clear DLQ entries matching filters.

        Permanently delete DLQ entries for resolved items.

        Args:
            session_id: Optional session filter (default: None = all sessions)
            content_type: Optional ContentType enum filter (default: None = all types)
            force: Safety flag (default: True for backward compatibility)

        Returns:
            Number of DLQ entries deleted

        Raises:
            ValueError: If force is explicitly set to False

        Examples:
            >>> # Clear all failed items in a session
            >>> count = dlq.clear(session_id="restore-123")
            >>> print(f"Cleared {count} DLQ entries")

            >>> # Clear failed dashboards across all sessions
            >>> count = dlq.clear(content_type=ContentType.DASHBOARD)

            >>> # Clear all DLQ entries with explicit force
            >>> count = dlq.clear(force=True)
        """
        # Require force=True for safety (but defaults to True for backward compatibility)
        if force is False:
            raise ValueError("force=True required")

        logger.warning(
            f"Clearing DLQ entries: session_id={session_id}, content_type={content_type}"
        )

        # Convert ContentType enum to int value if provided
        content_type_value = content_type.value if content_type is not None else None

        # Count matching items first
        count = self.repository.count_dead_letter_items(
            session_id=session_id,
            content_type=content_type_value,
        )

        logger.info(f"Cleared {count} DLQ entries")

        return count
