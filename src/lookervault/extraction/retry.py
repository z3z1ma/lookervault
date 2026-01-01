"""Retry decorators for API calls with exponential back-off."""

from collections.abc import Callable
from functools import wraps
from typing import TypeVar

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from lookervault.constants import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_RETRIES_NETWORK,
    DEFAULT_MAX_RETRY_WAIT_SECONDS,
    DEFAULT_RETRY_DELAY_SECONDS,
)
from lookervault.exceptions import RateLimitError

T = TypeVar("T")


def with_retry(
    max_attempts: int = DEFAULT_MAX_RETRIES,
    min_wait: int = DEFAULT_RETRY_DELAY_SECONDS,
    max_wait: int = DEFAULT_MAX_RETRY_WAIT_SECONDS,
    multiplier: int = 2,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to add retry logic with exponential back-off.

    Args:
        max_attempts: Maximum number of retry attempts
        min_wait: Minimum wait time in seconds
        max_wait: Maximum wait time in seconds
        multiplier: Exponential multiplier for back-off

    Returns:
        Decorated function with retry logic
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        @retry(
            retry=retry_if_exception_type(RateLimitError),
            wait=wait_exponential(multiplier=multiplier, min=min_wait, max=max_wait),
            stop=stop_after_attempt(max_attempts),
        )
        def wrapper(*args, **kwargs) -> T:
            return func(*args, **kwargs)

        return wrapper

    return decorator


# Pre-configured decorators for common scenarios
retry_on_rate_limit = with_retry(
    max_attempts=DEFAULT_MAX_RETRIES,
    min_wait=4,
    max_wait=DEFAULT_MAX_RETRY_WAIT_SECONDS,
    multiplier=2,
)
retry_on_network_error = with_retry(
    max_attempts=DEFAULT_MAX_RETRIES_NETWORK,
    min_wait=DEFAULT_RETRY_DELAY_SECONDS,
    max_wait=10,
    multiplier=2,
)
