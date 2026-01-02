"""Dead letter queue operations for storage mixin."""

import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime

from lookervault.exceptions import NotFoundError, StorageError
from lookervault.storage.models import DeadLetterItem
from lookervault.utils import transaction_rollback


class DeadLetterQueueMixin:
    """Mixin providing dead letter queue operations.

    This mixin handles storage, retrieval, listing, counting, and deletion
    of failed restoration items in the DLQ.
    """

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        raise NotImplementedError("Subclass must implement _get_connection")

    def save_dead_letter_item(self, item: DeadLetterItem) -> int:
        """Save or update failed restoration item to DLQ with thread-safe transaction control.

        Uses upsert (INSERT ... ON CONFLICT DO UPDATE) to make DLQ saves idempotent.
        If a DLQ entry with the same (session_id, content_id, content_type, retry_count)
        already exists, it will be updated instead of creating a duplicate.

        Includes retry logic for SQLITE_BUSY errors that can occur in parallel execution.

        Args:
            item: DeadLetterItem object

        Returns:
            DLQ entry ID

        Raises:
            StorageError: If save fails after retries
        """

        def _save_operation() -> int:
            try:
                conn = self._get_connection()
                # BEGIN IMMEDIATE: Thread-safe DLQ writes
                conn.execute("BEGIN IMMEDIATE")

                with transaction_rollback(conn):
                    cursor = conn.cursor()

                    cursor.execute(
                        """
                        INSERT INTO dead_letter_queue (
                            session_id, content_id, content_type, content_data,
                            error_message, error_type, stack_trace, retry_count,
                            failed_at, metadata
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(session_id, content_id, content_type, retry_count) DO UPDATE SET
                            error_message = excluded.error_message,
                            error_type = excluded.error_type,
                            stack_trace = excluded.stack_trace,
                            failed_at = excluded.failed_at,
                            metadata = excluded.metadata,
                            content_data = excluded.content_data
                    """,
                        (
                            item.session_id,
                            item.content_id,
                            item.content_type,
                            item.content_data,
                            item.error_message,
                            item.error_type,
                            item.stack_trace,
                            item.retry_count,
                            item.failed_at.isoformat(),
                            json.dumps(item.metadata) if item.metadata else None,
                        ),
                    )

                    dlq_id: int = cursor.lastrowid or 0
                    conn.commit()
                    return dlq_id
            except sqlite3.Error as e:
                raise StorageError(f"Failed to save dead letter item: {e}") from e

        # Retry operation on SQLITE_BUSY
        return self._retry_on_busy(_save_operation)

    def get_dead_letter_item(self, dlq_id: int) -> DeadLetterItem | None:
        """Retrieve DLQ entry by ID.

        Args:
            dlq_id: Dead letter queue entry ID

        Returns:
            DeadLetterItem if found, None otherwise
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id, session_id, content_id, content_type, content_data,
                       error_message, error_type, stack_trace, retry_count,
                       failed_at, metadata
                FROM dead_letter_queue
                WHERE id = ?
            """,
                (dlq_id,),
            )

            row = cursor.fetchone()
            if not row:
                return None

            return DeadLetterItem(
                id=row["id"],
                session_id=row["session_id"],
                content_id=row["content_id"],
                content_type=row["content_type"],
                content_data=row["content_data"],
                error_message=row["error_message"],
                error_type=row["error_type"],
                stack_trace=row["stack_trace"],
                retry_count=row["retry_count"],
                failed_at=datetime.fromisoformat(row["failed_at"]),
                metadata=json.loads(row["metadata"]) if row["metadata"] else None,
            )
        except sqlite3.Error as e:
            raise StorageError(f"Failed to get dead letter item: {e}") from e

    def list_dead_letter_items(
        self,
        session_id: str | None = None,
        content_type: int | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> Sequence[DeadLetterItem]:
        """List DLQ entries with optional filters.

        Args:
            session_id: Optional session filter
            content_type: Optional content type filter
            limit: Maximum items to return (default: 100)
            offset: Pagination offset (default: 0)

        Returns:
            Sequence of DeadLetterItem objects
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            query = """
                SELECT id, session_id, content_id, content_type, content_data,
                       error_message, error_type, stack_trace, retry_count,
                       failed_at, metadata
                FROM dead_letter_queue
                WHERE 1=1
            """

            params: list[int | str] = []

            if session_id is not None:
                query += " AND session_id = ?"
                params.append(session_id)

            if content_type is not None:
                query += " AND content_type = ?"
                params.append(content_type)

            query += " ORDER BY failed_at DESC LIMIT ? OFFSET ?"
            params.extend([limit if limit is not None else 100, offset])

            cursor.execute(query, params)

            items: list[DeadLetterItem] = []
            for row in cursor.fetchall():
                items.append(
                    DeadLetterItem(
                        id=row["id"],
                        session_id=row["session_id"],
                        content_id=row["content_id"],
                        content_type=row["content_type"],
                        content_data=row["content_data"],
                        error_message=row["error_message"],
                        error_type=row["error_type"],
                        stack_trace=row["stack_trace"],
                        retry_count=row["retry_count"],
                        failed_at=datetime.fromisoformat(row["failed_at"]),
                        metadata=json.loads(row["metadata"]) if row["metadata"] else None,
                    )
                )

            return items
        except sqlite3.Error as e:
            raise StorageError(f"Failed to list dead letter items: {e}") from e

    def count_dead_letter_items(
        self,
        session_id: str | None = None,
        content_type: int | None = None,
    ) -> int:
        """Count DLQ entries with optional filters.

        Args:
            session_id: Optional session filter
            content_type: Optional content type filter

        Returns:
            Total count of matching DLQ entries
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            query = """
                SELECT COUNT(*) as total
                FROM dead_letter_queue
                WHERE 1=1
            """

            params: list[int | str] = []

            if session_id is not None:
                query += " AND session_id = ?"
                params.append(session_id)

            if content_type is not None:
                query += " AND content_type = ?"
                params.append(content_type)

            cursor.execute(query, params)
            row = cursor.fetchone()

            return row["total"] if row else 0
        except sqlite3.Error as e:
            raise StorageError(f"Failed to count dead letter items: {e}") from e

    def delete_dead_letter_item(self, dlq_id: int) -> None:
        """Permanently delete DLQ entry with thread-safe transaction control.

        This is typically called after successful manual retry of a failed item.

        Includes retry logic for SQLITE_BUSY errors that can occur in parallel execution.

        Args:
            dlq_id: Dead letter queue entry ID

        Raises:
            NotFoundError: If DLQ entry doesn't exist
            StorageError: If deletion fails after retries
        """

        def _delete_operation() -> None:
            try:
                conn = self._get_connection()
                # BEGIN IMMEDIATE: Thread-safe DLQ deletion
                conn.execute("BEGIN IMMEDIATE")

                with transaction_rollback(conn):
                    cursor = conn.cursor()

                    cursor.execute(
                        """
                        DELETE FROM dead_letter_queue
                        WHERE id = ?
                    """,
                        (dlq_id,),
                    )

                    if cursor.rowcount == 0:
                        raise NotFoundError(f"Dead letter item not found: {dlq_id}")

                    conn.commit()
            except sqlite3.Error as e:
                raise StorageError(f"Failed to delete dead letter item: {e}") from e

        # Retry operation on SQLITE_BUSY
        self._retry_on_busy(_delete_operation)
