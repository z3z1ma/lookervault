"""Content repository for SQLite storage operations."""

import json
import sqlite3
import threading
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol

from lookervault.exceptions import NotFoundError, StorageError
from lookervault.storage.models import Checkpoint, ContentItem, ExtractionSession
from lookervault.storage.schema import create_schema, optimize_database


class ContentRepository(Protocol):
    """Protocol for content storage operations."""

    def save_content(self, item: ContentItem) -> None:
        """Save or update a content item.

        Args:
            item: ContentItem to persist

        Raises:
            StorageError: If save fails
        """
        ...

    def get_content(self, content_id: str) -> ContentItem | None:
        """Retrieve content by ID.

        Args:
            content_id: Unique content identifier

        Returns:
            ContentItem if found, None otherwise
        """
        ...

    def list_content(
        self,
        content_type: int,
        include_deleted: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> Sequence[ContentItem]:
        """List content items by type.

        Args:
            content_type: ContentType enum value
            include_deleted: Include soft-deleted items
            limit: Maximum items to return
            offset: Pagination offset

        Returns:
            Sequence of ContentItem objects
        """
        ...

    def delete_content(self, content_id: str, soft: bool = True) -> None:
        """Delete content item.

        Args:
            content_id: Unique content identifier
            soft: If True, soft delete. If False, hard delete.

        Raises:
            NotFoundError: If content doesn't exist
        """
        ...

    def save_checkpoint(self, checkpoint: Checkpoint) -> int:
        """Save extraction checkpoint.

        Args:
            checkpoint: Checkpoint object

        Returns:
            Checkpoint ID

        Raises:
            StorageError: If save fails
        """
        ...

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

    def update_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Update existing checkpoint.

        Args:
            checkpoint: Checkpoint object with updated values

        Raises:
            StorageError: If update fails
        """
        ...

    def create_session(self, session: ExtractionSession) -> None:
        """Create new extraction session."""
        ...

    def update_session(self, session: ExtractionSession) -> None:
        """Update existing extraction session."""
        ...

    def get_last_sync_timestamp(self, content_type: int) -> datetime | None:
        """Get the timestamp of the last successful extraction for a content type.

        Args:
            content_type: ContentType enum value

        Returns:
            Datetime of last sync, or None if never synced
        """
        ...

    def get_content_ids(self, content_type: int) -> set[str]:
        """Get all content IDs for a content type (excluding deleted).

        Args:
            content_type: ContentType enum value

        Returns:
            Set of content IDs
        """
        ...


class SQLiteContentRepository:
    """Thread-safe SQLite-based content repository implementation.

    Uses thread-local connections to enable parallel access from multiple worker threads.
    Each thread gets its own SQLite connection to prevent concurrency issues.
    """

    def __init__(self, db_path: str | Path):
        """Initialize repository with database path.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Thread-local storage for connections (one per thread)
        self._local = threading.local()

        # Initialize database schema once from main thread
        with self._create_connection() as conn:
            optimize_database(conn)
            create_schema(conn)

    def _create_connection(self) -> sqlite3.Connection:
        """Create new SQLite connection with optimal settings for parallel access.

        Returns:
            New SQLite connection with thread-safe configuration
        """
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=60.0,  # 60 second busy timeout for lock contention
            isolation_level=None,  # Manual transaction control
            check_same_thread=True,  # Safety check - each thread uses own connection
            cached_statements=0,  # Python 3.13 thread-safety fix
        )
        conn.row_factory = sqlite3.Row

        # Per-connection PRAGMAs (WAL mode set globally in schema.py)
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA temp_store = MEMORY")

        return conn

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create thread-local database connection.

        Each thread gets its own connection stored in thread-local storage.
        This prevents connection sharing between threads which would cause
        SQLite errors and potential data corruption.

        Returns:
            SQLite connection for current thread
        """
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = self._create_connection()
        return self._local.conn

    def close_thread_connection(self) -> None:
        """Close database connection for current thread.

        MUST be called in worker thread cleanup (e.g., in finally block)
        to prevent connection leaks when threads exit.
        """
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    def close(self) -> None:
        """Close database connection for current thread.

        Alias for close_thread_connection() for backward compatibility.
        """
        self.close_thread_connection()

    def save_content(self, item: ContentItem) -> None:
        """Save or update a content item with thread-safe transaction control.

        Uses BEGIN IMMEDIATE to prevent write-after-read deadlocks in parallel execution.
        This acquires a write lock immediately, allowing concurrent reads but blocking
        other writers until the transaction completes.

        Args:
            item: ContentItem to persist

        Raises:
            StorageError: If save fails
        """
        try:
            conn = self._get_connection()
            # BEGIN IMMEDIATE: Acquire write lock immediately to prevent deadlocks
            conn.execute("BEGIN IMMEDIATE")

            try:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    INSERT INTO content_items (
                        id, content_type, name, owner_id, owner_email,
                        created_at, updated_at, synced_at, deleted_at,
                        content_size, content_data
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        content_type = excluded.content_type,
                        name = excluded.name,
                        owner_id = excluded.owner_id,
                        owner_email = excluded.owner_email,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at,
                        synced_at = excluded.synced_at,
                        deleted_at = excluded.deleted_at,
                        content_size = excluded.content_size,
                        content_data = excluded.content_data
                """,
                    (
                        item.id,
                        item.content_type,
                        item.name,
                        item.owner_id,
                        item.owner_email,
                        item.created_at.isoformat(),
                        item.updated_at.isoformat(),
                        item.synced_at.isoformat() if item.synced_at else None,
                        item.deleted_at.isoformat() if item.deleted_at else None,
                        item.content_size,
                        item.content_data,
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        except sqlite3.Error as e:
            raise StorageError(f"Failed to save content: {e}") from e

    def get_content(self, content_id: str) -> ContentItem | None:
        """Retrieve content by ID.

        Args:
            content_id: Unique content identifier

        Returns:
            ContentItem if found, None otherwise
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id, content_type, name, owner_id, owner_email,
                       created_at, updated_at, synced_at, deleted_at,
                       content_size, content_data
                FROM content_items
                WHERE id = ?
            """,
                (content_id,),
            )

            row = cursor.fetchone()
            if not row:
                return None

            return ContentItem(
                id=row["id"],
                content_type=row["content_type"],
                name=row["name"],
                owner_id=row["owner_id"],
                owner_email=row["owner_email"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                synced_at=datetime.fromisoformat(row["synced_at"]) if row["synced_at"] else None,
                deleted_at=datetime.fromisoformat(row["deleted_at"]) if row["deleted_at"] else None,
                content_size=row["content_size"],
                content_data=row["content_data"],
            )
        except sqlite3.Error as e:
            raise StorageError(f"Failed to get content: {e}") from e

    def list_content(
        self,
        content_type: int,
        include_deleted: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> Sequence[ContentItem]:
        """List content items by type.

        Args:
            content_type: ContentType enum value
            include_deleted: Include soft-deleted items
            limit: Maximum items to return
            offset: Pagination offset

        Returns:
            Sequence of ContentItem objects
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            query = """
                SELECT id, content_type, name, owner_id, owner_email,
                       created_at, updated_at, synced_at, deleted_at,
                       content_size, content_data
                FROM content_items
                WHERE content_type = ?
            """

            params: list[int | str] = [content_type]

            if not include_deleted:
                query += " AND deleted_at IS NULL"

            query += " ORDER BY updated_at DESC"

            if limit:
                query += " LIMIT ? OFFSET ?"
                params.extend([limit, offset])

            cursor.execute(query, params)

            items = []
            for row in cursor.fetchall():
                items.append(
                    ContentItem(
                        id=row["id"],
                        content_type=row["content_type"],
                        name=row["name"],
                        owner_id=row["owner_id"],
                        owner_email=row["owner_email"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        updated_at=datetime.fromisoformat(row["updated_at"]),
                        synced_at=datetime.fromisoformat(row["synced_at"])
                        if row["synced_at"]
                        else None,
                        deleted_at=datetime.fromisoformat(row["deleted_at"])
                        if row["deleted_at"]
                        else None,
                        content_size=row["content_size"],
                        content_data=row["content_data"],
                    )
                )

            return items
        except sqlite3.Error as e:
            raise StorageError(f"Failed to list content: {e}") from e

    def delete_content(self, content_id: str, soft: bool = True) -> None:
        """Delete content item.

        Args:
            content_id: Unique content identifier
            soft: If True, soft delete. If False, hard delete.

        Raises:
            NotFoundError: If content doesn't exist
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            if soft:
                cursor.execute(
                    """
                    UPDATE content_items
                    SET deleted_at = ?
                    WHERE id = ?
                """,
                    (datetime.now().isoformat(), content_id),
                )
            else:
                cursor.execute("DELETE FROM content_items WHERE id = ?", (content_id,))

            if cursor.rowcount == 0:
                raise NotFoundError(f"Content not found: {content_id}")

            conn.commit()
        except sqlite3.Error as e:
            raise StorageError(f"Failed to delete content: {e}") from e

    def save_checkpoint(self, checkpoint: Checkpoint) -> int:
        """Save extraction checkpoint with thread-safe transaction control.

        Args:
            checkpoint: Checkpoint object

        Returns:
            Checkpoint ID

        Raises:
            StorageError: If save fails
        """
        try:
            conn = self._get_connection()
            # BEGIN IMMEDIATE: Thread-safe checkpoint writes
            conn.execute("BEGIN IMMEDIATE")

            try:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    INSERT INTO sync_checkpoints (
                        session_id, content_type, checkpoint_data, started_at,
                        completed_at, item_count, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        checkpoint.session_id,
                        checkpoint.content_type,
                        json.dumps(checkpoint.checkpoint_data),
                        checkpoint.started_at.isoformat(),
                        checkpoint.completed_at.isoformat() if checkpoint.completed_at else None,
                        checkpoint.item_count,
                        checkpoint.error_message,
                    ),
                )

                checkpoint_id = cursor.lastrowid
                conn.commit()
                return checkpoint_id
            except Exception:
                conn.rollback()
                raise
        except sqlite3.Error as e:
            raise StorageError(f"Failed to save checkpoint: {e}") from e

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
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            query = """
                SELECT id, session_id, content_type, checkpoint_data,
                       started_at, completed_at, item_count, error_message
                FROM sync_checkpoints
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

            return Checkpoint(
                id=row["id"],
                session_id=row["session_id"],
                content_type=row["content_type"],
                checkpoint_data=json.loads(row["checkpoint_data"]),
                started_at=datetime.fromisoformat(row["started_at"]),
                completed_at=datetime.fromisoformat(row["completed_at"])
                if row["completed_at"]
                else None,
                item_count=row["item_count"],
                error_message=row["error_message"],
            )
        except sqlite3.Error as e:
            raise StorageError(f"Failed to get checkpoint: {e}") from e

    def update_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Update existing checkpoint with thread-safe transaction control.

        Args:
            checkpoint: Checkpoint object with updated values

        Raises:
            StorageError: If update fails
        """
        try:
            conn = self._get_connection()
            # BEGIN IMMEDIATE: Thread-safe checkpoint updates
            conn.execute("BEGIN IMMEDIATE")

            try:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    UPDATE sync_checkpoints
                    SET checkpoint_data = ?, completed_at = ?,
                        item_count = ?, error_message = ?
                    WHERE id = ?
                """,
                    (
                        json.dumps(checkpoint.checkpoint_data),
                        checkpoint.completed_at.isoformat() if checkpoint.completed_at else None,
                        checkpoint.item_count,
                        checkpoint.error_message,
                        checkpoint.id,
                    ),
                )

                conn.commit()
            except Exception:
                conn.rollback()
                raise
        except sqlite3.Error as e:
            raise StorageError(f"Failed to update checkpoint: {e}") from e

    def create_session(self, session: ExtractionSession) -> None:
        """Create new extraction session.

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

    def get_content_ids(self, content_type: int) -> set[str]:
        """Get all content IDs for a content type (excluding deleted).

        Args:
            content_type: ContentType enum value

        Returns:
            Set of content IDs
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id
                FROM content_items
                WHERE content_type = ? AND deleted_at IS NULL
            """,
                (content_type,),
            )

            return {row["id"] for row in cursor.fetchall()}
        except sqlite3.Error as e:
            raise StorageError(f"Failed to get content IDs: {e}") from e

    def get_deleted_items_before(self, cutoff_date: datetime) -> Sequence[ContentItem]:
        """Get soft-deleted items before cutoff date.

        Args:
            cutoff_date: Cutoff datetime for deletion

        Returns:
            Sequence of ContentItem objects that are soft-deleted before cutoff
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id, content_type, name, owner_id, owner_email,
                       created_at, updated_at, synced_at, deleted_at,
                       content_size, content_data
                FROM content_items
                WHERE deleted_at IS NOT NULL AND deleted_at < ?
                ORDER BY deleted_at ASC
            """,
                (cutoff_date.isoformat(),),
            )

            items = []
            for row in cursor.fetchall():
                items.append(
                    ContentItem(
                        id=row["id"],
                        content_type=row["content_type"],
                        name=row["name"],
                        owner_id=row["owner_id"],
                        owner_email=row["owner_email"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        updated_at=datetime.fromisoformat(row["updated_at"]),
                        synced_at=datetime.fromisoformat(row["synced_at"])
                        if row["synced_at"]
                        else None,
                        deleted_at=datetime.fromisoformat(row["deleted_at"])
                        if row["deleted_at"]
                        else None,
                        content_size=row["content_size"],
                        content_data=row["content_data"],
                    )
                )

            return items
        except sqlite3.Error as e:
            raise StorageError(f"Failed to get deleted items: {e}") from e

    def hard_delete_before(self, cutoff_date: datetime) -> int:
        """Permanently delete soft-deleted items before cutoff date.

        Args:
            cutoff_date: Cutoff datetime for deletion

        Returns:
            Number of items deleted
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                DELETE FROM content_items
                WHERE deleted_at IS NOT NULL AND deleted_at < ?
            """,
                (cutoff_date.isoformat(),),
            )

            deleted_count = cursor.rowcount
            conn.commit()

            return deleted_count
        except sqlite3.Error as e:
            raise StorageError(f"Failed to hard delete items: {e}") from e
