"""Magic number constants used throughout the LookerVault codebase.

This module centralizes numeric values that would otherwise be magic numbers,
improving code readability and maintainability.
"""

# File I/O chunk sizes (bytes)
CHUNK_SIZE_SMALL = 8192  # 8KB - for checksum calculation
CHUNK_SIZE_GCS = 8 * 1024 * 1024  # 8MB - recommended by GCS for uploads/downloads

# Time-based constants (seconds)
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400

# Time-based constants (for display/formatting)
MINUTES_PER_HOUR = 60
HOURS_PER_DAY = 24
DAYS_PER_WEEK = 7
DAYS_PER_MONTH = 30

# Retry and timeout constants
DEFAULT_MAX_RETRIES = 5
DEFAULT_MAX_RETRIES_NETWORK = 3
DEFAULT_RETRY_DELAY_SECONDS = 1
DEFAULT_MAX_RETRY_WAIT_SECONDS = 120
DEFAULT_RETRY_MAX_WAIT_SECONDS = 60
SQLITE_BUSY_TIMEOUT_SECONDS = 60

# Rate limiter constants
RATE_LIMIT_SUCCESS_THRESHOLD = 10  # Consecutive successes before reducing backoff
RATE_LIMIT_BACKOFF_INCREASE_MULTIPLIER = 1.5  # Exponential backoff multiplier
RATE_LIMIT_BACKOFF_REDUCTION_FACTOR = 0.9  # 10% reduction per recovery cycle
RATE_LIMIT_MIN_BACKOFF_MULTIPLIER = 1.0  # Normal speed baseline

# GCS timeout constants
GCS_UPLOAD_TIMEOUT_SECONDS = 3600  # 1 hour for large files
GCS_DOWNLOAD_TIMEOUT_SECONDS = 3600  # 1 hour for large files
GCS_TOTAL_TIMEOUT_SECONDS = 600  # 10 minutes total operation timeout

# Checkpoint and batch constants
DEFAULT_CHECKPOINT_INTERVAL = 100
DEFAULT_BATCH_SIZE = 100

# Progress logging interval
PROGRESS_LOGGING_INTERVAL = 100

# Buffer size calculations
DEFAULT_QUEUE_MULTIPLIER = 100  # queue_size = workers * multiplier

# Memory conversion constants
BYTES_PER_KB = 1024
BYTES_PER_MB = 1024 * 1024
BYTES_PER_GB = 1024**3

# Percentage calculations
PERCENTAGE_MULTIPLIER = 100.0
PERCENTAGE_MAX = 100.0

# Retention policy defaults
RETENTION_MIN_DAYS = 30
RETENTION_MIN_COUNT = 5

# Snapshot cache TTL
DEFAULT_CACHE_TTL_MINUTES = 5

# Preview limits for CLI output
PREVIEW_LIMIT_DEFAULT = 10
PREVIEW_LIMIT_SMALL = 5
PREVIEW_LIMIT_TINY = 3

# Compression
DEFAULT_COMPRESSION_LEVEL = 6

# Bucket name validation
BUCKET_NAME_MIN_LENGTH = 3
SUGGESTIONS_LIMIT = 3

# Ping count for network diagnostics
NETWORK_PING_COUNT = 5
