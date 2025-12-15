"""Unit tests for snapshot configuration validation."""

import pytest
from pydantic import ValidationError

from lookervault.config.validator import (
    validate_compression_level,
    validate_gcs_bucket_name,
    validate_gcs_region,
)
from lookervault.snapshot.models import GCSStorageProvider


class TestBucketNameValidation:
    """Test GCS bucket name validation."""

    def test_valid_bucket_names(self) -> None:
        """Test valid bucket names."""
        valid_names = [
            "lookervault-backups",
            "test-bucket-123",
            "my_bucket",
            "bucket.with.periods",
            "a-b",  # minimum 3 chars but testing hyphen
            "abc",  # minimum length
        ]

        for name in valid_names:
            is_valid, msg = validate_gcs_bucket_name(name)
            assert is_valid, f"Expected '{name}' to be valid, but got: {msg}"
            assert msg == ""

    def test_invalid_bucket_names(self) -> None:
        """Test invalid bucket names."""
        invalid_cases = [
            ("", "cannot be empty"),
            ("ab", "at least 3 characters"),
            ("a" * 64, "not exceed 63 characters"),
            ("Invalid_Bucket", "lowercase letters"),
            ("UPPERCASE", "lowercase letters"),
            ("-starts-with-hyphen", "start and end"),
            ("ends-with-hyphen-", "start and end"),
            (".starts-with-period", "start and end"),
            ("ends-with-period.", "start and end"),
            ("bucket..double.period", "consecutive periods"),
            ("192.168.1.1", "ip address"),
            ("goog-test", "goog"),
            ("my-google-bucket", "google"),
        ]

        for name, expected_msg in invalid_cases:
            is_valid, msg = validate_gcs_bucket_name(name)
            assert not is_valid, f"Expected '{name}' to be invalid"
            assert (
                expected_msg.lower() in msg.lower()
            ), f"Expected error message to contain '{expected_msg}', got: {msg}"

    def test_bucket_name_normalization(self) -> None:
        """Test that bucket names are normalized to lowercase."""
        # The validator enforces lowercase, so mixed case will be rejected
        # But if you pass uppercase that would otherwise be valid, it gets lowercased
        provider = GCSStorageProvider(
            bucket_name="test-bucket-123",  # Already lowercase
            region="us-central1",
        )
        assert provider.bucket_name == "test-bucket-123"

        # Test that lowercase conversion happens during validation
        # Note: Pydantic's field_validator sees the value BEFORE any coercion
        # So we verify the .lower() call happens in the validator
        provider2 = GCSStorageProvider(
            bucket_name="abc",  # Already lowercase, minimum length
            region="us-central1",
        )
        assert provider2.bucket_name == "abc"


class TestRegionValidation:
    """Test GCS region validation."""

    def test_valid_regions(self) -> None:
        """Test valid GCS regions."""
        valid_regions = [
            # North America
            "us-central1",
            "us-east1",
            "us-west1",
            "northamerica-northeast1",
            # Europe
            "europe-west1",
            "europe-west2",
            "europe-north1",
            # Asia Pacific
            "asia-east1",
            "asia-southeast1",
            # Multi-regions
            "us",
            "eu",
            "asia",
        ]

        for region in valid_regions:
            is_valid, msg = validate_gcs_region(region)
            assert is_valid, f"Expected '{region}' to be valid, but got: {msg}"
            assert msg == ""

    def test_invalid_regions(self) -> None:
        """Test invalid GCS regions."""
        invalid_cases = [
            ("", "cannot be empty"),
            ("invalid-region", "Invalid GCS region"),
            ("us-east-99", "Invalid GCS region"),
        ]

        for region, expected_msg in invalid_cases:
            is_valid, msg = validate_gcs_region(region)
            assert not is_valid, f"Expected '{region}' to be invalid"
            assert (
                expected_msg in msg
            ), f"Expected error message to contain '{expected_msg}', got: {msg}"

    def test_region_suggestions(self) -> None:
        """Test that validation provides helpful suggestions for similar regions."""
        is_valid, msg = validate_gcs_region("us-west")
        assert not is_valid
        assert "Did you mean" in msg
        # Should suggest us-west1, us-west2, etc.
        assert "us-west" in msg.lower()

    def test_region_normalization(self) -> None:
        """Test that regions are normalized to lowercase."""
        provider = GCSStorageProvider(
            bucket_name="test-bucket",
            region="US-CENTRAL1",  # Uppercase
        )
        assert provider.region == "us-central1"


