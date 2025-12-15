"""Configuration loading with environment variable merging."""

import os
import tomllib
from pathlib import Path
from typing import Any

import typer

from lookervault.config.models import Configuration
from lookervault.exceptions import ConfigError
from lookervault.snapshot.models import (
    GCSStorageProvider,
    RetentionPolicy,
    SnapshotConfig,
)


def get_db_path(db_path_arg: str | None = None) -> str:
    """
    Get database path with priority order.

    Priority:
    1. Command-line argument
    2. LOOKERVAULT_DB_PATH environment variable
    3. Default: "looker.db"

    Args:
        db_path_arg: Optional database path from command-line argument

    Returns:
        Database path to use
    """
    # 1. Command-line argument
    if db_path_arg:
        return db_path_arg

    # 2. Environment variable
    if env_db_path := os.getenv("LOOKERVAULT_DB_PATH"):
        return env_db_path

    # 3. Default
    return "looker.db"


def get_config_path(config_arg: Path | None = None) -> Path:
    """
    Get configuration file path with priority order.

    Priority:
    1. Command-line argument
    2. LOOKERVAULT_CONFIG environment variable
    3. ~/.lookervault/config.toml (user home directory)
    4. ./lookervault.toml (current working directory)

    Args:
        config_arg: Optional path from command-line argument

    Returns:
        Path to configuration file (may not exist)
    """
    # 1. Command-line argument
    if config_arg:
        return config_arg

    # 2. Environment variable
    env_config = os.getenv("LOOKERVAULT_CONFIG")
    if env_config:
        return Path(env_config)

    # 3. User home directory
    app_dir = Path(typer.get_app_dir("lookervault"))
    user_config = app_dir / "config.toml"
    if user_config.exists():
        return user_config

    # 4. Current directory
    cwd_config = Path("lookervault.toml")
    if cwd_config.exists():
        return cwd_config

    # Default (may not exist)
    return user_config


