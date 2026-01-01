"""Wrapper for Looker SDK with custom configuration."""

import os
from typing import cast

import looker_sdk
from looker_sdk import error as looker_error
from looker_sdk.sdk.api40.methods import Looker40SDK

from lookervault.config.models import ConnectionStatus


class LookerClient:
    """Wrapper for Looker SDK with custom configuration and lazy initialization."""

    def __init__(
        self,
        api_url: str,
        client_id: str,
        client_secret: str,
        timeout: int = 30,
        verify_ssl: bool = True,
    ):
        """
        Initialize Looker client with configuration.

        Args:
            api_url: Base URL for Looker API
            client_id: OAuth client ID
            client_secret: OAuth client secret
            timeout: API request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
        """
        self.api_url = api_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self._sdk: Looker40SDK | None = None

    def _init_sdk(self) -> None:
        """Initialize Looker SDK with custom settings."""
        # Set environment variables for SDK configuration
        os.environ["LOOKERSDK_BASE_URL"] = self.api_url
        os.environ["LOOKERSDK_CLIENT_ID"] = self.client_id
        os.environ["LOOKERSDK_CLIENT_SECRET"] = self.client_secret
        os.environ["LOOKERSDK_VERIFY_SSL"] = str(self.verify_ssl).lower()
        os.environ["LOOKERSDK_TIMEOUT"] = str(self.timeout)

        self._sdk = looker_sdk.init40()

    @property
    def sdk(self) -> Looker40SDK:
        """
        Lazy-load SDK on first access.

        Returns:
            Initialized Looker40SDK instance
        """
        if self._sdk is None:
            self._init_sdk()
        return cast(Looker40SDK, self._sdk)

    def test_connection(self) -> ConnectionStatus:
        """
        Test connection to Looker instance and return status.

        Returns:
            ConnectionStatus with instance info or error message
        """
        try:
            # Test authentication by getting current user
            user = self.sdk.me()

            # Get instance version information
            versions = self.sdk.versions()

            # Return successful connection status
            return ConnectionStatus(
                connected=True,
                authenticated=True,
                instance_url=self.api_url,
                looker_version=versions.looker_release_version,
                api_version=versions.current_version.version
                if versions.current_version
                else "unknown",
                user_id=int(user.id) if user.id else None,
                user_email=user.email,
            )
        except looker_error.SDKError as e:
            # Connection or authentication failed
            error_msg = str(e)

            # Try to extract more useful error message
            if "401" in error_msg or "Unauthorized" in error_msg:
                error_msg = "Authentication failed - invalid credentials"
            elif "timeout" in error_msg.lower():
                error_msg = "Connection timeout - check network connectivity"
            elif "connection" in error_msg.lower():
                error_msg = "Cannot reach Looker instance - check API URL"

            return ConnectionStatus(
                connected=False,
                authenticated=False,
                error_message=error_msg,
            )
        except Exception as e:
            # Unexpected error
            return ConnectionStatus(
                connected=False,
                authenticated=False,
                error_message=f"Unexpected error: {str(e)}",
            )
