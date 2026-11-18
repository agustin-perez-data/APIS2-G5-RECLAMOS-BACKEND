"""HTTP session controls, including origin, CSRF and credential precedence."""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.analitica_sesion import COOKIE, RUTA
from tests.analitica_helpers import firmar
from tests.analitica_session_helpers import aplicacion_sesion

NAV = {"sec-fetch-site": "same-origin", "sec-fetch-dest": "iframe", "sec-fetch-mode": "navigate"}


@pytest.fixture
async def entorno(engine, monkeypatch):
    app, cfg, clave = aplicacion_sesion(engine, monkeypatch)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://localhost"
    ) as client:
        yield client, cfg, clave, app


async def iniciar(client, cfg, clave, **claims):
    return await client.post(
        RUTA + "/sesion",
        json={},
        headers={
            "Origin": "https://localhost",
            "Authorization": "Bearer " + firmar(cfg, clave, **claims),
        },
    )


async def test_ciclo_cookie_estado_rotacion_logout(entorno):
    client, cfg, clave, app = entorno
    inicio = await iniciar(client, cfg, clave)
    assert inicio.status_code == 200
    cookie = inicio.headers["set-cookie"]
    for atributo in ["Secure", "HttpOnly", "SameSite=Strict", "Path=" + RUTA]:
        assert atributo in cookie
    assert "Domain=" not in cookie
    identificador = client.cookies[COOKIE]
    assert identificador not in inicio.text
    assert (await client.get(RUTA, headers=NAV)).status_code == 200
    assert (await client.get(RUTA)).status_code == 403
    assert (
        await client.get(RUTA, headers=NAV | {"Authorization": "Bearer invalido"})
    ).status_code == 401
    estado = await client.get(
        RUTA + "/sesion", headers={"Authorization": "Bearer " + firmar(cfg, clave)}
    )
    assert estado.status_code == 200
    assert "csrf_token" not in estado.json()
    assert (
        await client.delete(RUTA + "/sesion", headers={"Origin": "https://localhost"})
    ).status_code == 403
    salida = await client.delete(
        RUTA + "/sesion",
        headers={"Origin": "https://localhost", "X-CSRF-Token": inicio.json()["csrf_token"]},
    )
    assert salida.status_code == 200
    client.cookies.set(COOKIE, identificador, domain="localhost.local", path=RUTA)
    assert (await client.get(RUTA, headers=NAV)).status_code == 401


@pytest.mark.parametrize("origen", [None, "null", "https://localhost.evil", "https://otro.example"])
async def test_rechaza_origen_invalido(entorno, origen):
    client, cfg, clave, _ = entorno
    headers = {"Authorization": "Bearer " + firmar(cfg, clave)}
    if origen:
        headers["Origin"] = origen
    assert (await client.post(RUTA + "/sesion", json={}, headers=headers)).status_code == 403


async def test_cambio_de_usuario_e_inicializacion_fallida_invalidan_la_anterior(entorno):
    client, cfg, clave, _ = entorno
    await iniciar(client, cfg, clave)
    anterior = client.cookies[COOKIE]
    assert (await iniciar(client, cfg, clave, sub="admin-B")).status_code == 200
    assert client.cookies[COOKIE] != anterior
    assert (await iniciar(client, cfg, clave, groups=["reclamos-operadores"])).status_code == 403
    assert COOKIE not in client.cookies
    assert (await client.get(RUTA, headers=NAV)).status_code == 401


@pytest.mark.parametrize("cabecera", ["Basic invalido", "Bearer invalido", "", "Bearer "])
async def test_bearer_explicito_no_hace_fallback_a_cookie(entorno, cabecera):
    client, cfg, clave, _ = entorno
    await iniciar(client, cfg, clave)
    assert (await client.get(RUTA, headers=NAV | {"Authorization": cabecera})).status_code == 401


async def test_estado_de_otro_usuario_y_cookies_ambiguas_no_son_aceptados(entorno):
    client, cfg, clave, _ = entorno
    await iniciar(client, cfg, clave)
    otro = firmar(cfg, clave, sub="admin-B")
    assert (
        await client.get(RUTA + "/sesion", headers={"Authorization": "Bearer " + otro})
    ).status_code == 409
    valor = client.cookies[COOKIE]
    assert (
        await client.get(RUTA, headers=NAV | {"Cookie": f"{COOKIE}={valor}; {COOKIE}={valor}"})
    ).status_code == 400


