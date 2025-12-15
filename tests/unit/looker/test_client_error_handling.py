"""Comprehensive tests for Looker API client error handling and retry logic.

This test module covers:
- Looker API client error handling
- Retry logic for transient errors
- Rate limiting (HTTP 429) handling
- Network error scenarios
- Authentication errors
- API validation errors
"""

from unittest.mock import Mock, patch

import pytest
from looker_sdk import error as looker_error
from tenacity import RetryError

from lookervault.exceptions import ExtractionError
from lookervault.extraction.rate_limiter import AdaptiveRateLimiter
from lookervault.looker.client import LookerClient
from lookervault.looker.extractor import LookerContentExtractor
from lookervault.storage.models import ContentType


class TestLookerClientInitialization:
    """Tests for LookerClient initialization and configuration."""

    def test_client_initialization_with_defaults(self):
        """Test client initializes with default values."""
        client = LookerClient(
            api_url="https://looker.example.com:19999",
            client_id="test_client_id",
            client_secret="test_secret",
        )

        assert client.api_url == "https://looker.example.com:19999"
        assert client.client_id == "test_client_id"
        assert client.client_secret == "test_secret"
        assert client.timeout == 30
        assert client.verify_ssl is True
        assert client._sdk is None  # Lazy initialization

    def test_client_initialization_with_custom_timeout(self):
        """Test client accepts custom timeout value."""
        client = LookerClient(
            api_url="https://looker.example.com:19999",
            client_id="test_id",
            client_secret="test_secret",
            timeout=60,
        )

        assert client.timeout == 60

    def test_client_initialization_with_ssl_disabled(self):
        """Test client accepts SSL verification disabled."""
        client = LookerClient(
            api_url="https://looker.example.com:19999",
            client_id="test_id",
            client_secret="test_secret",
            verify_ssl=False,
        )

        assert client.verify_ssl is False

    @patch("lookervault.looker.client.looker_sdk.init40")
    def test_lazy_sdk_initialization(self, mock_init40):
        """Test that SDK is only initialized on first access."""
        mock_sdk = Mock()
        mock_init40.return_value = mock_sdk

        client = LookerClient(
            api_url="https://looker.example.com:19999",
            client_id="test_id",
            client_secret="test_secret",
        )

        # SDK should not be initialized yet
        assert client._sdk is None
        assert mock_init40.call_count == 0

        # Access SDK property
        sdk = client.sdk

        # Now SDK should be initialized
        assert sdk == mock_sdk
        assert mock_init40.call_count == 1
        assert client._sdk == mock_sdk

        # Second access should reuse same SDK
        sdk2 = client.sdk
        assert sdk2 == mock_sdk
        assert mock_init40.call_count == 1  # Still only called once


