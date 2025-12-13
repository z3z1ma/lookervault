"""Configuration validation and readiness checks."""

import os
import sys
from datetime import datetime
from pathlib import Path

from lookervault.config.loader import get_config_path, load_config
from lookervault.config.models import CheckItem, ReadinessCheckResult
from lookervault.exceptions import ConfigError


def check_config_file(config_path: Path | None = None) -> CheckItem:
    """
    Check if configuration file exists.

    Args:
        config_path: Optional path to config file

    Returns:
        CheckItem with result
    """
    try:
        path = get_config_path(config_path)
        if path.exists():
            return CheckItem(
                name="Configuration File Found",
                status="pass",
                message=f"Found at {path}",
            )
        else:
            # Check if environment variables are set as alternative
            has_api_url = bool(os.getenv("LOOKERVAULT_API_URL"))
            if has_api_url:
                return CheckItem(
                    name="Configuration File Found",
                    status="warning",
                    message=f"Not found at {path}, using environment variables",
                )
            else:
                return CheckItem(
                    name="Configuration File Found",
                    status="fail",
                    message=f"Not found at {path} and LOOKERVAULT_API_URL not set",
                )
    except Exception as e:
        return CheckItem(
            name="Configuration File Found",
            status="fail",
            message=str(e),
        )


def check_config_valid(config_path: Path | None = None) -> CheckItem:
    """
    Check if configuration is valid.

    Args:
        config_path: Optional path to config file

    Returns:
        CheckItem with result
    """
    try:
        load_config(config_path)
        path = get_config_path(config_path)

        # Check if config was loaded from file or env vars
        if path.exists():
            return CheckItem(
                name="Configuration Valid",
                status="pass",
                message="TOML syntax and schema valid",
            )
        else:
            # Config loaded from environment variables
            return CheckItem(
                name="Configuration Valid",
                status="pass",
                message="Configuration built from environment variables",
            )
    except ConfigError as e:
        return CheckItem(
            name="Configuration Valid",
            status="fail",
            message=str(e),
        )
    except Exception as e:
        return CheckItem(
            name="Configuration Valid",
            status="fail",
            message=f"Unexpected error: {str(e)}",
        )


def check_credentials(config_path: Path | None = None) -> CheckItem:
    """
    Check if credentials are configured.

    Args:
        config_path: Optional path to config file

    Returns:
        CheckItem with result
    """
    try:
        config = load_config(config_path)

        # Check if both client_id and client_secret are set
        has_id = bool(config.looker.client_id)
        has_secret = bool(config.looker.client_secret)

        if has_id and has_secret:
            return CheckItem(
                name="Credentials Configured",
                status="pass",
                message="client_id and client_secret are set",
            )
        elif has_id and not has_secret:
            return CheckItem(
                name="Credentials Configured",
                status="warning",
                message="client_secret not set (required for Looker connection)",
            )
        elif not has_id and has_secret:
            return CheckItem(
                name="Credentials Configured",
                status="warning",
                message="client_id not set (required for Looker connection)",
            )
        else:
            return CheckItem(
                name="Credentials Configured",
                status="warning",
                message="client_id and client_secret not set (required for Looker connection)",
            )
    except ConfigError:
        return CheckItem(
            name="Credentials Configured",
            status="fail",
            message="Cannot check credentials - config invalid",
        )
    except Exception as e:
        return CheckItem(
            name="Credentials Configured",
            status="fail",
            message=f"Error: {str(e)}",
        )


def check_python_version() -> CheckItem:
    """
    Check if Python version meets requirements.

    Returns:
        CheckItem with result
    """
    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"

    # Require Python 3.11+
    if version.major >= 3 and version.minor >= 11:
        return CheckItem(
            name="Python Version",
            status="pass",
            message=version_str,
        )
    else:
        return CheckItem(
            name="Python Version",
            status="warning",
            message=f"{version_str} (Python 3.11+ recommended)",
        )


def check_dependencies() -> CheckItem:
    """
    Check if required dependencies are available.

    Returns:
        CheckItem with result
    """
    missing = []

    try:
        import looker_sdk  # noqa: F401
    except ImportError:
        missing.append("looker-sdk")

    try:
        import typer  # noqa: F401
    except ImportError:
        missing.append("typer")

    try:
        import pydantic  # noqa: F401
    except ImportError:
        missing.append("pydantic")

    if not missing:
        return CheckItem(
            name="Required Dependencies",
            status="pass",
            message="All dependencies available",
        )
    else:
        return CheckItem(
            name="Required Dependencies",
            status="fail",
            message=f"Missing: {', '.join(missing)}",
        )


def perform_readiness_check(config_path: Path | None = None) -> ReadinessCheckResult:
    """
    Perform all readiness checks.

    Args:
        config_path: Optional path to config file

    Returns:
        ReadinessCheckResult with all check results
    """
    checks = [
        check_config_file(config_path),
        check_config_valid(config_path),
        check_credentials(config_path),
        check_python_version(),
        check_dependencies(),
    ]

    # System is ready only if all checks pass (warnings are allowed)
    ready = all(check.status in ["pass", "warning"] for check in checks)

    # If any check fails, not ready
    if any(check.status == "fail" for check in checks):
        ready = False

    return ReadinessCheckResult(
        ready=ready,
        checks=checks,
        timestamp=datetime.now(),
    )
