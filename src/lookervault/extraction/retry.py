"""Retry decorators for API calls with exponential back-off."""

import os
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


def _in_test_mode() -> bool:
    """Check if we're running in a pytest environment.

    Lazily evaluates test mode at runtime (not import time) to ensure
    pytest environment variables are available when checked.

    Returns:
        True if running under pytest, False otherwise.
    """
    return (
        os.environ.get("PYTEST_XDIST_WORKER") is not None
        or os.environ.get("PYTEST_CURRENT_TEST") is not None
        or os.environ.get("LOOKERVAULT_TEST_MODE") == "1"
    )


def _get_wait_times(
    force_fast_retry: bool = False,
) -> tuple[float, float]:
    """Get appropriate wait times based on environment.

    Args:
        force_fast_retry: If True, force fast retry times regardless of environment

    Returns:
        Tuple of (min_wait, max_wait) in seconds
    """
    if _in_test_mode() or force_fast_retry:
        return 0.01, 0.1  # 10ms - 100ms for tests
    return 4.0, 120.0  # Production defaults


def with_retry(
    max_attempts: int = DEFAULT_MAX_RETRIES,
    min_wait: int = DEFAULT_RETRY_DELAY_SECONDS,
    max_wait: int = DEFAULT_MAX_RETRY_WAIT_SECONDS,
    multiplier: int = 2,
    force_fast_retry: bool = False,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to add retry logic with exponential back-off.

    Args:
        max_attempts: Maximum number of retry attempts
        min_wait: Minimum wait time in seconds (ignored if in test mode)
        max_wait: Maximum wait time in seconds (ignored if in test mode)
        multiplier: Exponential multiplier for back-off
        force_fast_retry: If True, use fast retry times (for testing)

    Returns:
        Decorated function with retry logic
    """
    # Determine wait times at decorator application time
    actual_min_wait, actual_max_wait = _get_wait_times(force_fast_retry)

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        @retry(
            retry=retry_if_exception_type(RateLimitError),
            wait=wait_exponential(multiplier=multiplier, min=actual_min_wait, max=actual_max_wait),
            stop=stop_after_attempt(max_attempts),
        )
        def wrapper(*args, **kwargs) -> T:
            return func(*args, **kwargs)

        return wrapper

    return decorator


# Pre-configured decorators for common scenarios
# Note: These are created at module import time, but _get_wait_times()
# checks for test mode dynamically
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
