"""Restoration checkpoint operations for storage mixin."""

import json
import sqlite3
from datetime import datetime

from lookervault.exceptions import StorageError
from lookervault.storage.models import RestorationCheckpoint
from lookervault.utils import transaction_rollback


class RestorationCheckpointsMixin:
    """Mixin providing restoration checkpoint operations.

    This mixin handles checkpoint creation, updates, and retrieval for
    tracking restoration progress and enabling resume functionality.
    """

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        raise NotImplementedError("Subclass must implement _get_connection")

    def save_restoration_checkpoint(self, checkpoint: RestorationCheckpoint) -> int:
        """Save or update restoration checkpoint with thread-safe transaction control.

        Uses upsert (INSERT ... ON CONFLICT DO UPDATE) to make checkpoint saves idempotent.
        If a checkpoint with the same (session_id, content_type, started_at) already exists,
        it will be updated instead of creating a duplicate.

        Includes retry logic for SQLITE_BUSY errors that can occur in parallel execution.

        Args:
            checkpoint: RestorationCheckpoint object

        Returns:
            Checkpoint ID

        Raises:
            StorageError: If save fails after retries
        """

        def _save_operation() -> int:
            try:
                conn = self._get_connection()
                # BEGIN IMMEDIATE: Thread-safe checkpoint writes
                conn.execute("BEGIN IMMEDIATE")

                with transaction_rollback(conn):
                    cursor = conn.cursor()

                    cursor.execute(
                        """
                        INSERT INTO restoration_checkpoints (
                            session_id, content_type, checkpoint_data, started_at,
                            completed_at, item_count, error_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(session_id, content_type, started_at) DO UPDATE SET
                            checkpoint_data = excluded.checkpoint_data,
                            completed_at = excluded.completed_at,
                            item_count = excluded.item_count,
                            error_count = excluded.error_count
                    """,
                        (
                            checkpoint.session_id,
                            checkpoint.content_type,
                            json.dumps(checkpoint.checkpoint_data),
                            checkpoint.started_at.isoformat(),
                            checkpoint.completed_at.isoformat()
                            if checkpoint.completed_at
                            else None,
                            checkpoint.item_count,
                            checkpoint.error_count,
                        ),
                    )

                    checkpoint_id: int = cursor.lastrowid or 0
                    conn.commit()
                    return checkpoint_id
            except sqlite3.Error as e:
                raise StorageError(f"Failed to save restoration checkpoint: {e}") from e

        # Retry operation on SQLITE_BUSY
        return self._retry_on_busy(_save_operation)

    def update_restoration_checkpoint(self, checkpoint: RestorationCheckpoint) -> None:
        """Update existing restoration checkpoint with thread-safe transaction control.

        Includes retry logic for SQLITE_BUSY errors that can occur in parallel execution.

        Args:
            checkpoint: RestorationCheckpoint object with updated values

        Raises:
            StorageError: If update fails after retries
        """

        def _update_operation() -> None:
            try:
                conn = self._get_connection()
                # BEGIN IMMEDIATE: Thread-safe checkpoint updates
                conn.execute("BEGIN IMMEDIATE")

                with transaction_rollback(conn):
                    cursor = conn.cursor()

                    cursor.execute(
                        """
                        UPDATE restoration_checkpoints
                        SET checkpoint_data = ?, completed_at = ?,
                            item_count = ?, error_count = ?
                        WHERE id = ?
                    """,
                        (
                            json.dumps(checkpoint.checkpoint_data),
                            checkpoint.completed_at.isoformat()
                            if checkpoint.completed_at
                            else None,
                            checkpoint.item_count,
                            checkpoint.error_count,
                            checkpoint.id,
                        ),
                    )

                    conn.commit()
            except sqlite3.Error as e:
                raise StorageError(f"Failed to update restoration checkpoint: {e}") from e

        # Retry operation on SQLITE_BUSY
        self._retry_on_busy(_update_operation)

    def get_latest_restoration_checkpoint(
        self, content_type: int, session_id: str | None = None
    ) -> RestorationCheckpoint | None:
        """Get most recent incomplete checkpoint for content type.

        Args:
            content_type: ContentType enum value
            session_id: Optional session filter

        Returns:
            Latest RestorationCheckpoint or None
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            query = """
                SELECT id, session_id, content_type, checkpoint_data,
                       started_at, completed_at, item_count, error_count
                FROM restoration_checkpoints
                WHERE content_type = ? AND completed_at IS NULL
            """

            params: list[int | str] = [content_type]

            if session_id:
                query += " AND session_id = ?"
                params.append(session_id)

            query += " ORDER BY started_at DESC LIMIT 1"

            cursor.execute(query, params)

            row = cursor.fetchone()
            if not row:
                return None

            return RestorationCheckpoint(
                id=row["id"],
                session_id=row["session_id"],
                content_type=row["content_type"],
                checkpoint_data=json.loads(row["checkpoint_data"]),
                started_at=datetime.fromisoformat(row["started_at"]),
                completed_at=datetime.fromisoformat(row["completed_at"])
                if row["completed_at"]
                else None,
                item_count=row["item_count"],
                error_count=row["error_count"],
            )
        except sqlite3.Error as e:
            raise StorageError(f"Failed to get restoration checkpoint: {e}") from e
