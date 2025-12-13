"""Configuration loading with environment variable merging."""

import os
import tomllib
from pathlib import Path

import typer

from lookervault.config.models import Configuration
from lookervault.exceptions import ConfigError


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

    Args:
        config_path: Optional path to config file

    Returns:
        Validated Configuration object

    Raises:
        ConfigError: If config file invalid or required values missing
    """
    path = get_config_path(config_path)

    # Try to load from file if it exists
    data = {}
    if path.exists():
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"Invalid TOML syntax in {path}: {e}") from e

        if "lookervault" not in data:
            raise ConfigError(f"Missing 'lookervault' section in {path}")

    # Build or merge environment variables
    if data and "lookervault" in data:
        # Config file exists, merge env vars
        config_data = data["lookervault"]

        if "looker" in config_data:
            looker_config = config_data["looker"]

            # Override with env vars if present
            if client_id := os.getenv("LOOKERVAULT_CLIENT_ID"):
                looker_config["client_id"] = client_id
            if client_secret := os.getenv("LOOKERVAULT_CLIENT_SECRET"):
                looker_config["client_secret"] = client_secret
            if api_url := os.getenv("LOOKERVAULT_API_URL"):
                looker_config["api_url"] = api_url
    else:
        # No config file, build entirely from env vars
        api_url = os.getenv("LOOKERVAULT_API_URL")
        if not api_url:
            raise ConfigError(
                "No config file found and LOOKERVAULT_API_URL environment variable not set. "
                "Either create a config file or set environment variables: "
                "LOOKERVAULT_API_URL, LOOKERVAULT_CLIENT_ID, LOOKERVAULT_CLIENT_SECRET"
            )

        config_data = {
            "looker": {
                "api_url": api_url,
                "client_id": os.getenv("LOOKERVAULT_CLIENT_ID", ""),
                "client_secret": os.getenv("LOOKERVAULT_CLIENT_SECRET", ""),
            }
        }

    try:
        return Configuration(**config_data)  # type: ignore[missing-argument]
    except Exception as e:
        raise ConfigError(f"Invalid configuration: {e}") from e
