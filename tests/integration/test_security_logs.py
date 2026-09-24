"""Security audit log tests.

Each test verifies two things simultaneously:
  1. The HTTP response has the expected status code.
  2. The expected structlog event was emitted.

`structlog.testing.capture_logs()` is the canonical way to assert on structlog
events: it short-circuits the processor chain and collects the raw event dicts,
bypassing the ConsoleRenderer/JSONRenderer so the output is stable regardless
of the environment configuration (is_local, etc.).

This separates the concern of "does the endpoint reject the request?" (already
covered by test_reclamos_api.py) from "does it leave an audit trail?".
"""

from __future__ import annotations

import pytest
import structlog
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENDPOINT_PROTEGIDO = "/api/v1/reclamos"
_ENDPOINT_SOLO_ADMIN = "/api/v1/reclamos/estadisticas"


# ---------------------------------------------------------------------------
# 401 - missing Authorization header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sin_token_emite_seguridad_token_ausente(
    client: AsyncClient,
) -> None:
    # Request without any Authorization header.
    with structlog.testing.capture_logs() as capturados:
        respuesta = await client.post(_ENDPOINT_PROTEGIDO, json={})

    assert respuesta.status_code == 401

    eventos = [e["event"] for e in capturados]
    assert "seguridad.token_ausente" in eventos


# ---------------------------------------------------------------------------
# 401 - invalid / expired JWT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_invalido_emite_seguridad_token_invalido(
    client: AsyncClient,
) -> None:
    # A well-formed Bearer header but the token is garbage.
    with structlog.testing.capture_logs() as capturados:
        respuesta = await client.get(
            _ENDPOINT_PROTEGIDO,
            headers={"Authorization": "Bearer no-es-un-jwt-valido"},
        )

    assert respuesta.status_code == 401

    eventos = [e["event"] for e in capturados]
    assert "seguridad.token_invalido" in eventos

    # The `razon` field must also be present: it distinguishes a forged token
    # from an expired one, which is critical for incident investigation.
    registro = next(e for e in capturados if e["event"] == "seguridad.token_invalido")
    assert registro.get("razon"), "log record must include 'razon' field"


# ---------------------------------------------------------------------------
# 403 - authenticated user lacks the required role
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rol_insuficiente_emite_seguridad_acceso_denegado(
    client: AsyncClient,
    auth,
    token_ciudadano: str,
) -> None:
    # `token_ciudadano` carries the `ciudadano` role only; the statistics
    # endpoint is restricted to `admin`.
    with structlog.testing.capture_logs() as capturados:
        respuesta = await client.get(_ENDPOINT_SOLO_ADMIN, headers=auth(token_ciudadano))

    assert respuesta.status_code == 403

    eventos = [e["event"] for e in capturados]
    assert "seguridad.acceso_denegado" in eventos

    # Verify the contextual fields that make the log actionable.
    registro = next(e for e in capturados if e["event"] == "seguridad.acceso_denegado")
    assert registro.get("usuario_id"), "log record must include 'usuario_id'"
    assert registro.get("roles_usuario") is not None, "log record must include 'roles_usuario'"
    assert registro.get("roles_requeridos") is not None, (
        "log record must include 'roles_requeridos'"
    )
