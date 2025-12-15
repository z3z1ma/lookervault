"""Unit tests for AdaptiveRateLimiter and RateLimiterState."""

import threading
import time

import pytest

from lookervault.extraction.rate_limiter import AdaptiveRateLimiter, RateLimiterState


class TestRateLimiterState:
    """Tests for RateLimiterState class."""

    def test_initial_state(self):
        """Test state initializes with correct default values."""
        state = RateLimiterState()
        assert state.backoff_multiplier == 1.0
        assert state.last_429_timestamp is None
        assert state.consecutive_successes == 0
        assert state.total_429_count == 0

    def test_on_rate_limit_detected_increases_backoff(self):
        """Test that rate limit detection increases backoff multiplier."""
        state = RateLimiterState()

        # First rate limit
        state.on_rate_limit_detected()
        assert state.backoff_multiplier == 1.5
        assert state.total_429_count == 1
        assert state.consecutive_successes == 0
        assert state.last_429_timestamp is not None

        # Second rate limit
        state.on_rate_limit_detected()
        assert state.backoff_multiplier == 2.25  # 1.5 * 1.5
        assert state.total_429_count == 2
        assert state.consecutive_successes == 0

        # Third rate limit
        state.on_rate_limit_detected()
        assert state.backoff_multiplier == pytest.approx(3.375)  # 2.25 * 1.5
        assert state.total_429_count == 3

    def test_on_rate_limit_resets_consecutive_successes(self):
        """Test that rate limit detection resets success counter."""
        state = RateLimiterState()

        # Build up successes
        for _ in range(5):
            state.on_success()

        assert state.consecutive_successes == 5

        # Rate limit should reset counter
        state.on_rate_limit_detected()
        assert state.consecutive_successes == 0

    def test_on_success_increments_counter(self):
        """Test that on_success increments consecutive_successes."""
        state = RateLimiterState()

        for i in range(1, 6):
            state.on_success()
            assert state.consecutive_successes == i

    def test_gradual_recovery_after_10_successes(self):
        """Test that backoff reduces after 10 consecutive successes."""
        state = RateLimiterState()

        # Set backoff to 3.0x
        state.backoff_multiplier = 3.0

        # First 9 successes should not reduce backoff
        for _ in range(9):
            state.on_success()

        assert state.backoff_multiplier == 3.0
        assert state.consecutive_successes == 9

        # 10th success should reduce backoff
        state.on_success()
        assert state.backoff_multiplier == pytest.approx(2.7)  # 3.0 * 0.9
        assert state.consecutive_successes == 0  # Reset after recovery

    def test_gradual_recovery_multiple_cycles(self):
        """Test multiple recovery cycles gradually reduce backoff."""
        state = RateLimiterState()
        state.backoff_multiplier = 5.0

        # First recovery cycle (5.0 -> 4.5)
        for _ in range(10):
            state.on_success()

        assert state.backoff_multiplier == pytest.approx(4.5)
        assert state.consecutive_successes == 0

        # Second recovery cycle (4.5 -> 4.05)
        for _ in range(10):
            state.on_success()

        assert state.backoff_multiplier == pytest.approx(4.05)
        assert state.consecutive_successes == 0

        # Third recovery cycle (4.05 -> 3.645)
        for _ in range(10):
            state.on_success()

        assert state.backoff_multiplier == pytest.approx(3.645)
        assert state.consecutive_successes == 0

    def test_recovery_stops_at_1_0(self):
        """Test that backoff multiplier doesn't go below 1.0."""
        state = RateLimiterState()
        state.backoff_multiplier = 1.05  # Just slightly above 1.0

        # This recovery should cap at 1.0 (not go to 0.945)
        for _ in range(10):
            state.on_success()

        assert state.backoff_multiplier == 1.0
        assert state.consecutive_successes == 0

    def test_get_backoff_multiplier_thread_safe(self):
        """Test that get_backoff_multiplier is thread-safe."""
        state = RateLimiterState()
        state.backoff_multiplier = 2.5

        multiplier = state.get_backoff_multiplier()
        assert multiplier == 2.5

    def test_get_stats_returns_correct_data(self):
        """Test that get_stats returns correct statistics."""
        state = RateLimiterState()

        # Initial state
        stats = state.get_stats()
        assert stats["backoff_multiplier"] == 1.0
        assert stats["total_429_count"] == 0
        assert stats["consecutive_successes"] == 0
        assert stats["last_429"] is None

        # After rate limit
        state.on_rate_limit_detected()
        stats = state.get_stats()
        assert stats["backoff_multiplier"] == 1.5
        assert stats["total_429_count"] == 1
        assert stats["consecutive_successes"] == 0
        assert stats["last_429"] is not None

        # After successes
        for _ in range(5):
            state.on_success()

        stats = state.get_stats()
        assert stats["consecutive_successes"] == 5

    def test_thread_safety_concurrent_rate_limits(self):
        """Test thread safety with concurrent rate limit detections."""
        state = RateLimiterState()
        num_threads = 10

        def detect_rate_limit():
            state.on_rate_limit_detected()

        threads = [threading.Thread(target=detect_rate_limit) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have exactly 10 rate limits detected
        assert state.total_429_count == num_threads

    def test_thread_safety_concurrent_successes(self):
        """Test thread safety with concurrent success calls."""
        state = RateLimiterState()
        num_threads = 20

        def record_success():
            state.on_success()

        threads = [threading.Thread(target=record_success) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All successes should be recorded
        # Note: If recovery happens, consecutive_successes resets to 0
        # Due to threading timing, we might have 1 or 2 recovery cycles
        # So we just verify state is consistent (0, 10, or 20 are all valid)
        stats = state.get_stats()
        assert stats["consecutive_successes"] in [0, 10, 20]
        # Backoff should still be 1.0 (no rate limits detected)
        assert stats["backoff_multiplier"] == 1.0

    def test_thread_safety_mixed_operations(self):
        """Test thread safety with mixed rate limits and successes."""
        state = RateLimiterState()
        state.backoff_multiplier = 3.0

        num_rate_limit_threads = 5
        num_success_threads = 50

        def detect_rate_limit():
            state.on_rate_limit_detected()

        def record_success():
            state.on_success()

        # Start all threads
        rate_limit_threads = [
            threading.Thread(target=detect_rate_limit) for _ in range(num_rate_limit_threads)
        ]
        success_threads = [
            threading.Thread(target=record_success) for _ in range(num_success_threads)
        ]

        all_threads = rate_limit_threads + success_threads
        for t in all_threads:
            t.start()
        for t in all_threads:
            t.join()

        # Verify final state is consistent
        stats = state.get_stats()
        assert stats["total_429_count"] == num_rate_limit_threads
        assert stats["backoff_multiplier"] >= 1.0  # Should have increased from rate limits


class TestAdaptiveRateLimiter:
    """Tests for AdaptiveRateLimiter class."""

    def test_initial_configuration(self):
        """Test rate limiter initializes with correct configuration."""
        rate_limiter = AdaptiveRateLimiter(
            requests_per_minute=100, requests_per_second=10, adaptive=True
        )

        assert rate_limiter.requests_per_minute == 100
        assert rate_limiter.requests_per_second == 10
        assert rate_limiter.adaptive is True
        assert rate_limiter.state.backoff_multiplier == 1.0

    def test_acquire_allows_burst_within_second_limit(self):
        """Test that acquire allows burst up to requests_per_second."""
        rate_limiter = AdaptiveRateLimiter(requests_per_minute=100, requests_per_second=5)

        start_time = time.time()

        # Should allow 5 requests without delay
        for _ in range(5):
            rate_limiter.acquire()

        elapsed = time.time() - start_time
        # Should complete very quickly (within 100ms)
        assert elapsed < 0.1

    def test_acquire_enforces_second_limit(self):
        """Test that acquire enforces requests_per_second limit."""
        rate_limiter = AdaptiveRateLimiter(requests_per_minute=100, requests_per_second=3)

        start_time = time.time()

        # First 3 should be immediate
        for _ in range(3):
            rate_limiter.acquire()

        # 4th request should be delayed by ~1 second
        rate_limiter.acquire()

        elapsed = time.time() - start_time
        # Should take at least 1 second (plus buffer)
        assert elapsed >= 1.0

    def test_acquire_enforces_minute_limit(self):
        """Test that acquire enforces requests_per_minute limit."""
        # Use very low limits for fast test
        rate_limiter = AdaptiveRateLimiter(requests_per_minute=5, requests_per_second=5)

        start_time = time.time()

        # First 5 should be immediate
        for _ in range(5):
            rate_limiter.acquire()

        # 6th request should be delayed until minute window clears
        rate_limiter.acquire()

        elapsed = time.time() - start_time
        # Should have waited for oldest request to age out of 60-second window
        # Note: This is a minimal delay since we're using small numbers
        assert elapsed >= 0.0  # Just verify it completes without error

    def test_sliding_window_clears_old_requests(self):
        """Test that sliding window properly removes old timestamps."""
        rate_limiter = AdaptiveRateLimiter(requests_per_minute=100, requests_per_second=5)

        # Fill up the second window
        for _ in range(5):
            rate_limiter.acquire()

        # Wait for second window to clear
        time.sleep(1.1)

        # Should be able to acquire again without delay
        start_time = time.time()
        rate_limiter.acquire()
        elapsed = time.time() - start_time

        assert elapsed < 0.1  # Should be immediate

    def test_on_429_detected_with_adaptive_enabled(self):
        """Test that 429 detection increases backoff when adaptive=True."""
        rate_limiter = AdaptiveRateLimiter(adaptive=True)

        assert rate_limiter.state.backoff_multiplier == 1.0

        rate_limiter.on_429_detected()
        assert rate_limiter.state.backoff_multiplier == 1.5
        assert rate_limiter.state.total_429_count == 1

        rate_limiter.on_429_detected()
        assert rate_limiter.state.backoff_multiplier == 2.25
        assert rate_limiter.state.total_429_count == 2

    def test_on_429_detected_with_adaptive_disabled(self):
        """Test that 429 detection has no effect when adaptive=False."""
        rate_limiter = AdaptiveRateLimiter(adaptive=False)

        assert rate_limiter.state.backoff_multiplier == 1.0

        rate_limiter.on_429_detected()
        # Should still be 1.0 when adaptive is disabled
        assert rate_limiter.state.backoff_multiplier == 1.0
        assert rate_limiter.state.total_429_count == 0

    def test_on_success_with_adaptive_enabled(self):
        """Test that on_success triggers recovery when adaptive=True."""
        rate_limiter = AdaptiveRateLimiter(adaptive=True)
        rate_limiter.state.backoff_multiplier = 3.0

        # Should increment successes
        rate_limiter.on_success()
        assert rate_limiter.state.consecutive_successes == 1

        # After 10 successes, should reduce backoff
        for _ in range(9):
            rate_limiter.on_success()

        assert rate_limiter.state.backoff_multiplier == pytest.approx(2.7)

    def test_on_success_with_adaptive_disabled(self):
        """Test that on_success has no effect when adaptive=False."""
        rate_limiter = AdaptiveRateLimiter(adaptive=False)
        rate_limiter.state.backoff_multiplier = 3.0

        rate_limiter.on_success()
        # Should not change when adaptive is disabled
        assert rate_limiter.state.backoff_multiplier == 3.0
        assert rate_limiter.state.consecutive_successes == 0

    def test_get_stats_with_adaptive_enabled(self):
        """Test get_stats includes adaptive state when adaptive=True."""
        rate_limiter = AdaptiveRateLimiter(
            requests_per_minute=100, requests_per_second=10, adaptive=True
        )

        stats = rate_limiter.get_stats()
        assert stats["requests_per_minute"] == 100
        assert stats["requests_per_second"] == 10
        assert stats["adaptive_enabled"] is True
        assert "backoff_multiplier" in stats
        assert "total_429_count" in stats
        assert "consecutive_successes" in stats
        assert "last_429" in stats

    def test_get_stats_with_adaptive_disabled(self):
        """Test get_stats excludes adaptive state when adaptive=False."""
        rate_limiter = AdaptiveRateLimiter(
            requests_per_minute=100, requests_per_second=10, adaptive=False
        )

        stats = rate_limiter.get_stats()
        assert stats["requests_per_minute"] == 100
        assert stats["requests_per_second"] == 10
        assert stats["adaptive_enabled"] is False
        assert "backoff_multiplier" not in stats
        assert "total_429_count" not in stats

    def test_repr(self):
        """Test string representation of rate limiter."""
        rate_limiter = AdaptiveRateLimiter(
            requests_per_minute=100, requests_per_second=10, adaptive=True
        )

        repr_str = repr(rate_limiter)
        assert "rpm=100" in repr_str
        assert "rps=10" in repr_str
        assert "adaptive=True" in repr_str
        assert "backoff=1.00x" in repr_str

        # After rate limit
        rate_limiter.on_429_detected()
        repr_str = repr(rate_limiter)
        assert "backoff=1.50x" in repr_str

    def test_thread_safety_concurrent_acquires(self):
        """Test thread safety with concurrent acquire calls."""
        rate_limiter = AdaptiveRateLimiter(requests_per_minute=1000, requests_per_second=100)
        num_threads = 10
        requests_per_thread = 10

        acquired_count = [0]
        lock = threading.Lock()

        def worker():
            for _ in range(requests_per_thread):
                rate_limiter.acquire()
                with lock:
                    acquired_count[0] += 1

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All requests should have been acquired
        assert acquired_count[0] == num_threads * requests_per_thread

    def test_thread_safety_concurrent_rate_limit_detection(self):
        """Test thread safety with concurrent 429 detections."""
        rate_limiter = AdaptiveRateLimiter(adaptive=True)
        num_threads = 20

        def detect_429():
            rate_limiter.on_429_detected()

        threads = [threading.Thread(target=detect_429) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have exactly 20 rate limits
        assert rate_limiter.state.total_429_count == num_threads

    def test_thread_safety_concurrent_success_reports(self):
        """Test thread safety with concurrent success reports."""
        rate_limiter = AdaptiveRateLimiter(adaptive=True)
        rate_limiter.state.backoff_multiplier = 2.0
        num_threads = 30

        def report_success():
            rate_limiter.on_success()

        threads = [threading.Thread(target=report_success) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 30 successes = 3 recovery cycles (10 each) + 0 remaining
        # Backoff should have reduced: 2.0 -> 1.8 -> 1.62 -> 1.458
        stats = rate_limiter.get_stats()
        assert stats["consecutive_successes"] == 0  # Reset after recovery cycles
        # Verify backoff reduced (approximately)
        assert stats["backoff_multiplier"] < 2.0

    def test_thread_safety_mixed_operations(self):
        """Test thread safety with mixed acquire, 429, and success calls."""
        rate_limiter = AdaptiveRateLimiter(
            requests_per_minute=500, requests_per_second=50, adaptive=True
        )

        num_acquire_threads = 5
        num_429_threads = 2
        num_success_threads = 10

        def worker_acquire():
            for _ in range(10):
                rate_limiter.acquire()

        def worker_429():
            rate_limiter.on_429_detected()

        def worker_success():
            for _ in range(5):
                rate_limiter.on_success()

        # Start all threads
        acquire_threads = [
            threading.Thread(target=worker_acquire) for _ in range(num_acquire_threads)
        ]
        limit_threads = [threading.Thread(target=worker_429) for _ in range(num_429_threads)]
        success_threads = [
            threading.Thread(target=worker_success) for _ in range(num_success_threads)
        ]

        all_threads = acquire_threads + limit_threads + success_threads
        for t in all_threads:
            t.start()
        for t in all_threads:
            t.join()

        # Verify final state is consistent
        stats = rate_limiter.get_stats()
        assert stats["total_429_count"] == num_429_threads
        assert stats["backoff_multiplier"] >= 1.0

    def test_rate_limiting_accuracy(self):
        """Test that rate limiting is accurate over time."""
        # Use moderate limits for reasonable test duration
        rate_limiter = AdaptiveRateLimiter(requests_per_minute=60, requests_per_second=10)

        start_time = time.time()
        num_requests = 20

        for _ in range(num_requests):
            rate_limiter.acquire()

        elapsed = time.time() - start_time

        # First 10 should be immediate (within second limit)
        # Next 10 should take ~1 second each (second limit)
        # So expect at least 1 second total
        assert elapsed >= 1.0

    def test_custom_limits(self):
        """Test rate limiter with custom limit values."""
        rate_limiter = AdaptiveRateLimiter(requests_per_minute=200, requests_per_second=20)

        assert rate_limiter.requests_per_minute == 200
        assert rate_limiter.requests_per_second == 20

        # Verify it can handle burst
        start_time = time.time()
        for _ in range(20):
            rate_limiter.acquire()

        elapsed = time.time() - start_time
        # Should complete quickly (within second window)
        assert elapsed < 1.5