class TestLookerClientConnectionTesting:
    """Tests for LookerClient.test_connection() method."""

    @patch("lookervault.looker.client.looker_sdk.init40")
    def test_successful_connection(self, mock_init40):
        """Test successful connection returns correct status."""
        mock_sdk = Mock()
        mock_init40.return_value = mock_sdk

        # Mock successful API responses
        mock_user = Mock()
        mock_user.id = "123"
        mock_user.email = "test@example.com"
        mock_sdk.me.return_value = mock_user

        mock_versions = Mock()
        mock_versions.looker_release_version = "24.0.0"
        mock_version = Mock()
        mock_version.version = "4.0"
        mock_versions.current_version = mock_version
        mock_sdk.versions.return_value = mock_versions

        client = LookerClient(
            api_url="https://looker.example.com:19999",
            client_id="test_id",
            client_secret="test_secret",
        )

        status = client.test_connection()

        assert status.connected is True
        assert status.authenticated is True
        assert status.instance_url == "https://looker.example.com:19999"
        assert status.looker_version == "24.0.0"
        assert status.api_version == "4.0"
        assert status.user_id == 123
        assert status.user_email == "test@example.com"
        assert status.error_message is None

    @patch("lookervault.looker.client.looker_sdk.init40")
    def test_authentication_failure_401(self, mock_init40):
        """Test authentication failure (401) returns appropriate error."""
        mock_sdk = Mock()
        mock_init40.return_value = mock_sdk

        # Mock 401 authentication error
        mock_sdk.me.side_effect = looker_error.SDKError("401 Unauthorized")

        client = LookerClient(
            api_url="https://looker.example.com:19999",
            client_id="invalid_id",
            client_secret="invalid_secret",
        )

        status = client.test_connection()

        assert status.connected is False
        assert status.authenticated is False
        assert status.error_message is not None
        assert "Authentication failed - invalid credentials" in status.error_message

    @patch("lookervault.looker.client.looker_sdk.init40")
    def test_connection_timeout_error(self, mock_init40):
        """Test connection timeout returns appropriate error."""
        mock_sdk = Mock()
        mock_init40.return_value = mock_sdk

        # Mock timeout error
        mock_sdk.me.side_effect = looker_error.SDKError("timeout occurred")

        client = LookerClient(
            api_url="https://looker.example.com:19999",
            client_id="test_id",
            client_secret="test_secret",
        )

        status = client.test_connection()

        assert status.connected is False
        assert status.authenticated is False
        assert status.error_message is not None
        assert "Connection timeout - check network connectivity" in status.error_message

    @patch("lookervault.looker.client.looker_sdk.init40")
    def test_connection_refused_error(self, mock_init40):
        """Test connection refused returns appropriate error."""
        mock_sdk = Mock()
        mock_init40.return_value = mock_sdk

        # Mock connection error
        mock_sdk.me.side_effect = looker_error.SDKError("connection refused")

        client = LookerClient(
            api_url="https://invalid.example.com:19999",
            client_id="test_id",
            client_secret="test_secret",
        )

        status = client.test_connection()

        assert status.connected is False
        assert status.authenticated is False
        assert status.error_message is not None
        assert "Cannot reach Looker instance - check API URL" in status.error_message

    @patch("lookervault.looker.client.looker_sdk.init40")
    def test_unexpected_error(self, mock_init40):
        """Test unexpected error is handled gracefully."""
        mock_sdk = Mock()
        mock_init40.return_value = mock_sdk

        # Mock unexpected error
        mock_sdk.me.side_effect = RuntimeError("Unexpected error")

        client = LookerClient(
            api_url="https://looker.example.com:19999",
            client_id="test_id",
            client_secret="test_secret",
        )

        status = client.test_connection()

        assert status.connected is False
        assert status.authenticated is False
        assert status.error_message is not None
        assert "Unexpected error" in status.error_message


