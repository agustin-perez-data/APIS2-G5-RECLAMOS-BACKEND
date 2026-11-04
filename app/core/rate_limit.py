"""Rate limiting configuration.

Uses SlowAPI with in-memory storage. Good enough for a single-instance deploy.
If the service scales to multiple replicas, swap the storage for Redis - but
that is not needed now.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def _get_key(request) -> str:
    """Identify the client by its real IP address.

    Behind a reverse proxy ``request.client.host`` is the proxy, not the user,
    so every client would share a single bucket and ten requests from anyone
    would lock out the rest. Each platform announces the original address in a
    different header, and we read both because the hosting moved from Railway
    to Render:

    * ``X-Real-IP`` - what Railway injects.
    * ``X-Forwarded-For`` - what Render sends. It grows as the request crosses
      proxies, and the client is the leftmost entry.

    With neither, which is local development, the socket address is correct.

    Note that both headers are taken on trust. Reaching the service without
    going through the platform's proxy would let a caller forge them and walk
    past the limit; today the proxy is the only way in.
    """
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()

    reenviadas = request.headers.get("x-forwarded-for")
    if reenviadas:
        return reenviadas.split(",")[0].strip()

    return get_remote_address(request)


limiter = Limiter(
    key_func=_get_key,
    # default_limits=[settings.rate_limit_default],
    enabled=settings.rate_limit_enabled,
)
