"""Utility methods for storage mixin."""

import sqlite3
from datetime import datetime

from lookervault.exceptions import StorageError
from lookervault.storage.schema import get_schema_version


class StorageUtilsMixin:
    """Mixin providing utility methods for storage operations.

    This mixin provides helper methods for schema versioning and
    timestamp queries.
    """

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        raise NotImplementedError("Subclass must implement _get_connection")

    def get_schema_version(self) -> int:
        """Get current database schema version.

        Returns:
            Current schema version number

        Raises:
            StorageError: If schema version cannot be retrieved
        """
        conn = self._get_connection()
        version = get_schema_version(conn)
        if version is None:
            raise StorageError("Database schema version not found")
        return version

    def get_last_sync_timestamp(self, content_type: int) -> datetime | None:
        """Get the timestamp of the last successful extraction for a content type.

        Args:
            content_type: ContentType enum value

        Returns:
            Datetime of last sync, or None if never synced
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT MAX(synced_at)
                FROM content_items
                WHERE content_type = ? AND deleted_at IS NULL
            """,
                (content_type,),
            )

            row = cursor.fetchone()
            if row and row[0]:
                return datetime.fromisoformat(row[0])
            return None
        except sqlite3.Error as e:
            raise StorageError(f"Failed to get last sync timestamp: {e}") from e
