"""Pydantic models for cloud snapshot management."""

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, computed_field, field_validator

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


class BackupTag(str, Enum):
    """Tags for categorizing backup snapshots."""

    PRODUCTION = "production"
    STAGING = "staging"
    CRITICAL = "critical"


class SnapshotMetadata(BaseModel):
    """Metadata about a single snapshot stored in Google Cloud Storage."""

    sequential_index: int = Field(..., description="User-facing index (1, 2, 3...)")
    filename: str = Field(..., description="Full blob name in GCS")
    timestamp: datetime = Field(..., description="UTC timestamp extracted from filename")
    size_bytes: int = Field(..., description="Size of the snapshot file in bytes")
    gcs_bucket: str = Field(..., description="GCS bucket name")
    gcs_path: str = Field(..., description="Full GCS path (gs://bucket/prefix/filename)")
    crc32c: str = Field(..., description="Base64-encoded CRC32C checksum")
    content_encoding: str | None = Field(None, description="Content encoding (e.g., 'gzip')")
    tags: list[str] = Field(default_factory=list, description="Protection tags")
    created: datetime = Field(..., description="Blob creation timestamp in GCS")
    updated: datetime = Field(..., description="Last modified timestamp in GCS")

    @computed_field
    @property
    def size_mb(self) -> float:
        """Computed property: size in megabytes."""
        return round(self.size_bytes / (1024 * 1024), 1)

    @computed_field
    @property
    def age_days(self) -> int:
        """Computed property: age in days since creation."""
        now = datetime.now(UTC)
        age = now - self.created.replace(tzinfo=UTC)
        return age.days

    @field_validator("sequential_index")
    @classmethod
    def validate_sequential_index(cls, v: int) -> int:
        """Validate sequential index is positive."""
        if v < 1:
            raise ValueError("Sequential index must be positive")
        return v

    @field_validator("size_bytes")
    @classmethod
    def validate_size_bytes(cls, v: int) -> int:
        """Validate size is non-negative."""
        if v < 0:
            raise ValueError("Size must be non-negative")
        return v


class RetentionPolicy(BaseModel):
    """Defines how long snapshots are retained and when they are deleted."""

    min_days: int = Field(30, description="Minimum retention period in days (safety mechanism)")
    max_days: int = Field(90, description="Maximum retention period in days (cost control)")
    min_count: int = Field(5, description="Minimum number of snapshots to always retain")
    lock_policy: bool = Field(
        False, description="Whether to lock GCS retention policy (irreversible)"
    )
    enabled: bool = Field(True, description="Whether retention policy enforcement is enabled")

    @field_validator("min_days")
    @classmethod
    def validate_min_days(cls, v: int) -> int:
        """Validate minimum retention is at least 1 day."""
        if v < 1:
            raise ValueError("Minimum retention must be at least 1 day")
        return v

    @field_validator("max_days")
    @classmethod
    def validate_max_days(cls, v: int, info) -> int:
        """Validate maximum retention is >= minimum retention."""
        min_days = info.data.get("min_days", 30)
        if v < min_days:
            raise ValueError(f"Maximum retention ({v}) must be >= minimum retention ({min_days})")
        return v

    @field_validator("min_count")
    @classmethod
    def validate_min_count(cls, v: int) -> int:
        """Validate minimum count is non-negative."""
        if v < 0:
            raise ValueError("Minimum count must be >= 0")
        return v


