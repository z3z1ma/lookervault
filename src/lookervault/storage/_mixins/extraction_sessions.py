"""Extraction session operations for storage mixin."""

import json
import sqlite3
from datetime import datetime

from lookervault.exceptions import StorageError
from lookervault.storage.models import ExtractionSession


class ExtractionSessionsMixin:
    """Mixin providing extraction session operations.

    This mixin handles creation, updates, and retrieval of extraction
    sessions which track the overall progress of content extraction.
    """

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        raise NotImplementedError("Subclass must implement _get_connection")

    def create_session(self, session: ExtractionSession) -> None:
        """Create or update extraction session.

        Uses upsert (INSERT ... ON CONFLICT DO UPDATE) to make session creation idempotent.
        If a session with the same id already exists, it will be updated instead of creating
        a duplicate. The started_at field is preserved to maintain original session start time.

        Args:
            session: ExtractionSession object

        Raises:
            StorageError: If creation fails
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO extraction_sessions (
                    id, started_at, completed_at, status,
                    total_items, error_count, config, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    completed_at = excluded.completed_at,
                    status = excluded.status,
                    total_items = excluded.total_items,
                    error_count = excluded.error_count,
                    config = excluded.config,
                    metadata = excluded.metadata
            """,
                (
                    session.id,
                    session.started_at.isoformat(),
                    session.completed_at.isoformat() if session.completed_at else None,
                    session.status,
                    session.total_items,
                    session.error_count,
                    json.dumps(session.config) if session.config else None,
                    json.dumps(session.metadata) if session.metadata else None,
                ),
            )

            conn.commit()
        except sqlite3.Error as e:
            raise StorageError(f"Failed to create session: {e}") from e

    def update_session(self, session: ExtractionSession) -> None:
        """Update existing extraction session.

        Args:
            session: ExtractionSession object

        Raises:
            StorageError: If update fails
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE extraction_sessions
                SET completed_at = ?, status = ?, total_items = ?,
                    error_count = ?, config = ?, metadata = ?
                WHERE id = ?
            """,
                (
                    session.completed_at.isoformat() if session.completed_at else None,
                    session.status,
                    session.total_items,
                    session.error_count,
                    json.dumps(session.config) if session.config else None,
                    json.dumps(session.metadata) if session.metadata else None,
                    session.id,
                ),
            )

            conn.commit()
        except sqlite3.Error as e:
            raise StorageError(f"Failed to update session: {e}") from e

    def get_extraction_session(self, session_id: str) -> ExtractionSession | None:
        """Retrieve extraction session by ID.

        Args:
            session_id: Unique session identifier

        Returns:
            ExtractionSession if found, None otherwise

        Raises:
            StorageError: If query fails
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id, started_at, completed_at, status,
                       total_items, error_count, config, metadata
                FROM extraction_sessions
                WHERE id = ?
            """,
                (session_id,),
            )

            row = cursor.fetchone()
            if not row:
                return None

            return ExtractionSession(
                id=row["id"],
                started_at=datetime.fromisoformat(row["started_at"]),
                completed_at=datetime.fromisoformat(row["completed_at"])
                if row["completed_at"]
                else None,
                status=row["status"],
                total_items=row["total_items"],
                error_count=row["error_count"],
                config=json.loads(row["config"]) if row["config"] else None,
                metadata=json.loads(row["metadata"]) if row["metadata"] else None,
            )
        except sqlite3.Error as e:
            raise StorageError(f"Failed to get extraction session: {e}") from e
