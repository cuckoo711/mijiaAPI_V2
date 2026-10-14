"""Keep authentication throttling independent between isolated server tests."""
import pytest

from server.rate_limit import SlidingWindowRateLimiter
from server.routers import admin_auth


@pytest.fixture(autouse=True)
def isolated_admin_auth_limiter(monkeypatch):
    # Each test creates a fresh store/app, so it must also get fresh process-local
    # authentication state. Keep the production limit so rate-limit tests work.
    monkeypatch.setattr(
        admin_auth, 'ADMIN_AUTH_RATE_LIMITER',
        SlidingWindowRateLimiter(max_requests=20, window_seconds=300),
    )
