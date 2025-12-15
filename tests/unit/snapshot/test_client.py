"""Unit tests for GCS client module."""

from unittest.mock import MagicMock, patch

import pytest
from google.auth.exceptions import DefaultCredentialsError, RefreshError

from lookervault.snapshot.client import create_storage_client, validate_bucket_access


class TestCreateStorageClient:
    """Test GCS storage client creation."""

    @patch("lookervault.snapshot.client.storage.Client")
    def test_create_client_without_project_id(self, mock_client_class):
        """Test creating client without explicit project ID."""
        mock_client = MagicMock()
        mock_client.project = "auto-detected-project"
        mock_client_class.return_value = mock_client

        client = create_storage_client()

        # Client should be created without project parameter
        mock_client_class.assert_called_once_with()
        assert client == mock_client

    @patch("lookervault.snapshot.client.storage.Client")
    def test_create_client_with_project_id(self, mock_client_class):
        """Test creating client with explicit project ID."""
        mock_client = MagicMock()
        mock_client.project = "my-project"
        mock_client_class.return_value = mock_client

        client = create_storage_client(project_id="my-project")

        # Client should be created with project parameter
        mock_client_class.assert_called_once_with(project="my-project")
        assert client == mock_client

    @patch("lookervault.snapshot.client.storage.Client")
    def test_create_client_no_credentials(self, mock_client_class):
        """Test client creation fails when no credentials found."""
        mock_client_class.side_effect = DefaultCredentialsError("No credentials found")

        with pytest.raises(RuntimeError) as exc_info:
            create_storage_client()

        error_msg = str(exc_info.value)
        assert "No valid Google Cloud credentials found" in error_msg
        assert "GOOGLE_APPLICATION_CREDENTIALS" in error_msg

    @patch("lookervault.snapshot.client.storage.Client")
    def test_create_client_expired_credentials(self, mock_client_class):
        """Test client creation fails when credentials expired."""
        mock_client_class.side_effect = RefreshError("Token expired")

        with pytest.raises(RuntimeError) as exc_info:
            create_storage_client()

        error_msg = str(exc_info.value)
        assert "Failed to refresh Google Cloud credentials" in error_msg
        assert "Re-authenticate" in error_msg

    @patch("lookervault.snapshot.client.storage.Client")
    def test_create_client_permission_error(self, mock_client_class):
        """Test client creation with permission errors."""
        mock_client_class.side_effect = Exception("permission denied")

        with pytest.raises(RuntimeError) as exc_info:
            create_storage_client()

        error_msg = str(exc_info.value)
        assert "permission" in error_msg.lower()

    @patch("lookervault.snapshot.client.storage.Client")
    def test_create_client_project_error(self, mock_client_class):
        """Test client creation with project errors."""
        mock_client_class.side_effect = Exception("invalid project id")

        with pytest.raises(RuntimeError) as exc_info:
            create_storage_client()

        error_msg = str(exc_info.value)
        assert "project" in error_msg.lower()


class TestValidateBucketAccess:
    """Test bucket access validation."""

    def test_validate_bucket_access_success(self):
        """Test successful bucket access validation."""
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.exists.return_value = True

        result = validate_bucket_access(mock_client, "test-bucket")

        assert result is True
        mock_bucket.exists.assert_called_once()
        mock_bucket.reload.assert_called_once()

    def test_validate_bucket_access_bucket_not_found(self):
        """Test validation fails when bucket doesn't exist."""
        from google.cloud import exceptions as gcs_exceptions

        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.exists.return_value = False

        with pytest.raises(RuntimeError) as exc_info:
            validate_bucket_access(mock_client, "nonexistent-bucket")

        error_msg = str(exc_info.value)
        assert "does not exist" in error_msg
        assert "Create the bucket" in error_msg

    def test_validate_bucket_access_permission_denied(self):
        """Test validation fails with insufficient permissions."""
        from google.cloud import exceptions as gcs_exceptions

        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.exists.side_effect = gcs_exceptions.Forbidden("Permission denied")

        with pytest.raises(RuntimeError) as exc_info:
            validate_bucket_access(mock_client, "test-bucket")

        error_msg = str(exc_info.value)
        assert "Insufficient permissions" in error_msg
        assert "storage.buckets.get" in error_msg

    def test_validate_bucket_access_network_error(self):
        """Test validation fails with network errors."""
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.exists.side_effect = ConnectionError("Network timeout")

        with pytest.raises(RuntimeError) as exc_info:
            validate_bucket_access(mock_client, "test-bucket")

        error_msg = str(exc_info.value)
        assert "network error" in error_msg.lower()

    def test_validate_bucket_access_reload_fails_gracefully(self):
        """Test validation fails if reload fails (doesn't fail gracefully in current implementation)."""
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.exists.return_value = True
        mock_bucket.reload.side_effect = Exception("Reload failed")

        # Current implementation doesn't handle reload() exceptions, so it will raise RuntimeError
        with pytest.raises(RuntimeError):
            validate_bucket_access(mock_client, "test-bucket")
