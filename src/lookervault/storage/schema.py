"""SQLite schema creation and management.

Query Performance Analysis (EXPLAIN QUERY PLAN verified):
- list_content: Uses idx_content_type (partial index for active records)
- get_deleted_items_before: Uses idx_deleted_at (soft-deleted items)
- get_last_sync_timestamp: Uses idx_updated_at DESC (latest updates)
- get_latest_checkpoint: Uses idx_checkpoint_type_completed (composite index)

All indexes are partial (WHERE deleted_at IS/IS NOT NULL) to reduce index size
and improve performance for common queries on active records.
"""

import sqlite3
from datetime import datetime

from lookervault.storage.models import ContentType

SCHEMA_VERSION = 2


def create_schema(conn: sqlite3.Connection) -> None:
    """Create database schema with all required tables and indexes.

    Args:
        conn: SQLite connection

    Raises:
        StorageError: If schema creation fails
    """
    cursor = conn.cursor()

    # Create schema version table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT
        )
    """)

    # Create content_items table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS content_items (
            id TEXT PRIMARY KEY NOT NULL,
            content_type INTEGER NOT NULL,
            name TEXT NOT NULL,
            owner_id INTEGER,
            owner_email TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            synced_at TEXT NOT NULL,
            deleted_at TEXT DEFAULT NULL,
            content_size INTEGER NOT NULL,
            content_data BLOB NOT NULL,
            folder_id TEXT DEFAULT NULL
        )
    """)

    # Create partial indexes for active records only
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_content_type
        ON content_items(content_type)
        WHERE deleted_at IS NULL
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_owner_id
        ON content_items(owner_id)
        WHERE deleted_at IS NULL
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_updated_at
        ON content_items(updated_at DESC)
        WHERE deleted_at IS NULL
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_deleted_at
        ON content_items(deleted_at)
        WHERE deleted_at IS NOT NULL
    """)

    # Create partial index for folder_id (only for content types that support folders)
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_folder_id
        ON content_items(folder_id)
        WHERE deleted_at IS NULL
          AND folder_id IS NOT NULL
          AND content_type IN (?, ?, ?, ?)
        """,
        (
            ContentType.DASHBOARD.value,
            ContentType.LOOK.value,
            ContentType.BOARD.value,
            ContentType.FOLDER.value,
        ),
    )

    # Create sync_checkpoints table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sync_checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            content_type INTEGER NOT NULL,
            checkpoint_data TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT DEFAULT NULL,
            item_count INTEGER DEFAULT 0,
            error_message TEXT DEFAULT NULL
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_checkpoint_type_completed
        ON sync_checkpoints(content_type, completed_at)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_checkpoint_session
        ON sync_checkpoints(session_id)
    """)

    # Create extraction_sessions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS extraction_sessions (
            id TEXT PRIMARY KEY NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT DEFAULT NULL,
            status TEXT NOT NULL,
            total_items INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            config TEXT,
            metadata TEXT
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_session_started
        ON extraction_sessions(started_at DESC)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_session_status
        ON extraction_sessions(status)
    """)

    # Create restoration_sessions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS restoration_sessions (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL,
            total_items INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            source_instance TEXT,
            destination_instance TEXT NOT NULL,
            config TEXT,
            metadata TEXT
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_restoration_session_status
        ON restoration_sessions(status)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_restoration_session_started
        ON restoration_sessions(started_at DESC)
    """)

    # Create restoration_checkpoints table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS restoration_checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            content_type INTEGER NOT NULL,
            checkpoint_data TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            item_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            FOREIGN KEY (session_id) REFERENCES restoration_sessions(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_restoration_checkpoint_session
        ON restoration_checkpoints(session_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_restoration_checkpoint_type
        ON restoration_checkpoints(content_type)
    """)

    # Create id_mappings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS id_mappings (
            source_instance TEXT NOT NULL,
            content_type INTEGER NOT NULL,
            source_id TEXT NOT NULL,
            destination_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            session_id TEXT,
            PRIMARY KEY (source_instance, content_type, source_id),
            FOREIGN KEY (session_id) REFERENCES restoration_sessions(id) ON DELETE SET NULL
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_id_mapping_dest
        ON id_mappings(destination_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_id_mapping_session
        ON id_mappings(session_id)
    """)

    # Create dead_letter_queue table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dead_letter_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            content_id TEXT NOT NULL,
            content_type INTEGER NOT NULL,
            content_data BLOB NOT NULL,
            error_message TEXT NOT NULL,
            error_type TEXT NOT NULL,
            stack_trace TEXT,
            retry_count INTEGER NOT NULL,
            failed_at TEXT NOT NULL,
            metadata TEXT,
            FOREIGN KEY (session_id) REFERENCES restoration_sessions(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_dlq_session
        ON dead_letter_queue(session_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_dlq_content
        ON dead_letter_queue(content_type, content_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_dlq_failed_at
        ON dead_letter_queue(failed_at DESC)
    """)

    # Migrate existing databases
    _migrate_to_version_2(conn)

    # Record schema version if not already recorded
    cursor.execute(
        "SELECT version FROM schema_version WHERE version = ?",
        (SCHEMA_VERSION,),
    )
    if not cursor.fetchone():
        cursor.execute(
            """
            INSERT INTO schema_version (version, applied_at, description)
            VALUES (?, ?, ?)
        """,
            (
                SCHEMA_VERSION,
                datetime.now().isoformat(),
                "Added folder_id column with partial index",
            ),
        )

    conn.commit()


def _migrate_to_version_2(conn: sqlite3.Connection) -> None:
    """Migrate existing databases from version 1 to version 2.

    Adds folder_id column to content_items table if it doesn't exist.

    Args:
        conn: SQLite connection
    """
    cursor = conn.cursor()

    # Check if folder_id column already exists
    cursor.execute("PRAGMA table_info(content_items)")
    columns = {row[1] for row in cursor.fetchall()}

    if "folder_id" not in columns:
        # Add folder_id column
        cursor.execute("ALTER TABLE content_items ADD COLUMN folder_id TEXT DEFAULT NULL")
        conn.commit()


def optimize_database(conn: sqlite3.Connection) -> None:
    """Apply SQLite optimization settings for performance.

    Args:
        conn: SQLite connection
    """
    cursor = conn.cursor()

    # Optimize for 10MB BLOBs
    cursor.execute("PRAGMA page_size = 16384")  # 16KB pages
    cursor.execute("PRAGMA cache_size = -64000")  # 64MB cache
    cursor.execute("PRAGMA journal_mode = WAL")  # Write-Ahead Logging
    cursor.execute("PRAGMA synchronous = NORMAL")  # Balance safety/speed
    cursor.execute("PRAGMA temp_store = MEMORY")  # Temp tables in RAM

    conn.commit()


def get_schema_version(conn: sqlite3.Connection) -> int | None:
    """Get current schema version.

    Args:
        conn: SQLite connection

    Returns:
        Current schema version or None if not initialized
    """
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        result = cursor.fetchone()
        return result[0] if result else None
    except sqlite3.OperationalError:
        return None
