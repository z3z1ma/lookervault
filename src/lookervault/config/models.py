"""Pydantic models for configuration and data structures."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, HttpUrl


class LookerConfig(BaseModel):
    """Looker API connection configuration."""

    api_url: HttpUrl
    client_id: Optional[str] = ""
    client_secret: Optional[str] = ""
    timeout: int = Field(default=30, ge=5, le=300)
    verify_ssl: bool = True


class OutputConfig(BaseModel):
    """Output formatting preferences for CLI commands."""

    default_format: Literal["table", "json"] = "table"
    color_enabled: bool = True


class Configuration(BaseModel):
    """Complete LookerVault configuration."""

    config_version: str
    looker: LookerConfig
    output: OutputConfig = OutputConfig()


class ConnectionStatus(BaseModel):
    """Current state of connectivity to a Looker instance."""

    connected: bool
    authenticated: bool
    instance_url: Optional[str] = None
    looker_version: Optional[str] = None
    api_version: Optional[str] = None
    user_id: Optional[int] = None
    user_email: Optional[str] = None
    error_message: Optional[str] = None


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
