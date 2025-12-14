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

SCHEMA_VERSION = 3


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

    # Migrate existing databases to add folder_id column before creating index
    _migrate_to_version_2(conn)

    # Create partial index for folder_id (only for content types that support folders)
    # Note: SQLite doesn't allow parameters in CREATE INDEX WHERE clauses, so we hardcode the values
    cursor.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_folder_id
        ON content_items(folder_id)
        WHERE deleted_at IS NULL
          AND folder_id IS NOT NULL
          AND content_type IN ({ContentType.DASHBOARD.value}, {ContentType.LOOK.value}, {ContentType.BOARD.value}, {ContentType.FOLDER.value})
    """)

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
            error_message TEXT DEFAULT NULL,
            UNIQUE(session_id, content_type, started_at)
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
            UNIQUE(session_id, content_type, started_at),
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
            UNIQUE(session_id, content_id, content_type, retry_count),
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

    # Run migrations after all tables are created
    _migrate_to_version_3(conn)

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
                "Added unique constraints for idempotent upsert operations",
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


def _migrate_to_version_3(conn: sqlite3.Connection) -> None:
    """Migrate existing databases from version 2 to version 3.

    Adds unique constraints to enable idempotent upsert operations:
    1. sync_checkpoints: UNIQUE(session_id, content_type, started_at)
    2. restoration_checkpoints: UNIQUE(session_id, content_type, started_at)
    3. dead_letter_queue: UNIQUE(session_id, content_id, content_type, retry_count)

    Args:
        conn: SQLite connection
    """
    cursor = conn.cursor()

    # Check current schema version
    cursor.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
    current_version = cursor.fetchone()
    current_version = current_version[0] if current_version else 0

    if current_version >= 3:
        return  # Already migrated

    # Check if tables exist (fresh database vs. migration)
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name IN ('sync_checkpoints', 'restoration_checkpoints', 'dead_letter_queue')
    """)
    existing_tables = {row[0] for row in cursor.fetchall()}

    # If no tables exist, this is a fresh database - skip migration
    if not existing_tables:
        return

    # SQLite doesn't support ALTER TABLE ADD CONSTRAINT directly
    # We need to recreate tables with new constraints

    # 1. Migrate sync_checkpoints (only if it exists)
    if "sync_checkpoints" in existing_tables:
        cursor.execute("""
            CREATE TABLE sync_checkpoints_tmp (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                content_type INTEGER NOT NULL,
                checkpoint_data TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT DEFAULT NULL,
                item_count INTEGER DEFAULT 0,
                error_message TEXT DEFAULT NULL,
                UNIQUE(session_id, content_type, started_at)
            )
        """)

        cursor.execute("""
            INSERT INTO sync_checkpoints_tmp
            SELECT * FROM sync_checkpoints
        """)

        cursor.execute("DROP TABLE sync_checkpoints")
        cursor.execute("ALTER TABLE sync_checkpoints_tmp RENAME TO sync_checkpoints")

        # Recreate indexes
        cursor.execute("""
            CREATE INDEX idx_checkpoint_type_completed
            ON sync_checkpoints(content_type, completed_at)
        """)
        cursor.execute("""
            CREATE INDEX idx_checkpoint_session
            ON sync_checkpoints(session_id)
        """)

    # 2. Migrate restoration_checkpoints (only if it exists)
    if "restoration_checkpoints" in existing_tables:
        cursor.execute("""
            CREATE TABLE restoration_checkpoints_tmp (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                content_type INTEGER NOT NULL,
                checkpoint_data TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                item_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                UNIQUE(session_id, content_type, started_at),
                FOREIGN KEY (session_id) REFERENCES restoration_sessions(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            INSERT INTO restoration_checkpoints_tmp
            SELECT * FROM restoration_checkpoints
        """)

        cursor.execute("DROP TABLE restoration_checkpoints")
        cursor.execute("ALTER TABLE restoration_checkpoints_tmp RENAME TO restoration_checkpoints")

        # Recreate indexes
        cursor.execute("""
            CREATE INDEX idx_restoration_checkpoint_session
            ON restoration_checkpoints(session_id)
        """)
        cursor.execute("""
            CREATE INDEX idx_restoration_checkpoint_type
            ON restoration_checkpoints(content_type)
        """)

    # 3. Migrate dead_letter_queue (only if it exists)
    if "dead_letter_queue" in existing_tables:
        cursor.execute("""
            CREATE TABLE dead_letter_queue_tmp (
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
                UNIQUE(session_id, content_id, content_type, retry_count),
                FOREIGN KEY (session_id) REFERENCES restoration_sessions(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            INSERT INTO dead_letter_queue_tmp
            SELECT * FROM dead_letter_queue
        """)

        cursor.execute("DROP TABLE dead_letter_queue")
        cursor.execute("ALTER TABLE dead_letter_queue_tmp RENAME TO dead_letter_queue")

        # Recreate indexes
        cursor.execute("""
            CREATE INDEX idx_dlq_session
            ON dead_letter_queue(session_id)
        """)
        cursor.execute("""
            CREATE INDEX idx_dlq_content
            ON dead_letter_queue(content_type, content_id)
        """)
        cursor.execute("""
            CREATE INDEX idx_dlq_failed_at
            ON dead_letter_queue(failed_at DESC)
        """)

    # Record migration
    cursor.execute(
        """
        INSERT INTO schema_version (version, applied_at, description)
        VALUES (?, ?, ?)
        """,
        (
            3,
            datetime.now().isoformat(),
            "Added unique constraints for idempotent upsert operations",
        ),
    )

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
