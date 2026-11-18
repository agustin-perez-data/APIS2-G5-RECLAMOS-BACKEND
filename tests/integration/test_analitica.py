"""Protected Analytics endpoint with real JWT validation and a fake HTTP client."""

from __future__ import annotations

import asyncio
import gzip
import time
from dataclasses import replace
from importlib import import_module
from types import SimpleNamespace

import httpx
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
from app.integrations.analitica import AnaliticaClient, ErrorAnalitica, TableroAnalitica

RUTA = "/api/v1/admin/analitica"
CABECERAS = (
    (b"content-type", b"text/html; charset=utf-8"),
    (b"cache-control", b"no-store, private"),
    (b"content-security-policy", b"default-src 'none'"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
)


class ClienteFalso:
    def __init__(self) -> None:
        self.tokens: list[str] = []
        self.error: ErrorAnalitica | None = None
        self.tablero = TableroAnalitica(
            html="<html><body>Indicadores de resolución</body></html>".encode(),
            headers=CABECERAS,
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
    assert respuesta.content == cliente.tablero.html
    assert respuesta.headers["content-type"] == "text/html; charset=utf-8"
    assert respuesta.headers["cache-control"] == "no-store, private"
    assert respuesta.headers["content-security-policy"] == "default-src 'none'"
    assert respuesta.headers["x-content-type-options"] == "nosniff"
    assert respuesta.headers["referrer-policy"] == "no-referrer"
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


async def test_rechaza_firma_alterada_audiencia_ajena_y_grupos_vacios(entorno, caplog) -> None:
    cfg, clave, app, cliente = entorno
    otro_firmante = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    casos = [
        (token_staff(cfg, otro_firmante), 401),
        (token_staff(cfg, clave, aud=["citypass-analitica-api"]), 401),
        (token_staff(cfg, clave, groups=[]), 403),
        (token_staff(cfg, clave, module=None), 403),
    ]
    for token, codigo in casos:
        respuesta = await pedir(app, token)
        assert respuesta.status_code == codigo
        assert token not in respuesta.text
        assert token not in caplog.text
    assert cliente.tokens == []


@pytest.mark.parametrize(
    ("upstream", "esperado"),
    [
        (301, 502),
        (302, 502),
        (401, 502),
        (403, 403),
        (404, 502),
        (429, 502),
        (500, 502),
        (503, 503),
    ],
)
async def test_errores_de_analitica_no_exponen_su_respuesta(
    entorno, upstream: int, esperado: int
) -> None:
    cfg, clave, app, cliente = entorno
    cliente.error = ErrorAnalitica(upstream)
    respuesta = await pedir(app, token_staff(cfg, clave))
    assert respuesta.status_code == esperado
    assert respuesta.headers["content-type"] == "application/problem+json"
    assert respuesta.headers["cache-control"] == "no-store"
    assert "Analítica no disponible" in respuesta.text


async def test_conserva_los_bytes_y_las_csp_repetidas(entorno) -> None:
    cfg, clave, app, cliente = entorno
    html = b"\xef\xbb\xbf" + cliente.tablero.html + b"\r\n"
    cliente.tablero = replace(
        cliente.tablero,
        html=html,
        headers=CABECERAS + ((b"content-security-policy", b"frame-ancestors 'self'"),),
    )
    respuesta = await pedir(app, token_staff(cfg, clave))
    assert respuesta.status_code == 200
    assert respuesta.content == html
    assert respuesta.headers["content-length"] == str(len(html))
    assert respuesta.headers.get_list("content-security-policy") == [
        "default-src 'none'",
        "frame-ancestors 'self'",
    ]


async def test_un_timeout_remoto_se_expone_como_504(entorno) -> None:
    cfg, clave, app, cliente = entorno
    cliente.error = ErrorAnalitica(timeout=True)
    respuesta = await pedir(app, token_staff(cfg, clave))
    assert respuesta.status_code == 504
    assert respuesta.json()["code"] == "http_504"
    assert respuesta.headers["cache-control"] == "no-store"


async def test_el_proxy_real_preserva_html_comprimido_y_solo_las_cabeceras_del_contrato(
    entorno,
) -> None:
    cfg, clave, app, _cliente = entorno
    token = token_staff(cfg, clave)
    pedidos: list[httpx.Request] = []
    html = "<html><body>Analítica: categorías y resolución</body></html>\r\n".encode()
    comprimido = gzip.compress(html)
    headers = list(CABECERAS) + [
        (b"content-security-policy", b"frame-ancestors 'self'"),
        (b"content-encoding", b"gzip"),
        (b"content-length", str(len(comprimido)).encode()),
        (b"set-cookie", b"sesion-remota=privada; Path=/; Secure; HttpOnly"),
        (b"authorization", b"Bearer privado"),
        (b"location", b"https://otro.example"),
    ]

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        return httpx.Response(200, content=comprimido, headers=headers)

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as remoto:
        app.state.analitica = AnaliticaClient("https://analitica.example", remoto)
        respuesta = await pedir(app, token)

    assert respuesta.status_code == 200
    assert respuesta.content == html
    assert respuesta.headers["content-length"] == str(len(html))
    assert respuesta.headers.get_list("content-security-policy") == [
        "default-src 'none'",
        "frame-ancestors 'self'",
    ]
    for nombre, valor in CABECERAS:
        assert valor.decode() in respuesta.headers.get_list(nombre.decode())
    assert not {"set-cookie", "content-encoding", "authorization", "location"} & set(
        respuesta.headers
    )
    assert len(pedidos) == 1
    assert pedidos[0].method == "GET"
    assert pedidos[0].url == "https://analitica.example/embed/reclamos"
    assert pedidos[0].headers["Authorization"] == f"Bearer {token}"
    assert pedidos[0].headers["Accept"] == "text/html"
    assert "X-Usuario-Token" not in pedidos[0].headers


@pytest.mark.parametrize(
    ("cache_control", "esperado"),
    [
        (None, ["no-store"]),
        ("", ["", "no-store"]),
        ("public, max-age=600", ["public, max-age=600", "no-store"]),
        ("no-cache", ["no-cache", "no-store"]),
        ('extension="private,no-store,other"', ['extension="private,no-store,other"', "no-store"]),
        ("private, No-Store", ["private, No-Store"]),
    ],
)
async def test_el_proxy_conserva_cache_control_y_agrega_no_store_si_hace_falta(
    entorno, cache_control: str | None, esperado: list[str]
) -> None:
    cfg, clave, app, _cliente = entorno
    headers = [(k, v) for k, v in CABECERAS if k != b"cache-control"]
    if cache_control is not None:
        headers.append((b"cache-control", cache_control.encode()))

    def responder(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>contenido privado</html>", headers=headers)

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as remoto:
        app.state.analitica = AnaliticaClient("https://analitica.example", remoto)
        respuesta = await pedir(app, token_staff(cfg, clave))

    assert respuesta.status_code == 200
    assert respuesta.headers.get_list("cache-control") == esperado
    assert respuesta.content == b"<html>contenido privado</html>"


@pytest.mark.parametrize(
    "omitidas",
    [
        {b"cache-control"},
        {b"content-security-policy"},
        {b"x-content-type-options"},
        {b"referrer-policy"},
        {k for k, _v in CABECERAS if k != b"content-type"},
    ],
)
async def test_el_proxy_acepta_html_sin_cabeceras_adicionales(
    entorno, omitidas: set[bytes]
) -> None:
    cfg, clave, app, _cliente = entorno
    headers = [(k, v) for k, v in CABECERAS if k not in omitidas]
    html = "<html>Analítica: resolución</html>".encode()

    def responder(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=html, headers=headers)

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as remoto:
        app.state.analitica = AnaliticaClient("https://analitica.example", remoto)
        respuesta = await pedir(app, token_staff(cfg, clave))

    assert respuesta.status_code == 200
    assert respuesta.content == html
    assert "no-store" in respuesta.headers["cache-control"]
    for nombre, valor in headers:
        assert respuesta.headers[nombre.decode()] == valor.decode()
    for nombre in omitidas - {b"cache-control"}:
        assert nombre.decode() not in respuesta.headers


async def test_no_duplica_no_store_en_cabeceras_cache_control_repetidas(entorno) -> None:
    cfg, clave, app, cliente = entorno
    cliente.tablero = replace(
        cliente.tablero,
        headers=tuple((k, v) for k, v in CABECERAS if k != b"cache-control")
        + ((b"cache-control", b"private"), (b"cache-control", b"no-store")),
    )
    respuesta = await pedir(app, token_staff(cfg, clave))
    assert respuesta.status_code == 200
    assert respuesta.headers.get_list("cache-control") == ["private", "no-store"]


async def test_dos_administradores_concurrentes_reciben_su_propio_tablero(entorno) -> None:
    cfg, clave, app, _cliente = entorno
    tokens = [token_staff(cfg, clave, sub=f"admin-{i}") for i in range(3)]
    html_por_token = {
        f"Bearer {token}": f"<html>Tablero {i}</html>".encode() for i, token in enumerate(tokens)
    }

    async def responder(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0)
        return httpx.Response(
            200, content=html_por_token[request.headers["Authorization"]], headers=CABECERAS
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as remoto:
        app.state.analitica = AnaliticaClient("https://analitica.example", remoto)
        respuestas = await asyncio.gather(*(pedir(app, token) for token in tokens))

    assert all(respuesta.status_code == 200 for respuesta in respuestas)
    assert [respuesta.content for respuesta in respuestas] == list(html_por_token.values())


async def test_error_del_upstream_no_filtra_el_jwt_humano(entorno, caplog) -> None:
    cfg, clave, app, cliente = entorno
    token = token_staff(cfg, clave)
    cliente.error = ErrorAnalitica()
    respuesta = await pedir(app, token)
    assert respuesta.status_code == 502
    assert token not in respuesta.text
    assert token not in caplog.text


def test_ruta_no_se_monta_por_defecto() -> None:
    from app.main import app

    assert RUTA not in app.openapi()["paths"]


def test_configuracion_no_habilita_analitica_sin_identidad_federada() -> None:
    assert not Settings().analitica_enabled
    with pytest.raises(ValueError, match="AUTH_ENABLED=true y JWT_ALGORITHM=RS256"):
        Settings(analitica_enabled=True, analitica_url="https://analitica.example")


@pytest.mark.parametrize(
    ("cambio", "error"),
    [
        ({"analitica_url": "http://analitica.example"}, "ANALITICA_URL"),
        ({"analitica_url": None}, "ANALITICA_URL"),
        ({"auth_enabled": False}, "AUTH_ENABLED"),
        ({"jwt_jwks_url": None}, "JWKS"),
        ({"jwt_staff_grupos_admin": []}, "grupo ADMIN"),
        ({"analitica_timeout_seconds": 0}, "analitica_timeout_seconds"),
    ],
)
def test_configuracion_invalida_falla_cerrada(entorno, cambio: dict, error: str) -> None:
    cfg, _clave, _app, _cliente = entorno
    with pytest.raises(ValueError, match=error):
        Settings(**(cfg.model_dump() | cambio))


def test_analitica_no_requiere_las_credenciales_del_gateway(entorno) -> None:
    cfg, _clave, _app, _cliente = entorno
    sin_gateway = Settings(
        **(
            cfg.model_dump()
            | {
                "gateway_enabled": False,
                "gateway_token_url": "",
                "gateway_client_id": "",
                "gateway_client_secret": "",
            }
        )
    )
    assert sin_gateway.analitica_enabled is True


async def test_lifespan_inicia_y_cierra_el_cliente_de_analitica(entorno, monkeypatch) -> None:
    cfg, _clave, _app, _cliente = entorno
    main = import_module("app.main")
    eventos: list[str] = []

    class RecursoFalso:
        async def start(self) -> None:
            eventos.append("start")

        async def stop(self) -> None:
            eventos.append("stop")

    async def cerrar_engine() -> None:
        eventos.append("engine.stop")

    monkeypatch.setattr(main, "settings", cfg)
    monkeypatch.setattr(main, "setup_logging", lambda: None)
    monkeypatch.setattr(main, "crear_publisher", RecursoFalso)
    monkeypatch.setattr(main, "AnaliticaClient", lambda *_args, **_kwargs: RecursoFalso())
    monkeypatch.setattr(main, "cerrar_engine", cerrar_engine)
    app = FastAPI()

    async with main.lifespan(app):
        assert app.state.publisher is not app.state.analitica
        assert eventos == ["start", "start"]
    assert eventos == ["start", "start", "stop", "stop", "engine.stop"]
