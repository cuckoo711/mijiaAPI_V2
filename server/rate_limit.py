"""Simple in-process rate limiting for sensitive admin endpoints."""

from __future__ import annotations

import threading
import time
from typing import Optional
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int = 0


class SlidingWindowRateLimiter:
    """Per-key sliding window limiter (process-local, best-effort)."""

    def __init__(self, *, max_requests: int, window_seconds: float) -> None:
        self._max_requests = max(1, max_requests)
        self._window_seconds = max(0.1, window_seconds)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, *, now: Optional[float] = None) -> RateLimitResult:
        current = time.monotonic() if now is None else now
        cutoff = current - self._window_seconds
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self._max_requests:
                retry_after = max(1, int(self._window_seconds - (current - bucket[0])) + 1)
                return RateLimitResult(allowed=False, retry_after_seconds=retry_after)
            bucket.append(current)
            return RateLimitResult(allowed=True)


# Login / bootstrap: 20 attempts per IP per 5 minutes is still above normal use,
# but slows credential stuffing when the host is exposed.
ADMIN_AUTH_RATE_LIMITER = SlidingWindowRateLimiter(max_requests=20, window_seconds=300.0)