class TestLookerContentExtractorErrorHandling:
    """Tests for LookerContentExtractor error handling."""

    def test_extractor_initialization(self):
        """Test extractor initializes correctly."""
        mock_client = Mock()
        extractor = LookerContentExtractor(client=mock_client)

        assert extractor.client == mock_client
        assert extractor.rate_limiter is None

    def test_extractor_with_rate_limiter(self):
        """Test extractor accepts rate limiter."""
        mock_client = Mock()
        rate_limiter = AdaptiveRateLimiter(requests_per_minute=100, requests_per_second=10)
        extractor = LookerContentExtractor(client=mock_client, rate_limiter=rate_limiter)

        assert extractor.rate_limiter == rate_limiter

    def test_call_api_successful_request(self):
        """Test _call_api handles successful requests."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Mock successful API response
        mock_response = Mock()
        mock_response.id = "123"
        mock_sdk.dashboard.return_value = mock_response

        extractor = LookerContentExtractor(client=mock_client)
        result = extractor._call_api("dashboard", dashboard_id="123")

        assert result == mock_response
        mock_sdk.dashboard.assert_called_once_with(dashboard_id="123")

    def test_call_api_with_rate_limiter_success(self):
        """Test _call_api uses rate limiter and reports success."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_response = Mock()
        mock_sdk.dashboard.return_value = mock_response

        rate_limiter = Mock(spec=AdaptiveRateLimiter)
        extractor = LookerContentExtractor(client=mock_client, rate_limiter=rate_limiter)

        result = extractor._call_api("dashboard", dashboard_id="123")

        # Should acquire rate limit token
        rate_limiter.acquire.assert_called_once()
        # Should report success
        rate_limiter.on_success.assert_called_once()
        assert result == mock_response

    def test_call_api_rate_limit_error_429(self):
        """Test _call_api detects and raises RateLimitError on 429 (wrapped in RetryError after retries)."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Mock 429 rate limit error (will be retried 5 times)
        mock_sdk.dashboard.side_effect = looker_error.SDKError("429 Too Many Requests")

        extractor = LookerContentExtractor(client=mock_client)

        # After retries are exhausted, tenacity wraps in RetryError
        with pytest.raises(RetryError):
            extractor._call_api("dashboard", dashboard_id="123")

        # Verify it was retried 5 times (max_attempts)
        assert mock_sdk.dashboard.call_count == 5

    def test_call_api_rate_limit_with_adaptive_limiter(self):
        """Test _call_api reports 429 to adaptive rate limiter."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Mock 429 error (will be retried 5 times)
        mock_sdk.dashboard.side_effect = looker_error.SDKError("429 Too Many Requests")

        rate_limiter = Mock(spec=AdaptiveRateLimiter)
        extractor = LookerContentExtractor(client=mock_client, rate_limiter=rate_limiter)

        with pytest.raises(RetryError):
            extractor._call_api("dashboard", dashboard_id="123")

        # Should acquire token (5 times - once per retry)
        assert rate_limiter.acquire.call_count == 5
        # Should report 429 detection (5 times - once per retry)
        assert rate_limiter.on_429_detected.call_count == 5
        # Should NOT report success
        rate_limiter.on_success.assert_not_called()

    def test_call_api_generic_sdk_error(self):
        """Test _call_api raises ExtractionError for non-rate-limit SDK errors."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Mock generic SDK error
        mock_sdk.dashboard.side_effect = looker_error.SDKError("Invalid dashboard ID")

        extractor = LookerContentExtractor(client=mock_client)

        with pytest.raises(ExtractionError) as exc_info:
            extractor._call_api("dashboard", dashboard_id="invalid")

        assert "API error calling dashboard" in str(exc_info.value)
        assert "Invalid dashboard ID" in str(exc_info.value)

    def test_call_api_method_not_found(self):
        """Test _call_api handles missing SDK method gracefully."""
        mock_client = Mock()
        mock_sdk = Mock(spec=[])  # SDK with no methods
        mock_client.sdk = mock_sdk

        extractor = LookerContentExtractor(client=mock_client)

        # AttributeError when trying to call non-existent method
        with pytest.raises(AttributeError):
            extractor._call_api("nonexistent_method")


class TestExtractorRetryLogic:
    """Tests for retry logic with tenacity decorators."""

    def test_retry_on_rate_limit_success_after_retry(self):
        """Test that @retry_on_rate_limit retries on RateLimitError and succeeds."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # First call raises 429, second call succeeds
        mock_response = Mock()
        mock_sdk.dashboard.side_effect = [
            looker_error.SDKError("429 Too Many Requests"),
            mock_response,
        ]

        extractor = LookerContentExtractor(client=mock_client)

        # Should retry and succeed
        result = extractor._call_api("dashboard", dashboard_id="123")

        assert result == mock_response
        assert mock_sdk.dashboard.call_count == 2

    def test_retry_on_rate_limit_exhausts_retries(self):
        """Test that @retry_on_rate_limit exhausts retries and raises RetryError."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Always raise 429
        mock_sdk.dashboard.side_effect = looker_error.SDKError("429 Too Many Requests")

        extractor = LookerContentExtractor(client=mock_client)

        # Should exhaust retries and raise RetryError (wrapping RateLimitError)
        with pytest.raises(RetryError):
            extractor._call_api("dashboard", dashboard_id="123")

        # Should have tried max_attempts times (5 by default)
        assert mock_sdk.dashboard.call_count == 5

    def test_retry_does_not_retry_non_rate_limit_errors(self):
        """Test that retry decorator does not retry non-RateLimitError exceptions."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Raise non-retryable error
        mock_sdk.dashboard.side_effect = looker_error.SDKError("Invalid request")

        extractor = LookerContentExtractor(client=mock_client)

        # Should raise ExtractionError without retry
        with pytest.raises(ExtractionError):
            extractor._call_api("dashboard", dashboard_id="123")

        # Should only try once (no retry)
        assert mock_sdk.dashboard.call_count == 1


