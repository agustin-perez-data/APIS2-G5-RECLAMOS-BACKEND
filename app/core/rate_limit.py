"""Rate limiting configuration.

Uses SlowAPI with in-memory storage. Good enough for a single-instance deploy
(Railway). If the service scales to multiple replicas, swap the storage for
Redis - but that is not needed now.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def _get_key(request) -> str:
    """Identify the client by its real IP address.

    When deployed behind Railway's reverse proxy, ``request.client.host``
    resolves to the proxy's internal IP rather than the end user's IP.
    Railway injects the original client IP in the ``X-Real-IP`` header, so
    we use that when present. In local development the header is absent and
    we fall back to the raw socket address.
    """
    return request.headers.get("x-real-ip") or get_remote_address(request)


limiter = Limiter(
    key_func=_get_key,
    # default_limits=[settings.rate_limit_default],
    enabled=settings.rate_limit_enabled,
)
