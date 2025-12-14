"""Configuration validation and readiness checks."""

import os
import re
import sys
from datetime import datetime
from pathlib import Path

from lookervault.config.loader import get_config_path, load_config
from lookervault.config.models import CheckItem, ReadinessCheckResult
from lookervault.exceptions import ConfigError

# Valid GCS regions (as of 2025)
# Source: https://cloud.google.com/storage/docs/locations
VALID_GCS_REGIONS = {
    # North America
    "northamerica-northeast1",  # Montréal
    "northamerica-northeast2",  # Toronto
    "us-central1",  # Iowa
    "us-east1",  # South Carolina
    "us-east4",  # Northern Virginia
    "us-east5",  # Columbus
    "us-south1",  # Dallas
    "us-west1",  # Oregon
    "us-west2",  # Los Angeles
    "us-west3",  # Salt Lake City
    "us-west4",  # Las Vegas
    # South America
    "southamerica-east1",  # São Paulo
    "southamerica-west1",  # Santiago
    # Europe
    "europe-central2",  # Warsaw
    "europe-north1",  # Finland
    "europe-southwest1",  # Madrid
    "europe-west1",  # Belgium
    "europe-west2",  # London
    "europe-west3",  # Frankfurt
    "europe-west4",  # Netherlands
    "europe-west6",  # Zürich
    "europe-west8",  # Milan
    "europe-west9",  # Paris
    "europe-west10",  # Berlin
    "europe-west12",  # Turin
    # Asia Pacific
    "asia-east1",  # Taiwan
    "asia-east2",  # Hong Kong
    "asia-northeast1",  # Tokyo
    "asia-northeast2",  # Osaka
    "asia-northeast3",  # Seoul
    "asia-south1",  # Mumbai
    "asia-south2",  # Delhi
    "asia-southeast1",  # Singapore
    "asia-southeast2",  # Jakarta
    # Australia
    "australia-southeast1",  # Sydney
    "australia-southeast2",  # Melbourne
    # Middle East
    "me-central1",  # Doha
    "me-west1",  # Tel Aviv
    # Africa
    "africa-south1",  # Johannesburg
}

# Valid GCS multi-regions
VALID_GCS_MULTI_REGIONS = {
    "us",  # Multi-region: US
    "eu",  # Multi-region: EU
    "asia",  # Multi-region: Asia
}

# Combined set of all valid locations
VALID_GCS_LOCATIONS = VALID_GCS_REGIONS | VALID_GCS_MULTI_REGIONS


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


def validate_gcs_bucket_name(bucket_name: str) -> tuple[bool, str]:
    """
    Validate GCS bucket name according to Google Cloud Storage naming rules.

    Args:
        bucket_name: The bucket name to validate

    Returns:
        Tuple of (is_valid, error_message). error_message is empty string if valid.

    References:
        https://cloud.google.com/storage/docs/buckets#naming
    """
    if not bucket_name:
        return False, "Bucket name cannot be empty"

    # Length constraints
    if len(bucket_name) < 3:
        return False, "Bucket name must be at least 3 characters"
    if len(bucket_name) > 63:
        return False, "Bucket name must not exceed 63 characters"

    # Character constraints
    # GCS bucket names must contain only lowercase letters, numbers, hyphens, underscores, and periods
    if not re.match(r"^[a-z0-9._-]+$", bucket_name):
        return (
            False,
            "Bucket name must contain only lowercase letters, numbers, hyphens, underscores, and periods",
        )

    # Must start and end with alphanumeric
    if not bucket_name[0].isalnum() or not bucket_name[-1].isalnum():
        return False, "Bucket name must start and end with a letter or number"

    # Cannot contain consecutive periods
    if ".." in bucket_name:
        return False, "Bucket name cannot contain consecutive periods"

    # Cannot be formatted as IP address
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", bucket_name):
        return False, "Bucket name cannot be formatted as an IP address"

    # Cannot start with "goog" prefix
    if bucket_name.startswith("goog"):
        return False, 'Bucket name cannot start with "goog" prefix'

    # Cannot contain "google" or close misspellings
    if "google" in bucket_name.lower():
        return False, 'Bucket name cannot contain "google"'

    return True, ""


def validate_gcs_region(region: str) -> tuple[bool, str]:
    """
    Validate GCS region/location code.

    Args:
        region: The region code to validate

    Returns:
        Tuple of (is_valid, error_message). error_message is empty string if valid.
    """
    if not region:
        return False, "Region cannot be empty"

    region_lower = region.lower()

    if region_lower in VALID_GCS_LOCATIONS:
        return True, ""

    # Provide helpful error message with suggestions
    suggestions = [r for r in VALID_GCS_LOCATIONS if region_lower in r or r in region_lower]
    if suggestions:
        return (
            False,
            f"Invalid GCS region '{region}'. Did you mean one of: {', '.join(sorted(suggestions)[:3])}?",
        )

    return (
        False,
        f"Invalid GCS region '{region}'. Must be a valid GCS region or multi-region (e.g., 'us-central1', 'europe-west1', 'us', 'eu', 'asia')",
    )


def validate_compression_level(level: int) -> tuple[bool, str]:
    """
    Validate gzip compression level.

    Args:
        level: The compression level to validate

    Returns:
        Tuple of (is_valid, error_message). error_message is empty string if valid.
    """
    if not isinstance(level, int):
        return False, f"Compression level must be an integer, got {type(level).__name__}"

    if not 1 <= level <= 9:
        return (
            False,
            f"Compression level must be between 1 (fastest) and 9 (best compression), got {level}",
        )

    return True, ""


def check_snapshot_config(config_path: Path | None = None) -> CheckItem:
    """
    Check if snapshot configuration is valid (if present).

    Args:
        config_path: Optional path to config file

    Returns:
        CheckItem with result
    """
    try:
        config = load_config(config_path)

        # Snapshot config is optional
        if config.snapshot is None:
            return CheckItem(
                name="Snapshot Configuration",
                status="pass",
                message="Not configured (optional)",
            )

        errors = []

        # Validate bucket name
        is_valid, error_msg = validate_gcs_bucket_name(config.snapshot.provider.bucket_name)
        if not is_valid:
            errors.append(f"bucket_name: {error_msg}")

        # Validate region
        is_valid, error_msg = validate_gcs_region(config.snapshot.provider.region)
        if not is_valid:
            errors.append(f"region: {error_msg}")

        # Validate compression level
        if config.snapshot.provider.compression_enabled:
            is_valid, error_msg = validate_compression_level(
                config.snapshot.provider.compression_level
            )
            if not is_valid:
                errors.append(f"compression_level: {error_msg}")

        # Check if credentials path exists (if specified)
        if config.snapshot.provider.credentials_path:
            creds_path = Path(config.snapshot.provider.credentials_path).expanduser()
            if not creds_path.exists():
                errors.append(
                    f"credentials_path: File not found at {config.snapshot.provider.credentials_path}"
                )

        if errors:
            return CheckItem(
                name="Snapshot Configuration",
                status="fail",
                message=f"Validation errors: {'; '.join(errors)}",
            )

        return CheckItem(
            name="Snapshot Configuration",
            status="pass",
            message=f"Valid (bucket: {config.snapshot.provider.bucket_name}, region: {config.snapshot.provider.region})",
        )

    except ConfigError as e:
        return CheckItem(
            name="Snapshot Configuration",
            status="fail",
            message=f"Config error: {str(e)}",
        )
    except Exception as e:
        return CheckItem(
            name="Snapshot Configuration",
            status="fail",
            message=f"Unexpected error: {str(e)}",
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
        check_snapshot_config(config_path),
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