class TestExtractOneErrorHandling:
    """Tests for extract_one error handling."""

    def test_extract_one_dashboard_success(self):
        """Test successful single dashboard extraction."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_dashboard = Mock()
        mock_dashboard.id = "123"
        mock_dashboard.title = "Test Dashboard"
        mock_sdk.dashboard.return_value = mock_dashboard

        extractor = LookerContentExtractor(client=mock_client)
        result = extractor.extract_one(ContentType.DASHBOARD, "123")

        assert result["id"] == "123"
        assert result["title"] == "Test Dashboard"

    def test_extract_one_look_success(self):
        """Test successful single look extraction."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_look = Mock()
        mock_look.id = "456"
        mock_look.title = "Test Look"
        mock_sdk.look.return_value = mock_look

        extractor = LookerContentExtractor(client=mock_client)
        result = extractor.extract_one(ContentType.LOOK, "456")

        assert result["id"] == "456"
        assert result["title"] == "Test Look"

    def test_extract_one_user_success(self):
        """Test successful single user extraction."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_user = Mock()
        mock_user.id = "789"
        mock_user.email = "user@example.com"
        mock_sdk.user.return_value = mock_user

        extractor = LookerContentExtractor(client=mock_client)
        result = extractor.extract_one(ContentType.USER, "789")

        assert result["id"] == "789"
        assert result["email"] == "user@example.com"

    def test_extract_one_not_found_error(self):
        """Test extract_one raises ExtractionError when content not found."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Mock 404 not found error (wrapped in ExtractionError by extract_one)
        mock_sdk.dashboard.side_effect = looker_error.SDKError("404 Not Found")

        extractor = LookerContentExtractor(client=mock_client)

        # extract_one wraps all exceptions in ExtractionError
        with pytest.raises(ExtractionError) as exc_info:
            extractor.extract_one(ContentType.DASHBOARD, "nonexistent")

        # Error message includes content type enum value and ID
        assert "Failed to extract" in str(exc_info.value)
        assert "nonexistent" in str(exc_info.value)

    def test_extract_one_rate_limit_error(self):
        """Test extract_one raises ExtractionError (wrapping RetryError) on 429."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Mock 429 rate limit (will be retried 5 times, then wrapped in ExtractionError)
        mock_sdk.dashboard.side_effect = looker_error.SDKError("429 Too Many Requests")

        extractor = LookerContentExtractor(client=mock_client)

        # extract_one wraps all exceptions (including RetryError) in ExtractionError
        with pytest.raises(ExtractionError):
            extractor.extract_one(ContentType.DASHBOARD, "123")

    def test_extract_one_unsupported_content_type(self):
        """Test extract_one raises ExtractionError for unsupported types."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk
        extractor = LookerContentExtractor(client=mock_client)

        # BOARD is not supported for single extraction (no SDK method)
        with pytest.raises(ExtractionError) as exc_info:
            extractor.extract_one(ContentType.BOARD, "123")

        # Error message contains "extract_one not supported"
        assert "extract_one not supported" in str(exc_info.value)


