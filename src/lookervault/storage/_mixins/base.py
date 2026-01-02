"""Base database connection and retry logic for storage mixins."""

import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from lookervault.constants import DEFAULT_MAX_RETRIES, SQLITE_BUSY_TIMEOUT_SECONDS
from lookervault.exceptions import StorageError
from lookervault.storage.schema import create_schema, optimize_database

logger = logging.getLogger(__name__)

T = TypeVar("T")


class DatabaseConnectionMixin:
    """Mixin providing thread-local database connection management and retry logic.

    This mixin provides the foundational database operations that all other
    storage mixins depend on. It handles:
    - Thread-local SQLite connections for parallel access
    - Connection lifecycle management
    - Retry logic with exponential backoff for SQLITE_BUSY errors
    - Database schema initialization
    """

    db_path: Path
    _local: threading.local

    def __init__(self, db_path: str | Path, **kwargs: object) -> None:
        """Initialize database connection management.

        Args:
            db_path: Path to SQLite database file
            **kwargs: Forwarded to parent classes for cooperative inheritance
        """
        super().__init__(**kwargs)
        object.__setattr__(self, "db_path", Path(db_path))
        object.__setattr__(self, "_local", threading.local())

        self.db_path.parent.mkdir(parents=True, exist_ok=True)

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
            timeout=float(
                SQLITE_BUSY_TIMEOUT_SECONDS
            ),  # 60 second busy timeout for lock contention
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

    def _retry_on_busy(
        self,
        operation: Callable[[], T],
        max_retries: int = DEFAULT_MAX_RETRIES,
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
        last_error: Exception | None = None
        delay: float = initial_delay

        for attempt in range(max_retries):
            try:
                return operation()
            except sqlite3.OperationalError as e:
                last_error = e
                if "database is locked" in str(e).lower() or "busy" in str(e).lower():
                    if attempt < max_retries - 1:
                        # Exponential backoff with jitter
                        jitter: float = (
                            delay * 0.1 * (hash(threading.current_thread().name) % 10) / 10
                        )
                        sleep_time: float = delay + jitter
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
