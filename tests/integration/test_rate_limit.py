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

    # 1. Send requests up to the limit. All should pass through the limiter
    # and reach the handler (which returns 401 due to invalid credentials).
    for _ in range(limite):
        respuesta = await client.post(url, json=payload)
        assert respuesta.status_code != 429, "Requests within the limit should not return 429"
        assert respuesta.status_code == 401

    # 2. The next request must exceed the limit and be intercepted by SlowAPI.
    respuesta_429 = await client.post(url, json=payload)

    # 3. Verify it returns HTTP 429.
    assert respuesta_429.status_code == 429

    # 4. Verify it respects our custom RFC 7807 handler.
    cuerpo = respuesta_429.json()
    assert cuerpo["code"] == "rate_limit"
    assert cuerpo["title"] == "Demasiadas solicitudes"
    assert "detail" in cuerpo

    # 5. Verify the Retry-After header is present.
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

    # This request exceeds the limit
    respuesta_429 = await client.post(url, json=payload, headers=headers)
    assert respuesta_429.status_code == 429
    assert respuesta_429.json()["code"] == "rate_limit"
    assert "Retry-After" in respuesta_429.headers


@pytest.mark.asyncio
async def test_limite_de_login_de_vecinos_bloquea_fuerza_bruta(client: AsyncClient) -> None:
    # Same ceiling as the staff login: settings.rate_limit_login is "10/minute".
    url = "/api/v1/auth/ciudadanos/login"
    payload = {"email": "vecina@ejemplo.com", "password": "no-es-la-clave"}

    for _ in range(10):
        respuesta = await client.post(url, json=payload)
        assert respuesta.status_code != 429

    bloqueado = await client.post(url, json=payload)
    assert bloqueado.status_code == 429
    assert bloqueado.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_el_registro_tiene_un_limite_mas_estricto(client: AsyncClient) -> None:
    # Tighter on purpose: a registration costs CPU (hashing) and creates rows.
    # settings.rate_limit_registro is "5/hour".
    url = "/api/v1/auth/ciudadanos/registro"

    for i in range(5):
        respuesta = await client.post(
            url,
            json={
                "email": f"vecina{i}@ejemplo.com",
                "password": "una-clave-larga",
                "nombre": "Vecina de prueba",
            },
        )
        assert respuesta.status_code != 429

    bloqueado = await client.post(
        url,
        json={
            "email": "una-mas@ejemplo.com",
            "password": "una-clave-larga",
            "nombre": "Vecina de prueba",
        },
    )
    assert bloqueado.status_code == 429
