"""Adaptive rate limiting for coordinated API request throttling across workers."""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class RateLimiterState:
    """Thread-safe state tracking for adaptive rate limiting.

    Tracks rate limit violations (HTTP 429 responses) and adjusts request
    rates dynamically to prevent future violations. Uses exponential backoff
    on 429 detection and gradual recovery after sustained success.

    Attributes:
        backoff_multiplier: Current rate reduction factor (1.0 = normal, >1.0 = slowed down)
        last_429_timestamp: Timestamp of most recent rate limit error
        consecutive_successes: Success count since last 429 (used for recovery)
        total_429_count: Total rate limit errors encountered
        _lock: Thread synchronization lock (private, reentrant)
    """

    backoff_multiplier: float = 1.0
    last_429_timestamp: datetime | None = None
    consecutive_successes: int = 0
    total_429_count: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def on_rate_limit_detected(self) -> None:
        """Increase backoff multiplier when HTTP 429 detected.

        Called by workers when they receive a 429 response. Increases
        the backoff multiplier by 1.5x, causing all future requests
        to slow down proportionally.
        """
        with self._lock:
            self.backoff_multiplier *= 1.5
            self.last_429_timestamp = datetime.now()
            self.consecutive_successes = 0
            self.total_429_count += 1

            logger.warning(
                f"Rate limit detected (429). Total: {self.total_429_count}. "
                f"Backoff multiplier increased to {self.backoff_multiplier:.2f}x"
            )

    def on_success(self) -> None:
        """Gradually reduce backoff after sustained success.

        Called after successful API requests. After 10 consecutive successes,
        reduces the backoff multiplier by 10% (towards 1.0 = normal speed).
        """
        with self._lock:
            self.consecutive_successes += 1

            # Gradual recovery: reduce backoff after 10 successful requests
            if self.consecutive_successes >= 10:
                old_multiplier = self.backoff_multiplier
                self.backoff_multiplier = max(1.0, self.backoff_multiplier * 0.9)
                self.consecutive_successes = 0

                if self.backoff_multiplier < old_multiplier:
                    logger.info(
                        f"Rate limit recovery: backoff reduced from "
                        f"{old_multiplier:.2f}x to {self.backoff_multiplier:.2f}x"
                    )

    def get_backoff_multiplier(self) -> float:
        """Get current backoff multiplier in a thread-safe manner.

        Returns:
            Current backoff multiplier (1.0 = normal, >1.0 = slowed)
        """
        with self._lock:
            return self.backoff_multiplier

    def get_stats(self) -> dict[str, int | float | str | None]:
        """Get thread-safe snapshot of rate limiter statistics.

        Returns:
            Dictionary with current state information
        """
        with self._lock:
            return {
                "backoff_multiplier": self.backoff_multiplier,
                "total_429_count": self.total_429_count,
                "consecutive_successes": self.consecutive_successes,
                "last_429": self.last_429_timestamp.isoformat()
                if self.last_429_timestamp
                else None,
            }