class TestExtractRangeErrorHandling:
    """Tests for extract_range error handling."""

    def test_extract_range_dashboards_success(self):
        """Test successful range extraction for dashboards."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_dashboards = [Mock(id=str(i), title=f"Dashboard {i}") for i in range(10)]
        mock_sdk.search_dashboards.return_value = mock_dashboards

        extractor = LookerContentExtractor(client=mock_client)
        results = extractor.extract_range(
            ContentType.DASHBOARD, offset=0, limit=10, fields="id,title"
        )

        assert len(results) == 10
        mock_sdk.search_dashboards.assert_called_once_with(fields="id,title", limit=10, offset=0)

    def test_extract_range_looks_success(self):
        """Test successful range extraction for looks."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_looks = [Mock(id=str(i), title=f"Look {i}") for i in range(5)]
        mock_sdk.search_looks.return_value = mock_looks

        extractor = LookerContentExtractor(client=mock_client)
        results = extractor.extract_range(ContentType.LOOK, offset=0, limit=5)

        assert len(results) == 5

    def test_extract_range_users_success(self):
        """Test successful range extraction for users."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_users = [Mock(id=str(i), email=f"user{i}@example.com") for i in range(3)]
        mock_sdk.all_users.return_value = mock_users

        extractor = LookerContentExtractor(client=mock_client)
        results = extractor.extract_range(ContentType.USER, offset=0, limit=3)

        assert len(results) == 3
        mock_sdk.all_users.assert_called_once_with(fields=None, limit=3, offset=0)

    def test_extract_range_with_folder_id_filter(self):
        """Test extract_range applies folder_id filter for dashboards."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_dashboards = [Mock(id="1", folder_id="folder123")]
        mock_sdk.search_dashboards.return_value = mock_dashboards

        extractor = LookerContentExtractor(client=mock_client)
        results = extractor.extract_range(
            ContentType.DASHBOARD, offset=0, limit=10, folder_id="folder123"
        )

        assert len(results) == 1
        # Should pass folder_id to SDK
        mock_sdk.search_dashboards.assert_called_once_with(
            fields=None, limit=10, offset=0, folder_id="folder123"
        )

    def test_extract_range_unsupported_content_type(self):
        """Test extract_range raises ExtractionError (wrapping ValueError) for unsupported content types."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk
        extractor = LookerContentExtractor(client=mock_client)

        # BOARD does not support pagination - ValueError is wrapped in ExtractionError
        with pytest.raises(ExtractionError) as exc_info:
            extractor.extract_range(ContentType.BOARD, offset=0, limit=10)

        # The error message should mention range extraction not being supported
        assert "range extraction" in str(exc_info.value) or "Failed to extract range" in str(
            exc_info.value
        )

    def test_extract_range_rate_limit_error(self):
        """Test extract_range raises ExtractionError (wrapping RetryError) on 429."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Mock 429 error (will be retried 5 times, then wrapped)
        mock_sdk.search_dashboards.side_effect = looker_error.SDKError("429 Too Many Requests")

        extractor = LookerContentExtractor(client=mock_client)

        # extract_range wraps RetryError in ExtractionError
        with pytest.raises(ExtractionError):
            extractor.extract_range(ContentType.DASHBOARD, offset=0, limit=10)

    def test_extract_range_api_error(self):
        """Test extract_range raises ExtractionError on API errors."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_sdk.search_dashboards.side_effect = looker_error.SDKError("Invalid request")

        extractor = LookerContentExtractor(client=mock_client)

        with pytest.raises(ExtractionError) as exc_info:
            extractor.extract_range(ContentType.DASHBOARD, offset=0, limit=10)

        # Error message should contain "API error"
        assert "API error" in str(exc_info.value)

    def test_extract_range_empty_results(self):
        """Test extract_range handles empty results gracefully."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Return empty list
        mock_sdk.search_dashboards.return_value = []

        extractor = LookerContentExtractor(client=mock_client)
        results = extractor.extract_range(ContentType.DASHBOARD, offset=100, limit=10)

        assert len(results) == 0


