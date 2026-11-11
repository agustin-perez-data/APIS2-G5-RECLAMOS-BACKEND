"""Protected Analytics endpoint with real JWT validation and a fake HTTP client."""

from __future__ import annotations

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.api.errors import registrar_manejadores
from app.api.v1 import analitica
from app.core import security
from app.core.config import Settings
from app.integrations.analitica import ErrorAnalitica, TableroAnalitica

RUTA = "/api/v1/admin/analitica"


class ClienteFalso:
    def __init__(self) -> None:
        self.tokens: list[str] = []
        self.error: ErrorAnalitica | None = None
        self.tablero = TableroAnalitica(
            html="<html><body>Indicadores</body></html>",
            content_type="text/html; charset=utf-8",
            cache_control="no-store, private",
            content_security_policy="default-src 'none'",
        )

    async def obtener_tablero(self, token: str) -> TableroAnalitica:
        self.tokens.append(token)
        if self.error:
            raise self.error
        return self.tablero


@pytest.fixture
def entorno(monkeypatch):
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cfg = Settings(
        analitica_enabled=True,
        analitica_url="https://analitica.example",
        auth_enabled=True,
        auth_dev_login_enabled=False,
        jwt_algorithm="RS256",
        jwt_jwks_url="https://login.example/jwks",
        jwt_issuer="https://idp.citypass.local",
        jwt_audience="citypass-reclamos-api",
        jwt_roles_claim="groups",
        jwt_staff_estricto=True,
        jwt_token_use_esperado="human",
        jwt_staff_grupos_admin=["reclamos-administradores"],
        jwt_staff_grupos_operador=["reclamos-operadores"],
        gateway_client_secret="secreto-de-test",
    )
    monkeypatch.setattr(deps, "settings", cfg)
    monkeypatch.setattr(security, "settings", cfg)
    monkeypatch.setattr(
        security,
        "_jwks_client",
        lambda _url: SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=clave.public_key())
        ),
    )
    app = FastAPI()
    registrar_manejadores(app)
    app.include_router(analitica.router, prefix="/api/v1")
    cliente = ClienteFalso()
    app.state.analitica = cliente
    return cfg, clave, app, cliente


def token_staff(cfg: Settings, clave, **cambios) -> str:
    claims = {
        "sub": "U000042",
        "iss": cfg.jwt_issuer,
        "aud": [cfg.jwt_audience],
        "exp": int(time.time()) + 900,
        "token_use": "human",
        "module": "reclamos",
        "groups": ["reclamos-administradores"],
    }
    claims.update(cambios)
    return jwt.encode(claims, clave, algorithm="RS256")


async def pedir(app: FastAPI, token: str | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        return await http.get(RUTA, headers=headers)


async def test_admin_federado_recibe_html_y_se_reenvia_el_jwt_original(entorno) -> None:
    cfg, clave, app, cliente = entorno
    token = token_staff(cfg, clave)

    respuesta = await pedir(app, token)

    assert respuesta.status_code == 200
    assert respuesta.text == cliente.tablero.html
    assert respuesta.headers["content-type"] == cliente.tablero.content_type
    assert respuesta.headers["cache-control"] == "no-store, private"
    assert respuesta.headers["content-security-policy"] == "default-src 'none'"
    assert respuesta.headers["x-content-type-options"] == "nosniff"
    assert cliente.tokens == [token]


@pytest.mark.parametrize(
    ("claims", "codigo"),
    [
        ({"groups": ["reclamos-operadores"]}, 403),
        ({"module": "analitica"}, 403),
        ({"token_use": "service"}, 401),
        ({"iss": "https://otro-emisor.example"}, 401),
        ({"exp": 1}, 401),
    ],
)
async def test_rechaza_identidades_sin_permiso(entorno, claims: dict, codigo: int) -> None:
    cfg, clave, app, cliente = entorno
    respuesta = await pedir(app, token_staff(cfg, clave, **claims))
    assert respuesta.status_code == codigo
    assert cliente.tokens == []


async def test_rechaza_ausencia_de_token_y_token_ciudadano(entorno) -> None:
    cfg, _clave, app, cliente = entorno
    assert (await pedir(app)).status_code == 401
    ciudadano = jwt.encode(
        {
            "sub": "vecino-1",
            "iss": cfg.jwt_ciudadanos_issuer,
            "aud": cfg.jwt_ciudadanos_audience,
            "exp": int(time.time()) + 900,
            "roles": ["admin"],
        },
        cfg.jwt_ciudadanos_secret,
        algorithm="HS256",
    )
    assert (await pedir(app, ciudadano)).status_code == 403
    assert cliente.tokens == []


@pytest.mark.parametrize(("upstream", "esperado"), [(401, 502), (403, 403), (503, 502)])
async def test_errores_de_analitica_no_exponen_su_respuesta(
    entorno, upstream: int, esperado: int
) -> None:
    cfg, clave, app, cliente = entorno
    cliente.error = ErrorAnalitica(upstream)
    respuesta = await pedir(app, token_staff(cfg, clave))
    assert respuesta.status_code == esperado
    assert respuesta.headers["content-type"] == "application/problem+json"
    assert "Analítica no disponible" in respuesta.text


async def test_fuerza_no_store_si_analitica_no_lo_envia(entorno) -> None:
    cfg, clave, app, cliente = entorno
    cliente.tablero = TableroAnalitica("<html></html>", "text/html", "public, max-age=600", None)
    respuesta = await pedir(app, token_staff(cfg, clave))
    assert respuesta.status_code == 200
    assert respuesta.headers["cache-control"] == "no-store"
    assert "content-security-policy" not in respuesta.headers


def test_configuracion_no_habilita_analitica_sin_identidad_federada() -> None:
    assert not Settings().analitica_enabled
    with pytest.raises(ValueError, match="AUTH_ENABLED=true y JWT_ALGORITHM=RS256"):
        Settings(analitica_enabled=True, analitica_url="https://analitica.example")
