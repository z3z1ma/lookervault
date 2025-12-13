"""Connection testing and Looker instance information retrieval."""

from lookervault.config.models import Configuration, ConnectionStatus
from lookervault.looker.client import LookerClient


def connect_and_get_info(config: Configuration) -> ConnectionStatus:
    """
    Connect to Looker instance and retrieve information.

    Args:
        config: Configuration with Looker connection details

    Returns:
        ConnectionStatus with instance info or error details
    """
    # Validate credentials are present
    if not config.looker.client_id or not config.looker.client_secret:
        return ConnectionStatus(
            connected=False,
            authenticated=False,
            error_message="Missing credentials - set LOOKERVAULT_CLIENT_ID and LOOKERVAULT_CLIENT_SECRET",
        )

    # Create Looker client
    client = LookerClient(
        api_url=str(config.looker.api_url),
        client_id=config.looker.client_id,
        client_secret=config.looker.client_secret,
        timeout=config.looker.timeout,
        verify_ssl=config.looker.verify_ssl,
    )

    # Test connection
    return client.test_connection()
