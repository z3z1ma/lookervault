"""Restoration session operations for storage mixin."""

import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime

from lookervault.exceptions import StorageError
from lookervault.storage.models import RestorationSession
from lookervault.utils import transaction_rollback


class RestorationSessionsMixin:
    """Mixin providing restoration session operations.

    This mixin handles creation, updates, retrieval, and listing of
    restoration sessions which track the overall progress of content restoration.
    """

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        raise NotImplementedError("Subclass must implement _get_connection")

    def create_restoration_session(self, session: RestorationSession) -> None:
        """Create or update restoration session with thread-safe transaction control.

        Uses upsert (INSERT ... ON CONFLICT DO UPDATE) to make session creation idempotent.
        If a session with the same id already exists, it will be updated instead of creating
        a duplicate. The started_at field is preserved to maintain original session start time.

        Uses BEGIN IMMEDIATE to prevent write-after-read deadlocks in parallel execution.

        Args:
            session: RestorationSession object

        Raises:
            StorageError: If creation fails after retries
        """

        def _create_operation() -> None:
            try:
                conn = self._get_connection()
                # BEGIN IMMEDIATE: Acquire write lock immediately to prevent deadlocks
                conn.execute("BEGIN IMMEDIATE")

                with transaction_rollback(conn):
                    cursor = conn.cursor()

                    cursor.execute(
                        """
                        INSERT INTO restoration_sessions (
                            id, started_at, completed_at, status,
                            total_items, success_count, error_count,
                            source_instance, destination_instance,
                            config, metadata
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            completed_at = excluded.completed_at,
                            status = excluded.status,
                            total_items = excluded.total_items,
                            success_count = excluded.success_count,
                            error_count = excluded.error_count,
                            source_instance = excluded.source_instance,
                            destination_instance = excluded.destination_instance,
                            config = excluded.config,
                            metadata = excluded.metadata
                    """,
                        (
                            session.id,
                            session.started_at.isoformat(),
                            session.completed_at.isoformat() if session.completed_at else None,
                            session.status,
                            session.total_items,
                            session.success_count,
                            session.error_count,
                            session.source_instance,
                            session.destination_instance,
                            json.dumps(session.config) if session.config else None,
                            json.dumps(session.metadata) if session.metadata else None,
                        ),
                    )

                    conn.commit()
            except sqlite3.Error as e:
                raise StorageError(f"Failed to create restoration session: {e}") from e

        # Retry operation on SQLITE_BUSY
        self._retry_on_busy(_create_operation)

    def update_restoration_session(self, session: RestorationSession) -> None:
        """Update existing restoration session with thread-safe transaction control.

        Uses BEGIN IMMEDIATE to prevent write-after-read deadlocks in parallel execution.
        Includes retry logic for SQLITE_BUSY errors that can occur in parallel execution.

        Args:
            session: RestorationSession object with updated values

        Raises:
            StorageError: If update fails after retries
        """

        def _update_operation() -> None:
            try:
                conn = self._get_connection()
                # BEGIN IMMEDIATE: Acquire write lock immediately to prevent deadlocks
                conn.execute("BEGIN IMMEDIATE")

                with transaction_rollback(conn):
                    cursor = conn.cursor()

                    cursor.execute(
                        """
                        UPDATE restoration_sessions
                        SET completed_at = ?, status = ?,
                            total_items = ?, success_count = ?,
                            error_count = ?, source_instance = ?,
                            destination_instance = ?, config = ?, metadata = ?
                        WHERE id = ?
                    """,
                        (
                            session.completed_at.isoformat() if session.completed_at else None,
                            session.status,
                            session.total_items,
                            session.success_count,
                            session.error_count,
                            session.source_instance,
                            session.destination_instance,
                            json.dumps(session.config) if session.config else None,
                            json.dumps(session.metadata) if session.metadata else None,
                            session.id,
                        ),
                    )

                    conn.commit()
            except sqlite3.Error as e:
                raise StorageError(f"Failed to update restoration session: {e}") from e

        # Retry operation on SQLITE_BUSY
        self._retry_on_busy(_update_operation)

    def get_restoration_session(self, session_id: str) -> RestorationSession | None:
        """Retrieve restoration session by ID.

        Args:
            session_id: Unique session identifier

        Returns:
            RestorationSession if found, None otherwise

        Raises:
            StorageError: If query fails
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id, started_at, completed_at, status,
                       total_items, success_count, error_count,
                       source_instance, destination_instance,
                       config, metadata
                FROM restoration_sessions
                WHERE id = ?
            """,
                (session_id,),
            )

            row = cursor.fetchone()
            if not row:
                return None

            return RestorationSession(
                id=row["id"],
                started_at=datetime.fromisoformat(row["started_at"]),
                completed_at=datetime.fromisoformat(row["completed_at"])
                if row["completed_at"]
                else None,
                status=row["status"],
                total_items=row["total_items"],
                success_count=row["success_count"],
                error_count=row["error_count"],
                source_instance=row["source_instance"],
                destination_instance=row["destination_instance"],
                config=json.loads(row["config"]) if row["config"] else None,
                metadata=json.loads(row["metadata"]) if row["metadata"] else None,
            )
        except sqlite3.Error as e:
            raise StorageError(f"Failed to get restoration session: {e}") from e

    def list_restoration_sessions(
        self,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[RestorationSession]:
        """List restoration sessions with optional status filter.

        Args:
            status: Optional status filter (e.g., 'pending', 'running', 'completed')
            limit: Maximum sessions to return (default: 100)
            offset: Pagination offset (default: 0)

        Returns:
            Sequence of RestorationSession objects ordered by started_at DESC

        Raises:
            StorageError: If query fails
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            query = """
                SELECT id, started_at, completed_at, status,
                       total_items, success_count, error_count,
                       source_instance, destination_instance,
                       config, metadata
                FROM restoration_sessions
            """

            params: list[str | int] = []

            if status:
                query += " WHERE status = ?"
                params.append(status)

            query += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)

            sessions: list[RestorationSession] = []
            for row in cursor.fetchall():
                sessions.append(
                    RestorationSession(
                        id=row["id"],
                        started_at=datetime.fromisoformat(row["started_at"]),
                        completed_at=datetime.fromisoformat(row["completed_at"])
                        if row["completed_at"]
                        else None,
                        status=row["status"],
                        total_items=row["total_items"],
                        success_count=row["success_count"],
                        error_count=row["error_count"],
                        source_instance=row["source_instance"],
                        destination_instance=row["destination_instance"],
                        config=json.loads(row["config"]) if row["config"] else None,
                        metadata=json.loads(row["metadata"]) if row["metadata"] else None,
                    )
                )

            return sessions
        except sqlite3.Error as e:
            raise StorageError(f"Failed to list restoration sessions: {e}") from e
