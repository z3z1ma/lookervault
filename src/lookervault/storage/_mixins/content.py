"""Content CRUD operations for storage mixin."""

import sqlite3
from collections.abc import Sequence
from datetime import datetime

from lookervault.exceptions import NotFoundError, StorageError
from lookervault.storage.models import ContentItem, ContentType
from lookervault.utils import transaction_rollback


class ContentMixin:
    """Mixin providing content item CRUD operations.

    This mixin handles all operations related to content items including:
    - Creating/updating content items
    - Retrieving single or multiple items
    - Counting items by type
    - Soft/hard deletion
    - Folder-filtered queries
    - Cleanup of old deleted items
    """

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        raise NotImplementedError("Subclass must implement _get_connection")

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

                with transaction_rollback(conn):
                    cursor = conn.cursor()

                    cursor.execute(
                        """
                        INSERT INTO content_items (
                            id, content_type, name, owner_id, owner_email,
                            created_at, updated_at, synced_at, deleted_at,
                            content_size, content_data, folder_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id, content_type) DO UPDATE SET
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

            items: list[ContentItem] = []
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
            import logging

            logger = logging.getLogger(__name__)
            conn = self._get_connection()
            cursor = conn.cursor()

            # Parameterized query to prevent SQL injection
            placeholders: str = ",".join(["?" for _ in folder_ids])
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

            filtered_ids: set[str] = {row["id"] for row in cursor.fetchall()}

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
            import logging

            logger = logging.getLogger(__name__)
            conn = self._get_connection()
            cursor = conn.cursor()

            # Parameterized query to prevent SQL injection
            placeholders: str = ",".join(["?" for _ in folder_ids])
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

            items: list[ContentItem] = []
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

            items: list[ContentItem] = []
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

            deleted_count: int = cursor.rowcount
            conn.commit()

            return deleted_count
        except sqlite3.Error as e:
            raise StorageError(f"Failed to hard delete items: {e}") from e
