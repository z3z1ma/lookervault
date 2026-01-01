"""Custom exception classes for LookerVault."""


class LookerVaultError(Exception):
    """Base exception for all LookerVault errors."""

    pass


class ConfigError(LookerVaultError):
    """Exception raised for configuration errors."""

    pass


class ConnectionError(LookerVaultError):
    """Exception raised for Looker connection errors."""

    pass


class StorageError(LookerVaultError):
    """Exception raised for storage layer errors."""

    pass


class NotFoundError(StorageError):
    """Exception raised when content is not found."""

    pass


class SerializationError(LookerVaultError):
    """Exception raised for serialization/deserialization errors."""

    pass


class ExtractionError(LookerVaultError):
    """Exception raised for content extraction errors."""

    pass


class RateLimitError(ExtractionError):
    """Exception raised when API rate limit is exceeded (retryable)."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: int | None = None):
        """Initialize rate limit error.

        Args:
            message: Error message
            retry_after: Seconds to wait before retrying
        """
        self.retry_after = retry_after
        if retry_after:
            message = f"{message}. Retry after {retry_after}s"
        super().__init__(message)


class OrchestrationError(LookerVaultError):
    """Exception raised for orchestration workflow errors."""

    pass


class ProcessingError(LookerVaultError):
    """Exception raised for batch processing errors."""

    pass


class RestorationError(LookerVaultError):
    """Base exception for content restoration errors."""

    pass


class DeserializationError(RestorationError):
    """Exception raised when content cannot be deserialized from storage.

    This occurs when:
    - Binary blob in database is corrupted or invalid
    - JSON/msgpack format is malformed
    - Content schema doesn't match expected structure
    """

    pass


class ValidationError(LookerVaultError):
    """Exception raised when content fails validation.

    This occurs when:
    - Required fields are missing from content
    - Field values fail type or constraint checks
    - Content structure doesn't match Looker API expectations
    - YAML syntax or structure is invalid
    """

    pass


class DependencyError(RestorationError):
    """Exception raised when content dependencies cannot be resolved.

    This occurs when:
    - Referenced content doesn't exist in source or destination
    - Circular dependencies detected in dependency graph
    - Dependency ordering violation during bulk restoration
    """

    pass


class IDMappingError(RestorationError):
    """Exception raised when ID mapping fails during cross-instance restoration.

    This occurs when:
    - Source ID cannot be mapped to destination ID
    - ID mapping table is inconsistent or corrupted
    - Foreign key references cannot be translated
    """

    pass