class GCSStorageProvider(BaseModel):
    """Configuration for Google Cloud Storage connection and operations."""

    bucket_name: str = Field(..., description="GCS bucket name for snapshot storage")
    project_id: str | None = Field(
        None, description="GCP project ID (auto-detected from credentials if None)"
    )
    credentials_path: str | None = Field(
        None, description="Path to service account JSON key (uses ADC if None)"
    )
    region: str = Field("us-central1", description="GCS bucket region")
    storage_class: str = Field(
        "STANDARD",
        description="Initial storage class (STANDARD, NEARLINE, COLDLINE, ARCHIVE)",
    )
    autoclass_enabled: bool = Field(
        True, description="Whether to enable GCS Autoclass for automatic transitions"
    )
    prefix: str = Field("snapshots/", description="Object name prefix for snapshots")
    filename_prefix: str = Field("looker", description="Snapshot filename prefix")
    compression_enabled: bool = Field(True, description="Whether to compress snapshots with gzip")
    compression_level: int = Field(6, description="Gzip compression level 1-9 (1=fastest, 9=best)")

    @field_validator("bucket_name")
    @classmethod
    def validate_bucket_name(cls, v: str) -> str:
        """Validate GCS bucket name format according to Google Cloud Storage naming rules.

        References:
            https://cloud.google.com/storage/docs/buckets#naming
        """
        import re

        if not v:
            raise ValueError("Bucket name cannot be empty")

        # Length constraints
        if len(v) < 3:
            raise ValueError("Bucket name must be at least 3 characters")
        if len(v) > 63:
            raise ValueError("Bucket name must not exceed 63 characters")

        # Character constraints - must contain only lowercase letters, numbers, hyphens, underscores, and periods
        if not re.match(r"^[a-z0-9._-]+$", v):
            raise ValueError(
                "Bucket name must contain only lowercase letters, numbers, hyphens, underscores, and periods"
            )

        # Must start and end with alphanumeric
        if not v[0].isalnum() or not v[-1].isalnum():
            raise ValueError("Bucket name must start and end with a letter or number")

        # Cannot contain consecutive periods
        if ".." in v:
            raise ValueError("Bucket name cannot contain consecutive periods")

        # Cannot be formatted as IP address
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", v):
            raise ValueError("Bucket name cannot be formatted as an IP address")

        # Cannot start with "goog" prefix
        if v.startswith("goog"):
            raise ValueError('Bucket name cannot start with "goog" prefix')

        # Cannot contain "google"
        if "google" in v.lower():
            raise ValueError('Bucket name cannot contain "google"')

        return v.lower()

    @field_validator("region")
    @classmethod
    def validate_region(cls, v: str) -> str:
        """Validate GCS region/location code.

        References:
            https://cloud.google.com/storage/docs/locations
        """
        if not v:
            raise ValueError("Region cannot be empty")

        region_lower = v.lower()

        if region_lower in VALID_GCS_LOCATIONS:
            return region_lower

        # Provide helpful error message with suggestions
        suggestions = [r for r in VALID_GCS_LOCATIONS if region_lower in r or r in region_lower]
        if suggestions:
            raise ValueError(
                f"Invalid GCS region '{v}'. Did you mean one of: {', '.join(sorted(suggestions)[:3])}?"
            )

        raise ValueError(
            f"Invalid GCS region '{v}'. Must be a valid GCS region or multi-region "
            f"(e.g., 'us-central1', 'europe-west1', 'us', 'eu', 'asia')"
        )

    @field_validator("storage_class")
    @classmethod
    def validate_storage_class(cls, v: str) -> str:
        """Validate storage class is one of the allowed values."""
        allowed = {"STANDARD", "NEARLINE", "COLDLINE", "ARCHIVE"}
        if v.upper() not in allowed:
            raise ValueError(f"Storage class must be one of: {', '.join(allowed)}")
        return v.upper()

    @field_validator("compression_level")
    @classmethod
    def validate_compression_level(cls, v: int) -> int:
        """Validate compression level is in range 1-9."""
        if not 1 <= v <= 9:
            raise ValueError("Compression level must be between 1 (fastest) and 9 (best)")
        return v

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, v: str) -> str:
        """Validate prefix format (no leading slash, should end with slash)."""
        if v.startswith("/"):
            raise ValueError("Prefix must not start with /")
        if not v.endswith("/"):
            v = v + "/"
        return v


class SnapshotConfig(BaseModel):
    """Top-level configuration for snapshot management."""

    provider: GCSStorageProvider = Field(..., description="GCS storage configuration")
    retention: RetentionPolicy = Field(
        default_factory=RetentionPolicy, description="Retention and cleanup policy"
    )
    cache_ttl_minutes: int = Field(
        5, description="Local cache TTL for snapshot listings in minutes"
    )
    audit_log_path: str = Field(
        "~/.lookervault/audit.log", description="Path to local audit log file"
    )
    audit_gcs_bucket: str | None = Field(
        None, description="GCS bucket for centralized audit logs (optional)"
    )

    @field_validator("cache_ttl_minutes")
    @classmethod
    def validate_cache_ttl(cls, v: int) -> int:
        """Validate cache TTL is non-negative."""
        if v < 0:
            raise ValueError("Cache TTL must be >= 0 (0 disables caching)")
        return v

    @field_validator("audit_log_path")
    @classmethod
    def validate_audit_log_path(cls, v: str) -> str:
        """Expand user home directory in audit log path."""
        return str(Path(v).expanduser())
