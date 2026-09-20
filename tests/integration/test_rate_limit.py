"""Integration tests for the Rate Limiting layer.

These tests verify that SlowAPI correctly intercepts bursts of requests,
emits the expected HTTP 429 with RFC 7807 formatting, and respects the
limits defined in the application settings.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.rate_limit import limiter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _setup_limiter() -> None:
    """Enable the rate limiter for these tests and clean up afterwards.
    
    The global test suite runs with RATE_LIMIT_ENABLED=false (see conftest.py)
    to prevent fast tests from tripping 429s. We turn it on locally here.
    """
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.enabled = False
    limiter.reset()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_limite_de_login_bloquea_fuerza_bruta(client: AsyncClient) -> None:
    # settings.rate_limit_login is "10/minute"
    limite = 10
    url = "/api/v1/auth/dev/login"
    payload = {"usuario": "admin", "password": "wrong"}

    # 1. Hacemos requests hasta el limite. Todos deberian pasar el limiter
    # y llegar al handler (que devolvera 401 por password incorrecta).
    for _ in range(limite):
        respuesta = await client.post(url, json=payload)
        assert respuesta.status_code != 429, "Requests dentro del limite no devuelven 429"
        assert respuesta.status_code == 401

    # 2. El siguiente request debe exceder el limite y ser interceptado por SlowAPI.
    respuesta_429 = await client.post(url, json=payload)
    
    # 3. Verificamos que es 429
    assert respuesta_429.status_code == 429
    
    # 4. Verificamos que respeta nuestro handler personalizado (RFC 7807)
    cuerpo = respuesta_429.json()
    assert cuerpo["code"] == "rate_limit"
    assert cuerpo["title"] == "Demasiadas solicitudes"
    assert "detail" in cuerpo
    
    # 5. Verificamos que existe el header Retry-After
    assert "Retry-After" in respuesta_429.headers
    assert respuesta_429.headers["Retry-After"].isdigit()


@pytest.mark.asyncio
async def test_creacion_reclamo_tiene_rate_limit(
    client: AsyncClient, auth, token_ciudadano: str
) -> None:
    # settings.rate_limit_creacion is "10/minute"
    limite = 10
    url = "/api/v1/reclamos"
    payload = {
        "titulo": "Bache gigante",
        "descripcion": "Rompi la cubierta.",
        "barrio": "Centro",
        "direccion": "San Martin 100",
    }
    headers = auth(token_ciudadano)

    for _ in range(limite):
        respuesta = await client.post(url, json=payload, headers=headers)
        assert respuesta.status_code != 429
        assert respuesta.status_code == 201

    # Este request excede el limite
    respuesta_429 = await client.post(url, json=payload, headers=headers)
    assert respuesta_429.status_code == 429
    assert respuesta_429.json()["code"] == "rate_limit"
    assert "Retry-After" in respuesta_429.headers
