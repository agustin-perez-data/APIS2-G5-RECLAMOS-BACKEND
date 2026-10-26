"""How the rate limiter identifies a client behind a reverse proxy.

The platform changed from Railway to Render and each one announces the original
client IP in a different header. Getting this wrong is silent: the limiter falls
back to the proxy's address and every user shares a single bucket, so ten logins
from anyone lock out the rest.
"""

from __future__ import annotations

from starlette.requests import Request

from app.core.rate_limit import _get_key


def _request(headers: dict[str, str], ip: str = "10.0.0.7") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": (ip, 12345),
        }
    )


def test_usa_x_real_ip_cuando_viene() -> None:
    assert _get_key(_request({"X-Real-IP": "200.1.2.3"})) == "200.1.2.3"


def test_usa_x_forwarded_for_cuando_no_hay_x_real_ip() -> None:
    # Render announces it this way.
    assert _get_key(_request({"X-Forwarded-For": "200.1.2.3"})) == "200.1.2.3"


def test_toma_el_primero_de_la_cadena_de_proxies() -> None:
    # `X-Forwarded-For` grows as it crosses proxies: the client is the leftmost.
    pedido = _request({"X-Forwarded-For": "200.1.2.3, 10.0.0.1, 10.0.0.2"})
    assert _get_key(pedido) == "200.1.2.3"


def test_sin_cabeceras_usa_la_ip_del_socket() -> None:
    # Local development, with no proxy in front.
    assert _get_key(_request({})) == "10.0.0.7"
