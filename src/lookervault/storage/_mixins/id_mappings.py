"""ID mapping operations for storage mixin."""

import sqlite3
from collections.abc import Sequence
from datetime import datetime

from lookervault.exceptions import StorageError
from lookervault.storage.models import IDMapping
from lookervault.utils import transaction_rollback


class IDMappingsMixin:
    """Mixin providing ID mapping operations for cross-instance restoration.

    This mixin handles storage, retrieval, batch queries, and cleanup
    of source ID → destination ID mappings for cross-instance content restoration.
    """

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        raise NotImplementedError("Subclass must implement _get_connection")

    def save_id_mapping(self, mapping: IDMapping) -> None:
        """Save source ID → destination ID mapping with thread-safe transaction control.

        Args:
            mapping: IDMapping object to persist

        Raises:
            StorageError: If save fails after retries
        """

        def _save_operation() -> None:
            try:
                conn = self._get_connection()
                # BEGIN IMMEDIATE: Acquire write lock immediately to prevent deadlocks
                conn.execute("BEGIN IMMEDIATE")

                with transaction_rollback(conn):
                    cursor = conn.cursor()

                    cursor.execute(
                        """
                        INSERT INTO id_mappings (
                            source_instance, content_type, source_id,
                            destination_id, created_at, session_id
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(source_instance, content_type, source_id) DO UPDATE SET
                            destination_id = excluded.destination_id,
                            created_at = excluded.created_at,
                            session_id = excluded.session_id
                    """,
                        (
                            mapping.source_instance,
                            mapping.content_type,
                            mapping.source_id,
                            mapping.destination_id,
                            mapping.created_at.isoformat(),
                            mapping.session_id,
                        ),
                    )
                    conn.commit()
            except sqlite3.Error as e:
                raise StorageError(f"Failed to save ID mapping: {e}") from e

        # Retry operation on SQLITE_BUSY
        self._retry_on_busy(_save_operation)

    def get_id_mapping(
        self, source_instance: str, content_type: int, source_id: str
    ) -> IDMapping | None:
        """Retrieve ID mapping for source content.

        Args:
            source_instance: Source Looker instance URL
            content_type: ContentType enum value
            source_id: Original ID from source instance

        Returns:
            IDMapping if found, None otherwise
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT source_instance, content_type, source_id,
                       destination_id, created_at, session_id
                FROM id_mappings
                WHERE source_instance = ? AND content_type = ? AND source_id = ?
            """,
                (source_instance, content_type, source_id),
            )

            row = cursor.fetchone()
            if not row:
                return None

            return IDMapping(
                source_instance=row["source_instance"],
                content_type=row["content_type"],
                source_id=row["source_id"],
                destination_id=row["destination_id"],
                created_at=datetime.fromisoformat(row["created_at"]),
                session_id=row["session_id"],
            )
        except sqlite3.Error as e:
            raise StorageError(f"Failed to get ID mapping: {e}") from e

    def get_destination_id(
        self, source_instance: str, content_type: int, source_id: str
    ) -> str | None:
        """Get destination ID for source ID.

        Args:
            source_instance: Source Looker instance URL
            content_type: ContentType enum value
            source_id: Original ID from source instance

        Returns:
            Destination ID if mapped, None otherwise
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT destination_id
                FROM id_mappings
                WHERE source_instance = ? AND content_type = ? AND source_id = ?
            """,
                (source_instance, content_type, source_id),
            )

            row = cursor.fetchone()
            return row["destination_id"] if row else None
        except sqlite3.Error as e:
            raise StorageError(f"Failed to get destination ID: {e}") from e

    def batch_get_mappings(
        self, source_instance: str, content_type: int, source_ids: Sequence[str]
    ) -> dict[str, str]:
        """Batch retrieve mappings for multiple source IDs.

        Optimized for performance using single bulk query with IN clause.

        Args:
            source_instance: Source Looker instance URL
            content_type: ContentType enum value
            source_ids: List of source IDs to look up

        Returns:
            Dictionary mapping source_id -> destination_id (only includes found mappings)
        """
        if not source_ids:
            return {}

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Use parameterized query with IN clause for bulk lookup
            # Safe: placeholders are just "?" repeated, no user input in SQL structure
            placeholders: str = ",".join("?" * len(source_ids))
            query = f"""
                SELECT source_id, destination_id
                FROM id_mappings
                WHERE source_instance = ? AND content_type = ? AND source_id IN ({placeholders})
            """  # noqa: S608

            params: list[str | int] = [source_instance, content_type] + list(source_ids)
            cursor.execute(query, params)

            return {row["source_id"]: row["destination_id"] for row in cursor.fetchall()}
        except sqlite3.Error as e:
            raise StorageError(f"Failed to batch get mappings: {e}") from e

    def clear_mappings(
        self, source_instance: str | None = None, content_type: int | None = None
    ) -> int:
        """Clear ID mappings with optional filters.

        Args:
            source_instance: Optional source instance filter (None = all instances)
            content_type: Optional content type filter (None = all types)

        Returns:
            Number of mappings deleted
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            query = "DELETE FROM id_mappings"
            params: list[str | int] = []
            conditions: list[str] = []

            if source_instance is not None:
                conditions.append("source_instance = ?")
                params.append(source_instance)

            if content_type is not None:
                conditions.append("content_type = ?")
                params.append(content_type)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            cursor.execute(query, params)
            deleted_count: int = cursor.rowcount
            conn.commit()

            return deleted_count
        except sqlite3.Error as e:
            raise StorageError(f"Failed to clear mappings: {e}") from e
