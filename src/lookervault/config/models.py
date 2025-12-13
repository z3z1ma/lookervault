"""Pydantic models for configuration and data structures."""

import os
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class LookerConfig(BaseModel):
    """Looker API connection configuration."""

    api_url: HttpUrl
    client_id: str | None = ""
    client_secret: str | None = ""
    timeout: int = Field(default=120, ge=5, le=600)  # Increased to 120s for large instances
    verify_ssl: bool = True


class OutputConfig(BaseModel):
    """Output formatting preferences for CLI commands."""

    default_format: Literal["table", "json"] = "table"
    color_enabled: bool = True


class Configuration(BaseModel):
    """Complete LookerVault configuration."""

    config_version: str = "1.0"
    looker: LookerConfig
    output: OutputConfig = OutputConfig()


class ConnectionStatus(BaseModel):
    """Current state of connectivity to a Looker instance."""

    connected: bool
    authenticated: bool
    instance_url: str | None = None
    looker_version: str | None = None
    api_version: str | None = None
    user_id: int | None = None
    user_email: str | None = None
    error_message: str | None = None


class LookerInstance(BaseModel):
    """Metadata about a Looker instance retrieved from the API."""

    looker_release_version: str
    api_server_url: str
    web_server_url: str
    current_api_version: str
    supported_api_versions: list[str]


class CheckItem(BaseModel):
    """Individual readiness check result."""

    name: str
    status: Literal["pass", "fail", "warning"]
    message: str


class ReadinessCheckResult(BaseModel):
    """Result of a system readiness check."""

    ready: bool
    checks: list[CheckItem]
    timestamp: datetime


class ParallelConfig(BaseModel):
    """Configuration for parallel content extraction execution.

    Controls worker thread pool size, work queue depth, batch sizing,
    and API rate limiting for parallel extraction operations.

    Examples:
        >>> # Default configuration (8 workers on 8-core machine)
        >>> config = ParallelConfig()

        >>> # High-throughput configuration
        >>> config = ParallelConfig(workers=16, queue_size=1600, batch_size=200)

        >>> # Sequential fallback (no parallelism)
        >>> config = ParallelConfig(workers=1, queue_size=10)
    """

    workers: int = Field(
        default_factory=lambda: min(os.cpu_count() or 1, 8),
        ge=1,
        le=50,
        description="Number of worker threads in the thread pool (1-50)",
    )

    queue_size: int = Field(
        default=0,  # Will be set to workers * 100 in validator
        ge=10,
        description="Maximum depth of work queue (bounded queue for backpressure)",
    )

    batch_size: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Number of items per work batch",
    )

    rate_limit_per_minute: int = Field(
        default=100,
        gt=0,
        description="Maximum API requests per minute across all workers",
    )

    rate_limit_per_second: int = Field(
        default=10,
        gt=0,
        description="Maximum API requests per second (burst allowance)",
    )

    adaptive_rate_limiting: bool = Field(
        default=True,
        description="Enable adaptive backoff when HTTP 429 detected",
    )

    @model_validator(mode="after")
    def validate_queue_size(self) -> "ParallelConfig":
        """Ensure queue_size is appropriate for worker count.

        Queue size must be at least workers * 10 to prevent worker starvation.
        If not explicitly set, defaults to workers * 100 for good throughput.

        Returns:
            Validated ParallelConfig instance

        Raises:
            ValueError: If queue_size < workers * 10
        """
        # Auto-calculate queue_size if not explicitly set (default=0)
        if self.queue_size == 0:
            self.queue_size = self.workers * 100

        # Validate minimum queue size
        min_queue_size = self.workers * 10
        if self.queue_size < min_queue_size:
            raise ValueError(
                f"queue_size ({self.queue_size}) must be at least workers * 10 "
                f"({min_queue_size}) to prevent worker starvation"
            )

        return self

    @model_validator(mode="after")
    def validate_rate_limits(self) -> "ParallelConfig":
        """Ensure rate limits are consistent.

        Rate limit per second (burst) should not exceed rate limit per minute
        to avoid impossible configuration.

        Returns:
            Validated ParallelConfig instance

        Raises:
            ValueError: If rate_limit_per_second > rate_limit_per_minute
        """
        # Convert to per-second rates for comparison
        max_per_second_from_minute = self.rate_limit_per_minute / 60.0

        if self.rate_limit_per_second > self.rate_limit_per_minute:
            raise ValueError(
                f"rate_limit_per_second ({self.rate_limit_per_second}) cannot exceed "
                f"rate_limit_per_minute ({self.rate_limit_per_minute})"
            )

        return self

    def __str__(self) -> str:
        """Return human-readable configuration summary."""
        return (
            f"ParallelConfig(workers={self.workers}, queue={self.queue_size}, "
            f"batch={self.batch_size}, rate={self.rate_limit_per_minute}/min)"
        )