@pytest.mark.parametrize("site", ["cross-site", "same-site", "none"])
async def test_fetch_metadata_no_permite_iframe_desde_otro_origen(entorno, site):
    client, cfg, clave, _ = entorno
    await iniciar(client, cfg, clave)
    assert (await client.get(RUTA, headers=NAV | {"Sec-Fetch-Site": site})).status_code == 403


async def test_concurrencia_aisla_los_navegadores_y_sus_tokens(entorno):
    from contextlib import AsyncExitStack
    from dataclasses import replace

    import jwt

    _client, cfg, clave, app = entorno
    original = app.state.analitica.obtener_tablero

    async def tablero(token):
        # The real API validated this token before reaching the fake remote.
        sub = jwt.decode(token, options={"verify_signature": False})["sub"]
        await asyncio.sleep(0)
        return replace(await original(token), html=f"<html>{sub}</html>".encode())

    app.state.analitica.obtener_tablero = tablero
    async with AsyncExitStack() as stack:
        clientes = [
            await stack.enter_async_context(
                AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost")
            )
            for _ in range(3)
        ]
        for i, http in enumerate(clientes):
            assert (await iniciar(http, cfg, clave, sub=f"admin-{i}")).status_code == 200
        assert len({http.cookies[COOKIE] for http in clientes}) == 3
        respuestas = await asyncio.gather(*(http.get(RUTA, headers=NAV) for http in clientes))
        assert [r.content for r in respuestas] == [
            f"<html>admin-{i}</html>".encode() for i in range(3)
        ]


async def test_revocacion_durante_consulta_impide_entregar_el_documento(entorno, engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.sesion_analitica_service import SesionAnaliticaService

    client, cfg, clave, app = entorno
    await iniciar(client, cfg, clave)
    identificador = client.cookies[COOKIE]
    original = app.state.analitica.obtener_tablero

    async def revocar_antes_de_responder(token):
        async with async_sessionmaker(engine)() as session:
            await SesionAnaliticaService(session, cfg).revocar(identificador)
        return await original(token)

    app.state.analitica.obtener_tablero = revocar_antes_de_responder
    respuesta = await client.get(RUTA, headers=NAV)
    assert respuesta.status_code == 401
    assert "Tablero" not in respuesta.text


async def test_cookie_malformada_y_jwt_vencido_no_dan_acceso(entorno):
    client, cfg, clave, _ = entorno
    client.cookies.set(COOKIE, "invalida", domain="localhost.local", path=RUTA)
    assert (await client.get(RUTA, headers=NAV)).status_code == 401
    await iniciar(client, cfg, clave)
    assert (
        await client.get(
            RUTA, headers=NAV | {"Authorization": "Bearer " + firmar(cfg, clave, exp=1)}
        )
    ).status_code == 401


async def test_lifespan_arranca_y_cancela_la_limpieza(monkeypatch):
    from fastapi import FastAPI

    from app import main
    from app.events.producer import InMemoryEventPublisher
    from app.services import limpieza_analitica
    from tests.analitica_helpers import entorno_federado

    cfg, _ = entorno_federado(monkeypatch)
    iniciado, cancelado = asyncio.Event(), asyncio.Event()

    async def ciclo(_cfg):
        iniciado.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelado.set()

    monkeypatch.setattr(main, "settings", cfg)
    monkeypatch.setattr(main, "setup_logging", lambda: None)
    monkeypatch.setattr(main, "crear_publisher", InMemoryEventPublisher)
    monkeypatch.setattr(limpieza_analitica, "limpiar_sesiones_periodicamente", ciclo)
    async with main.lifespan(FastAPI()):
        await asyncio.wait_for(iniciado.wait(), timeout=2)
    assert cancelado.is_set()


async def test_limpieza_periodica_es_cancelable_y_sobrevive_fallos(monkeypatch):
    from app.services import limpieza_analitica as modulo
    from tests.analitica_helpers import entorno_federado

    cfg, _ = entorno_federado(monkeypatch)
    pasadas = asyncio.Event()

    class Servicio:
        def __init__(self, *_args):
            pass

        async def limpiar_expiradas(self):
            pasadas.set()
            raise RuntimeError("No debe filtrarse")

    monkeypatch.setattr(modulo, "SesionAnaliticaService", Servicio)
    tarea = asyncio.create_task(modulo.limpiar_sesiones_periodicamente(cfg, intervalo=0.01))
    await asyncio.wait_for(pasadas.wait(), timeout=2)
    tarea.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarea
