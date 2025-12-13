"""Configuration loading with environment variable merging."""

import os
import tomllib
from pathlib import Path
from typing import Optional

import typer

from .models import Configuration
from ..exceptions import ConfigError


def get_config_path(config_arg: Optional[Path] = None) -> Path:
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


def load_config(config_path: Optional[Path] = None) -> Configuration:
    """
    Load and validate configuration from TOML file and environment variables.

    Environment variables override config file values:
    - LOOKERVAULT_CLIENT_ID
    - LOOKERVAULT_CLIENT_SECRET
    - LOOKERVAULT_API_URL

    Args:
        config_path: Optional path to config file

    Returns:
        Validated Configuration object

    Raises:
        ConfigError: If config file not found or invalid
    """
    path = get_config_path(config_path)

    if not path.exists():
        raise ConfigError(f"Configuration file not found: {path}")

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Invalid TOML syntax in {path}: {e}")

    if "lookervault" not in data:
        raise ConfigError(f"Missing 'lookervault' section in {path}")

    # Merge environment variables
    if "looker" in data["lookervault"]:
        looker_config = data["lookervault"]["looker"]

        # Override with env vars if present
        if client_id := os.getenv("LOOKERVAULT_CLIENT_ID"):
            looker_config["client_id"] = client_id
        if client_secret := os.getenv("LOOKERVAULT_CLIENT_SECRET"):
            looker_config["client_secret"] = client_secret
        if api_url := os.getenv("LOOKERVAULT_API_URL"):
            looker_config["api_url"] = api_url

    try:
        return Configuration(**data["lookervault"])
    except Exception as e:
        raise ConfigError(f"Invalid configuration: {e}")