class TestExtractAllErrorHandling:
    """Tests for extract_all error handling."""

    def test_extract_all_dashboards_success(self):
        """Test successful extraction of all dashboards."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Mock paginated responses
        mock_sdk.search_dashboards.side_effect = [
            [Mock(id="1"), Mock(id="2")],
            [],
        ]

        extractor = LookerContentExtractor(client=mock_client)
        results = list(extractor.extract_all(ContentType.DASHBOARD, batch_size=2))

        assert len(results) == 2

    def test_extract_all_rate_limit_error(self):
        """Test extract_all raises ExtractionError (wrapping RetryError) on 429."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Mock 429 error (will be retried 5 times, then wrapped)
        mock_sdk.search_dashboards.side_effect = looker_error.SDKError("429 Too Many Requests")

        extractor = LookerContentExtractor(client=mock_client)

        # extract_all wraps RetryError in ExtractionError
        with pytest.raises(ExtractionError):
            list(extractor.extract_all(ContentType.DASHBOARD))

    def test_extract_all_unsupported_content_type(self):
        """Test extract_all raises ExtractionError for unsupported types."""
        mock_client = Mock()
        extractor = LookerContentExtractor(client=mock_client)

        # Note: All content types in ContentType enum are now supported
        # This test is kept for future extensibility
        # If we need to test unsupported types, we'd need to add a new enum value
        pass

    def test_extract_all_generic_exception(self):
        """Test extract_all wraps generic exceptions as ExtractionError."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Raise generic exception
        mock_sdk.search_dashboards.side_effect = RuntimeError("Unexpected error")

        extractor = LookerContentExtractor(client=mock_client)

        with pytest.raises(ExtractionError) as exc_info:
            list(extractor.extract_all(ContentType.DASHBOARD))

        # Error message should contain "Failed to extract content type"
        assert "Failed to extract content type" in str(exc_info.value)


class TestTestConnectionMethod:
    """Tests for extractor.test_connection() method."""

    @patch("lookervault.looker.client.looker_sdk.init40")
    def test_test_connection_success(self, mock_init40):
        """Test successful connection test."""
        mock_sdk = Mock()
        mock_init40.return_value = mock_sdk

        # Mock successful connection
        mock_user = Mock()
        mock_user.id = "123"
        mock_user.email = "test@example.com"
        mock_sdk.me.return_value = mock_user

        mock_versions = Mock()
        mock_versions.looker_release_version = "24.0.0"
        mock_version = Mock()
        mock_version.version = "4.0"
        mock_versions.current_version = mock_version
        mock_sdk.versions.return_value = mock_versions

        client = LookerClient(
            api_url="https://looker.example.com:19999",
            client_id="test_id",
            client_secret="test_secret",
        )
        extractor = LookerContentExtractor(client=client)

        result = extractor.test_connection()

        assert result is True

    @patch("lookervault.looker.client.looker_sdk.init40")
    def test_test_connection_failure(self, mock_init40):
        """Test failed connection test."""
        mock_sdk = Mock()
        mock_init40.return_value = mock_sdk

        # Mock connection failure
        mock_sdk.me.side_effect = looker_error.SDKError("401 Unauthorized")

        client = LookerClient(
            api_url="https://looker.example.com:19999",
            client_id="invalid_id",
            client_secret="invalid_secret",
        )
        extractor = LookerContentExtractor(client=client)

        result = extractor.test_connection()

        assert result is False

    @patch("lookervault.looker.client.looker_sdk.init40")
    def test_test_connection_exception(self, mock_init40):
        """Test connection test handles exceptions gracefully."""
        mock_sdk = Mock()
        mock_init40.return_value = mock_sdk

        # Mock unexpected exception
        mock_sdk.me.side_effect = RuntimeError("Unexpected error")

        client = LookerClient(
            api_url="https://looker.example.com:19999",
            client_id="test_id",
            client_secret="test_secret",
        )
        extractor = LookerContentExtractor(client=client)

        result = extractor.test_connection()

        assert result is False


class TestNetworkErrorScenarios:
    """Tests for various network error scenarios."""

    @patch("lookervault.looker.client.looker_sdk.init40")
    def test_network_timeout_during_extraction(self, mock_init40):
        """Test network timeout during extraction."""
        mock_sdk = Mock()
        mock_init40.return_value = mock_sdk

        # Mock network timeout
        mock_sdk.search_dashboards.side_effect = looker_error.SDKError("Read timeout")

        client = LookerClient(
            api_url="https://looker.example.com:19999",
            client_id="test_id",
            client_secret="test_secret",
        )
        extractor = LookerContentExtractor(client=client)

        with pytest.raises(ExtractionError) as exc_info:
            list(extractor.extract_all(ContentType.DASHBOARD))

        assert "API error" in str(exc_info.value)

    @patch("lookervault.looker.client.looker_sdk.init40")
    def test_connection_reset_during_extraction(self, mock_init40):
        """Test connection reset during extraction."""
        mock_sdk = Mock()
        mock_init40.return_value = mock_sdk

        # Mock connection reset
        mock_sdk.search_dashboards.side_effect = looker_error.SDKError("Connection reset by peer")

        client = LookerClient(
            api_url="https://looker.example.com:19999",
            client_id="test_id",
            client_secret="test_secret",
        )
        extractor = LookerContentExtractor(client=client)

        with pytest.raises(ExtractionError):
            list(extractor.extract_all(ContentType.DASHBOARD))

    @patch("lookervault.looker.client.looker_sdk.init40")
    def test_dns_resolution_failure(self, mock_init40):
        """Test DNS resolution failure."""
        mock_sdk = Mock()
        mock_init40.return_value = mock_sdk

        # Mock DNS error
        mock_sdk.search_dashboards.side_effect = looker_error.SDKError("Name or service not known")

        client = LookerClient(
            api_url="https://nonexistent.example.com:19999",
            client_id="test_id",
            client_secret="test_secret",
        )
        extractor = LookerContentExtractor(client=client)

        with pytest.raises(ExtractionError):
            list(extractor.extract_all(ContentType.DASHBOARD))


class TestAPIValidationErrors:
    """Tests for API validation error handling."""

    def test_invalid_field_specification(self):
        """Test handling of invalid field specification."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Mock validation error for invalid fields
        mock_sdk.search_dashboards.side_effect = looker_error.SDKError(
            "Invalid field: nonexistent_field"
        )

        extractor = LookerContentExtractor(client=mock_client)

        with pytest.raises(ExtractionError) as exc_info:
            list(extractor.extract_all(ContentType.DASHBOARD, fields="nonexistent_field"))

        assert "API error" in str(exc_info.value)

    def test_invalid_limit_value(self):
        """Test handling of invalid limit value in extract_range."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Mock validation error for invalid limit
        mock_sdk.search_dashboards.side_effect = looker_error.SDKError("Invalid limit value")

        extractor = LookerContentExtractor(client=mock_client)

        with pytest.raises(ExtractionError):
            extractor.extract_range(ContentType.DASHBOARD, offset=0, limit=-1)

    def test_invalid_offset_value(self):
        """Test handling of invalid offset value in extract_range."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Mock validation error for invalid offset
        mock_sdk.search_dashboards.side_effect = looker_error.SDKError("Invalid offset value")

        extractor = LookerContentExtractor(client=mock_client)

        with pytest.raises(ExtractionError):
            extractor.extract_range(ContentType.DASHBOARD, offset=-100, limit=10)


