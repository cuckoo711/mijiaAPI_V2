"""Tests for process-local rate limiting."""

from server.rate_limit import SlidingWindowRateLimiter


def test_sliding_window_rate_limiter_blocks_after_max() -> None:
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60.0)
    now = 1000.0
    assert limiter.check("ip", now=now).allowed
    assert limiter.check("ip", now=now + 1).allowed
    assert limiter.check("ip", now=now + 2).allowed
    blocked = limiter.check("ip", now=now + 3)
    assert not blocked.allowed
    assert blocked.retry_after_seconds >= 1

    # Different key is independent
    assert limiter.check("other", now=now + 3).allowed

    # After window slides, allow again
    assert limiter.check("ip", now=now + 61).allowed
