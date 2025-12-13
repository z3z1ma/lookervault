"""SQLite schema creation and management."""

import sqlite3
from datetime import datetime

SCHEMA_VERSION = 1


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
            content_data BLOB NOT NULL
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
            (SCHEMA_VERSION, datetime.now().isoformat(), "Initial schema"),
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