class AdaptiveRateLimiter:
    """Thread-safe adaptive rate limiter using sliding window algorithm.

    Coordinates API request rates across multiple worker threads using:
    - Sliding window rate limiting for proactive throttling
    - Adaptive backoff on HTTP 429 detection (reactive adjustment)
    - Shared state across all workers for coordinated slowdown

    The rate limiter operates in two layers:
    1. Proactive: Sliding window prevents exceeding configured limits
    2. Reactive: Adaptive backoff slows down further when 429s are detected

    Thread-safe: All methods can be called concurrently from multiple workers.

    Example:
        >>> # Shared across all workers
        >>> rate_limiter = AdaptiveRateLimiter(requests_per_minute=100, requests_per_second=10)
        >>>
        >>> # In worker thread before API call:
        >>> rate_limiter.acquire()  # Blocks if rate limit would be exceeded
        >>> try:
        >>>     response = make_api_call()
        >>>     rate_limiter.on_success()
        >>> except RateLimitError:  # HTTP 429
        >>>     rate_limiter.on_429_detected()
        >>>     raise
    """

    def __init__(
        self,
        requests_per_minute: int = 100,
        requests_per_second: int = 10,
        max_delay: int = 120,
        adaptive: bool = True,
    ):
        """Initialize adaptive rate limiter.

        Args:
            requests_per_minute: Maximum requests per minute across all workers
            requests_per_second: Maximum requests per second (burst allowance)
            max_delay: Maximum delay in seconds for rate limiting (unused, for API compatibility)
            adaptive: Enable adaptive backoff on 429 detection
        """
        self.requests_per_minute = requests_per_minute
        self.requests_per_second = requests_per_second
        self.adaptive = adaptive

        # Sliding window tracking (thread-safe)
        self._lock = threading.Lock()
        self._minute_window: deque[float] = deque()  # Timestamps of requests in past minute
        self._second_window: deque[float] = deque()  # Timestamps of requests in past second

        # Adaptive state (shared across workers)
        self.state = RateLimiterState()

        logger.info(
            f"Initialized AdaptiveRateLimiter: {requests_per_minute} req/min, "
            f"{requests_per_second} req/sec (burst), adaptive={adaptive}"
        )

    def acquire(self) -> None:
        """Acquire rate limit token before making API request.

        Blocks if rate limit would be exceeded. Uses sliding window algorithm
        to smooth out request bursts while respecting configured limits.

        Thread-safe: Can be called concurrently from multiple workers.
        """
        while True:
            with self._lock:
                now = time.time()

                # Clean old timestamps from windows
                cutoff_minute = now - 60.0
                while self._minute_window and self._minute_window[0] < cutoff_minute:
                    self._minute_window.popleft()

                cutoff_second = now - 1.0
                while self._second_window and self._second_window[0] < cutoff_second:
                    self._second_window.popleft()

                # Check if we can proceed
                minute_count = len(self._minute_window)
                second_count = len(self._second_window)

                if (
                    minute_count < self.requests_per_minute
                    and second_count < self.requests_per_second
                ):
                    # Accept request - add timestamps
                    self._minute_window.append(now)
                    self._second_window.append(now)
                    return

                # Rate limit exceeded - calculate sleep time
                sleep_time = 0.0
                if minute_count >= self.requests_per_minute:
                    # Oldest request in minute window
                    oldest = self._minute_window[0]
                    sleep_time = max(sleep_time, (oldest + 60.0) - now)

                if second_count >= self.requests_per_second:
                    # Oldest request in second window
                    oldest = self._second_window[0]
                    sleep_time = max(sleep_time, (oldest + 1.0) - now)

            # Sleep outside lock to allow other threads to proceed
            if sleep_time > 0:
                time.sleep(sleep_time + 0.01)  # Add 10ms buffer

    def on_429_detected(self) -> None:
        """Handle HTTP 429 rate limit response.

        Updates adaptive state to slow down all future requests.
        Only has effect if adaptive=True.

        Thread-safe: Can be called concurrently from multiple workers.
        """
        if self.adaptive:
            self.state.on_rate_limit_detected()

    def on_success(self) -> None:
        """Record successful API request for gradual recovery.

        After sustained success, reduces backoff multiplier towards normal speed.
        Only has effect if adaptive=True.

        Thread-safe: Can be called concurrently from multiple workers.
        """
        if self.adaptive:
            self.state.on_success()

    def get_stats(self) -> dict[str, int | float | str | None]:
        """Get current rate limiter statistics.

        Returns:
            Dictionary with rate limit configuration and state
        """
        stats = {
            "requests_per_minute": self.requests_per_minute,
            "requests_per_second": self.requests_per_second,
            "adaptive_enabled": self.adaptive,
        }

        if self.adaptive:
            stats.update(self.state.get_stats())

        return stats

    def __repr__(self) -> str:
        """Return string representation of rate limiter."""
        return (
            f"AdaptiveRateLimiter(rpm={self.requests_per_minute}, "
            f"rps={self.requests_per_second}, "
            f"adaptive={self.adaptive}, "
            f"backoff={self.state.get_backoff_multiplier():.2f}x)"
        )
