"""Pydantic models for configuration and data structures."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


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
