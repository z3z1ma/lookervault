"""Custom exception classes for LookerVault."""


class ConfigError(Exception):
    """Exception raised for configuration errors."""

    pass


class ConnectionError(Exception):
    """Exception raised for Looker connection errors."""

    pass