class TestSDKObjectConversion:
    """Tests for SDK object to dictionary conversion."""

    def test_sdk_object_to_dict_with_all_fields(self):
        """Test conversion of SDK object with all fields populated."""
        mock_obj = Mock()
        mock_obj.id = "123"
        mock_obj.title = "Test"
        mock_obj.description = "Description"
        mock_obj.created_at = "2024-01-01T00:00:00Z"

        result = LookerContentExtractor._sdk_object_to_dict(mock_obj)

        assert result["id"] == "123"
        assert result["title"] == "Test"
        assert result["description"] == "Description"
        assert result["created_at"] == "2024-01-01T00:00:00Z"

    def test_sdk_object_to_dict_filters_none_values(self):
        """Test that None values are filtered out."""
        mock_obj = Mock()
        mock_obj.id = "123"
        mock_obj.title = None
        mock_obj.description = "Description"

        result = LookerContentExtractor._sdk_object_to_dict(mock_obj)

        assert result["id"] == "123"
        assert "title" not in result
        assert result["description"] == "Description"

    def test_sdk_object_to_dict_filters_private_attributes(self):
        """Test that private attributes (starting with _) are filtered out."""
        mock_obj = Mock()
        mock_obj.id = "123"
        mock_obj._internal = "private"
        mock_obj.public_field = "public"

        result = LookerContentExtractor._sdk_object_to_dict(mock_obj)

        assert result["id"] == "123"
        assert "_internal" not in result
        assert result["public_field"] == "public"
