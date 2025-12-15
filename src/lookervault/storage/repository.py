"""Content repository for SQLite storage operations."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol, TypeVar

from lookervault.exceptions import NotFoundError, StorageError
from lookervault.storage.models import (
    Checkpoint,
    ContentItem,
    ContentType,
    DeadLetterItem,
    ExtractionSession,
    IDMapping,
    RestorationCheckpoint,
    RestorationSession,
)
from lookervault.storage.schema import create_schema, optimize_database

logger = logging.getLogger(__name__)

T = TypeVar("T")


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

    def count_content(
        self,
        content_type: int,
        include_deleted: bool = False,
    ) -> int:
        """Count content items by type.

        Args:
            content_type: ContentType enum value
            include_deleted: Include soft-deleted items

        Returns:
            Total count of matching items
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

    def get_schema_version(self) -> int:
        """Get current database schema version.

        Returns:
            Current schema version number

        Raises:
            StorageError: If schema version cannot be retrieved
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

    def get_schema_version(self) -> int:
        """Get current database schema version.

        Returns:
            Current schema version number

        Raises:
            StorageError: If schema version cannot be retrieved
        """
        from lookervault.storage.schema import get_schema_version

        conn = self._get_connection()
        version = get_schema_version(conn)
        if version is None:
            raise StorageError("Database schema version not found")
        return version

    def _retry_on_busy(
        self,
        operation: Callable[[], T],
        max_retries: int = 5,
        initial_delay: float = 0.1,
    ) -> T:
        """Retry database operation on SQLITE_BUSY error.

        Implements exponential backoff for write contention in parallel execution.
        SQLite can return SQLITE_BUSY even with BEGIN IMMEDIATE if multiple writers
        are contending for the database lock.

        Args:
            operation: Callable that performs the database operation
            max_retries: Maximum retry attempts (default: 5)
            initial_delay: Initial retry delay in seconds (default: 0.1)

        Returns:
            Result of operation() call

        Raises:
            StorageError: If operation fails after max_retries
        """
        last_error = None
        delay = initial_delay

        for attempt in range(max_retries):
            try:
                return operation()
            except sqlite3.OperationalError as e:
                last_error = e
                if "database is locked" in str(e).lower() or "busy" in str(e).lower():
                    if attempt < max_retries - 1:
                        # Exponential backoff with jitter
                        jitter = delay * 0.1 * (hash(threading.current_thread().name) % 10) / 10
                        sleep_time = delay + jitter
                        logger.debug(
                            f"SQLITE_BUSY detected (attempt {attempt + 1}/{max_retries}), "
                            f"retrying in {sleep_time:.3f}s"
                        )
                        time.sleep(sleep_time)
                        delay *= 2  # Exponential backoff
                    else:
                        logger.warning(f"SQLITE_BUSY retry exhausted after {max_retries} attempts")
                        raise StorageError(
                            f"Database locked after {max_retries} retries: {e}"
                        ) from e
                else:
                    # Not a busy error - re-raise immediately
                    raise

        # Should never reach here, but for type safety
        raise StorageError(f"Database operation failed: {last_error}") from last_error

    def save_content(self, item: ContentItem) -> None:
        """Save or update a content item with thread-safe transaction control.

        Uses BEGIN IMMEDIATE to prevent write-after-read deadlocks in parallel execution.
        This acquires a write lock immediately, allowing concurrent reads but blocking
        other writers until the transaction completes.

        Includes retry logic for SQLITE_BUSY errors that can occur in parallel execution.

        Args:
            item: ContentItem to persist

        Raises:
            StorageError: If save fails after retries
        """

        def _save_operation() -> None:
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
                            content_size, content_data, folder_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                            content_data = excluded.content_data,
                            folder_id = excluded.folder_id
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
                            item.folder_id,
                        ),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
            except sqlite3.Error as e:
                raise StorageError(f"Failed to save content: {e}") from e

        # Retry operation on SQLITE_BUSY
        self._retry_on_busy(_save_operation)

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
                       content_size, content_data, folder_id
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
                folder_id=row["folder_id"],
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
                       content_size, content_data, folder_id
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
                        folder_id=row["folder_id"],
                    )
                )

            return items
        except sqlite3.Error as e:
            raise StorageError(f"Failed to list content: {e}") from e

    def count_content(
        self,
        content_type: int,
        include_deleted: bool = False,
    ) -> int:
        """Count content items by type.

        Args:
            content_type: ContentType enum value
            include_deleted: Include soft-deleted items

        Returns:
            Total count of matching items
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            query = """
                SELECT COUNT(*) as total
                FROM content_items
                WHERE content_type = ?
            """

            params: list[int | str] = [content_type]

            if not include_deleted:
                query += " AND deleted_at IS NULL"

            cursor.execute(query, params)
            row = cursor.fetchone()

            return row["total"] if row else 0
        except sqlite3.Error as e:
            raise StorageError(f"Failed to count content: {e}") from e

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
        """Save or update extraction checkpoint with thread-safe transaction control.

        Uses upsert (INSERT ... ON CONFLICT DO UPDATE) to make checkpoint saves idempotent.
        If a checkpoint with the same (session_id, content_type, started_at) already exists,
        it will be updated instead of creating a duplicate.

        Includes retry logic for SQLITE_BUSY errors that can occur in parallel execution.

        Args:
            checkpoint: Checkpoint object

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

                try:
                    cursor = conn.cursor()

                    cursor.execute(
                        """
                        INSERT INTO sync_checkpoints (
                            session_id, content_type, checkpoint_data, started_at,
                            completed_at, item_count, error_message
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(session_id, content_type, started_at) DO UPDATE SET
                            checkpoint_data = excluded.checkpoint_data,
                            completed_at = excluded.completed_at,
                            item_count = excluded.item_count,
                            error_message = excluded.error_message
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

        # Retry operation on SQLITE_BUSY
        return self._retry_on_busy(_save_operation)

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

        Includes retry logic for SQLITE_BUSY errors that can occur in parallel execution.

        Args:
            checkpoint: Checkpoint object with updated values

        Raises:
            StorageError: If update fails after retries
        """

        def _update_operation() -> None:
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
                            checkpoint.completed_at.isoformat()
                            if checkpoint.completed_at
                            else None,
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

        # Retry operation on SQLITE_BUSY
        self._retry_on_busy(_update_operation)

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
        if content_type not in [
            ContentType.DASHBOARD.value,
            ContentType.LOOK.value,
            ContentType.BOARD.value,
        ]:
            raise ValueError(
                f"Content type {ContentType(content_type).name} does not support folder filtering"
            )

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Parameterized query to prevent SQL injection
            placeholders = ",".join(["?" for _ in folder_ids])
            # ruff: noqa: S608
            query = f"""
                SELECT id
                FROM content_items
                WHERE content_type = ? AND folder_id IN ({placeholders})
            """

            params: list[int | str] = [content_type, *folder_ids]

            if not include_deleted:
                query += " AND deleted_at IS NULL"

            cursor.execute(query, params)

            filtered_ids = {row["id"] for row in cursor.fetchall()}

            logger.debug(
                f"Filtered {len(filtered_ids)} {ContentType(content_type).name} items "
                f"in {len(folder_ids)} folder(s)"
            )

            return filtered_ids

        except sqlite3.Error as e:
            raise StorageError(f"Failed to get content IDs in folders: {e}") from e

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
        if content_type not in [
            ContentType.DASHBOARD.value,
            ContentType.LOOK.value,
            ContentType.BOARD.value,
        ]:
            raise ValueError(
                f"Content type {ContentType(content_type).name} does not support folder filtering"
            )

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Parameterized query to prevent SQL injection
            placeholders = ",".join(["?" for _ in folder_ids])
            # ruff: noqa: S608
            query = f"""
                SELECT id, content_type, name, owner_id, owner_email,
                       created_at, updated_at, synced_at, deleted_at,
                       content_size, content_data, folder_id
                FROM content_items
                WHERE content_type = ? AND folder_id IN ({placeholders})
            """

            # Construct params with content_type first, then folder_ids
            params: list[int | str] = [content_type, *folder_ids]

            if not include_deleted:
                query += " AND deleted_at IS NULL"

            query += " ORDER BY updated_at DESC"

            if limit is not None:
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
                        folder_id=row["folder_id"],
                    )
                )

            logger.debug(
                f"Listed {len(items)} {ContentType(content_type).name} items "
                f"in {len(folder_ids)} folder(s)"
            )

            return items

        except sqlite3.Error as e:
            raise StorageError(f"Failed to list content in folders: {e}") from e

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
                       content_size, content_data, folder_id
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
                        folder_id=row["folder_id"],
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

                try:
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

                    dlq_id = cursor.lastrowid
                    conn.commit()
                    return dlq_id
                except Exception:
                    conn.rollback()
                    raise
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
        limit: int = 100,
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
            params.extend([limit, offset])

            cursor.execute(query, params)

            items = []
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

                try:
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
                except Exception:
                    conn.rollback()
                    raise
            except sqlite3.Error as e:
                raise StorageError(f"Failed to delete dead letter item: {e}") from e

        # Retry operation on SQLITE_BUSY
        self._retry_on_busy(_delete_operation)

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

                try:
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
                except Exception:
                    conn.rollback()
                    raise
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
            placeholders = ",".join("?" * len(source_ids))
            query = f"""
                SELECT source_id, destination_id
                FROM id_mappings
                WHERE source_instance = ? AND content_type = ? AND source_id IN ({placeholders})
            """  # noqa: S608

            params = [source_instance, content_type] + list(source_ids)
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
            conditions = []

            if source_instance is not None:
                conditions.append("source_instance = ?")
                params.append(source_instance)

            if content_type is not None:
                conditions.append("content_type = ?")
                params.append(content_type)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            cursor.execute(query, params)
            deleted_count = cursor.rowcount
            conn.commit()

            return deleted_count
        except sqlite3.Error as e:
            raise StorageError(f"Failed to clear mappings: {e}") from e

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

                try:
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

                    checkpoint_id = cursor.lastrowid
                    conn.commit()
                    return checkpoint_id
                except Exception:
                    conn.rollback()
                    raise
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

                try:
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
                except Exception:
                    conn.rollback()
                    raise
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

                try:
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
                except Exception:
                    conn.rollback()
                    raise
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

                try:
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
                except Exception:
                    conn.rollback()
                    raise
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

            sessions = []
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