def load_config(config_path: Path | None = None) -> Configuration:
    """
    Load and validate configuration from TOML file and environment variables.

    Environment variables override config file values (or provide all values if no file exists):
    - LOOKERVAULT_CLIENT_ID
    - LOOKERVAULT_CLIENT_SECRET
    - LOOKERVAULT_API_URL
    - LOOKERVAULT_TIMEOUT (optional, default: 120 seconds)
    - LOOKERVAULT_DB_PATH (optional, default database path)
    - LOOKER_BASE_URL (alias for LOOKERVAULT_API_URL)
    - LOOKER_CLIENT_ID (alias for LOOKERVAULT_CLIENT_ID)
    - LOOKER_CLIENT_SECRET (alias for LOOKERVAULT_CLIENT_SECRET)

    Args:
        config_path: Optional path to config file

    Returns:
        Validated Configuration object

    Raises:
        ConfigError: If config file invalid or required values missing
    """
    path = get_config_path(config_path)

    # Try to load from file if it exists
    data: dict[str, Any] = {}
    if path.exists():
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"Invalid TOML syntax in {path}: {e}") from e

    # Build or merge environment variables
    if data:
        # Config file exists, merge env vars
        if "looker" in data:
            looker_config = data["looker"]

            # Override with env vars if present (support both LOOKERVAULT_ and LOOKER_ prefixes)
            if client_id := (os.getenv("LOOKERVAULT_CLIENT_ID") or os.getenv("LOOKER_CLIENT_ID")):
                looker_config["client_id"] = client_id
            if client_secret := (
                os.getenv("LOOKERVAULT_CLIENT_SECRET") or os.getenv("LOOKER_CLIENT_SECRET")
            ):
                looker_config["client_secret"] = client_secret
            if api_url := (os.getenv("LOOKERVAULT_API_URL") or os.getenv("LOOKER_BASE_URL")):
                looker_config["api_url"] = api_url
            if timeout_str := os.getenv("LOOKERVAULT_TIMEOUT"):
                try:
                    looker_config["timeout"] = int(timeout_str)
                except ValueError:
                    raise ConfigError(f"Invalid LOOKERVAULT_TIMEOUT value: {timeout_str}") from None
    else:
        # No config file, build entirely from env vars
        api_url = os.getenv("LOOKERVAULT_API_URL") or os.getenv("LOOKER_BASE_URL")
        if not api_url:
            raise ConfigError(
                "No config file found and LOOKERVAULT_API_URL/LOOKER_BASE_URL environment variable not set. "
                "Either create a config file or set environment variables: "
                "LOOKERVAULT_API_URL (or LOOKER_BASE_URL), LOOKERVAULT_CLIENT_ID (or LOOKER_CLIENT_ID), "
                "LOOKERVAULT_CLIENT_SECRET (or LOOKER_CLIENT_SECRET)"
            )

        looker_config: dict[str, Any] = {
            "api_url": api_url,
            "client_id": os.getenv("LOOKERVAULT_CLIENT_ID") or os.getenv("LOOKER_CLIENT_ID", ""),
            "client_secret": os.getenv("LOOKERVAULT_CLIENT_SECRET")
            or os.getenv("LOOKER_CLIENT_SECRET", ""),
        }

        # Add timeout if specified
        if timeout_str := os.getenv("LOOKERVAULT_TIMEOUT"):
            try:
                looker_config["timeout"] = int(timeout_str)
            except ValueError:
                raise ConfigError(f"Invalid LOOKERVAULT_TIMEOUT value: {timeout_str}") from None

        data = {"looker": looker_config}

    # Load snapshot configuration if present (optional section)
    if "snapshot" in data:
        snapshot_data = data["snapshot"]

        # Override with environment variables if present
        if bucket_name := os.getenv("LOOKERVAULT_GCS_BUCKET"):
            snapshot_data["bucket_name"] = bucket_name
        if project_id := os.getenv("LOOKERVAULT_GCS_PROJECT"):
            snapshot_data["project_id"] = project_id
        if region := os.getenv("LOOKERVAULT_GCS_REGION"):
            snapshot_data["region"] = region
        if credentials_path := os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            snapshot_data["credentials_path"] = credentials_path

        # Override retention policy from environment
        if "retention" not in snapshot_data:
            snapshot_data["retention"] = {}
        if min_days_str := os.getenv("LOOKERVAULT_RETENTION_MIN_DAYS"):
            try:
                snapshot_data["retention"]["min_days"] = int(min_days_str)
            except ValueError:
                raise ConfigError(
                    f"Invalid LOOKERVAULT_RETENTION_MIN_DAYS value: {min_days_str}"
                ) from None
        if max_days_str := os.getenv("LOOKERVAULT_RETENTION_MAX_DAYS"):
            try:
                snapshot_data["retention"]["max_days"] = int(max_days_str)
            except ValueError:
                raise ConfigError(
                    f"Invalid LOOKERVAULT_RETENTION_MAX_DAYS value: {max_days_str}"
                ) from None
        if min_count_str := os.getenv("LOOKERVAULT_RETENTION_MIN_COUNT"):
            try:
                snapshot_data["retention"]["min_count"] = int(min_count_str)
            except ValueError:
                raise ConfigError(
                    f"Invalid LOOKERVAULT_RETENTION_MIN_COUNT value: {min_count_str}"
                ) from None

        # Parse retention policy
        retention_data = snapshot_data.get("retention", {})
        retention = RetentionPolicy(**retention_data)

        # Parse GCS provider config
        provider_data = {
            k: v
            for k, v in snapshot_data.items()
            if k not in ["retention", "cache_ttl_minutes", "audit_log_path", "audit_gcs_bucket"]
        }
        provider = GCSStorageProvider(**provider_data)

        # Parse snapshot config
        data["snapshot"] = SnapshotConfig(
            provider=provider,
            retention=retention,
            cache_ttl_minutes=snapshot_data.get("cache_ttl_minutes", 5),
            audit_log_path=snapshot_data.get("audit_log_path", "~/.lookervault/audit.log"),
            audit_gcs_bucket=snapshot_data.get("audit_gcs_bucket"),
        )

    try:
        return Configuration(**data)  # type: ignore[missing-argument]
    except Exception as e:
        raise ConfigError(f"Invalid configuration: {e}") from e