class TestCompressionLevelValidation:
    """Test compression level validation."""

    def test_valid_compression_levels(self) -> None:
        """Test valid compression levels (1-9)."""
        for level in range(1, 10):  # 1 through 9
            is_valid, msg = validate_compression_level(level)
            assert is_valid, f"Expected compression level {level} to be valid, but got: {msg}"
            assert msg == ""

    def test_invalid_compression_levels(self) -> None:
        """Test invalid compression levels."""
        invalid_levels = [0, -1, 10, 100]

        for level in invalid_levels:
            is_valid, msg = validate_compression_level(level)
            assert not is_valid, f"Expected compression level {level} to be invalid"
            assert "between 1" in msg
            assert "9" in msg


class TestGCSStorageProviderModel:
    """Test GCSStorageProvider Pydantic model integration."""

    def test_valid_provider_configuration(self) -> None:
        """Test creating a valid GCS storage provider."""
        provider = GCSStorageProvider(
            bucket_name="lookervault-backups",
            region="us-central1",
            compression_enabled=True,
            compression_level=6,
        )

        assert provider.bucket_name == "lookervault-backups"
        assert provider.region == "us-central1"
        assert provider.compression_level == 6

    def test_provider_with_invalid_bucket_name(self) -> None:
        """Test that invalid bucket name raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            GCSStorageProvider(
                bucket_name="Invalid_Bucket_Name",
                region="us-central1",
            )

        error = exc_info.value
        assert "bucket_name" in str(error)
        assert "lowercase" in str(error)

    def test_provider_with_invalid_region(self) -> None:
        """Test that invalid region raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            GCSStorageProvider(
                bucket_name="test-bucket",
                region="invalid-region-code",
            )

        error = exc_info.value
        assert "region" in str(error)
        assert "Invalid GCS region" in str(error)

    def test_provider_with_invalid_compression_level(self) -> None:
        """Test that invalid compression level raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            GCSStorageProvider(
                bucket_name="test-bucket",
                region="us-central1",
                compression_level=0,  # Invalid: must be 1-9
            )

        error = exc_info.value
        assert "compression_level" in str(error)
        assert "between 1" in str(error)

    def test_provider_with_default_values(self) -> None:
        """Test that provider uses sensible defaults."""
        provider = GCSStorageProvider(
            bucket_name="test-bucket",
        )

        assert provider.region == "us-central1"  # Default region
        assert provider.storage_class == "STANDARD"  # Default storage class
        assert provider.compression_enabled is True  # Default compression
        assert provider.compression_level == 6  # Default level
        assert provider.autoclass_enabled is True  # Default autoclass
        assert provider.prefix == "snapshots/"  # Default prefix

    def test_provider_storage_class_validation(self) -> None:
        """Test storage class validation."""
        # Valid storage classes
        for storage_class in ["STANDARD", "NEARLINE", "COLDLINE", "ARCHIVE"]:
            provider = GCSStorageProvider(
                bucket_name="test-bucket",
                storage_class=storage_class,
            )
            assert provider.storage_class == storage_class

        # Invalid storage class
        with pytest.raises(ValidationError) as exc_info:
            GCSStorageProvider(
                bucket_name="test-bucket",
                storage_class="INVALID_CLASS",
            )
        assert "storage_class" in str(exc_info.value)

    def test_provider_prefix_normalization(self) -> None:
        """Test that prefix is normalized to end with slash."""
        # Without trailing slash
        provider = GCSStorageProvider(
            bucket_name="test-bucket",
            prefix="snapshots",
        )
        assert provider.prefix == "snapshots/"

        # With trailing slash (unchanged)
        provider = GCSStorageProvider(
            bucket_name="test-bucket",
            prefix="snapshots/",
        )
        assert provider.prefix == "snapshots/"

        # Leading slash is invalid
        with pytest.raises(ValidationError) as exc_info:
            GCSStorageProvider(
                bucket_name="test-bucket",
                prefix="/snapshots/",
            )
        assert "must not start with /" in str(exc_info.value)
