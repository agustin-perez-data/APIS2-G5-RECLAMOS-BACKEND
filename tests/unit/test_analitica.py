"""Unit tests for the Analytics HTTP client, without external services."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core.config import Settings
from app.integrations.analitica import AnaliticaClient, ErrorAnalitica


def _config() -> Settings:
    return Settings(
        gateway_token_url="https://login.example/oauth/token",
        gateway_client_id="grupo4",
        gateway_client_secret="secreto-de-test",
    )


def _cliente(responder, *, timeout_seconds: float = 10.0) -> AnaliticaClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    return AnaliticaClient(
        "https://analitica.example/",
        _config(),
        http,
        timeout_seconds=timeout_seconds,
    )


async def test_pide_token_con_credenciales_existentes_y_reutiliza_la_cache() -> None:
    pedidos: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "servicio-1", "expires_in": 900})
        return httpx.Response(
            200,
            text="<html>tablero</html>",
            headers={
                "Content-Type": "text/html; charset=utf-8",
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'",
            },
        )

    client = _cliente(responder)
    primero = await client.obtener_tablero("usuario-1")
    segundo = await client.obtener_tablero("usuario-2")

    tokens = [p for p in pedidos if p.url.path == "/oauth/token"]
    tableros = [p for p in pedidos if p.url.path == "/embed/reclamos"]
    assert len(tokens) == 1
    assert tokens[0].method == "POST"
    assert tokens[0].content == b"grant_type=client_credentials"
    assert tokens[0].headers["Authorization"] == "Basic Z3J1cG80OnNlY3JldG8tZGUtdGVzdA=="
    assert len(tableros) == 2
    assert all(p.url == "https://analitica.example/embed/reclamos" for p in tableros)
    assert all(p.headers["Authorization"] == "Bearer servicio-1" for p in tableros)
    assert [p.headers["X-Usuario-Token"] for p in tableros] == ["usuario-1", "usuario-2"]
    assert primero.html == segundo.html == "<html>tablero</html>"
    assert primero.content_type == "text/html; charset=utf-8"
    assert primero.cache_control == "no-store"
    assert primero.content_security_policy == "default-src 'none'"


async def test_renueva_el_token_antes_del_vencimiento() -> None:
    tokens = 0

    def responder(request: httpx.Request) -> httpx.Response:
        nonlocal tokens
        if request.url.path == "/oauth/token":
            tokens += 1
            return httpx.Response(200, json={"access_token": f"servicio-{tokens}"})
        return httpx.Response(200, text="<html></html>", headers={"Content-Type": "text/html"})

    client = _cliente(responder)
    await client.obtener_tablero("usuario")
    client._token_vence = 0
    await client.obtener_tablero("usuario")
    assert tokens == 2


async def test_un_401_de_analitica_invalida_el_token_para_el_siguiente_pedido() -> None:
    tokens = 0

    def responder(request: httpx.Request) -> httpx.Response:
        nonlocal tokens
        if request.url.path == "/oauth/token":
            tokens += 1
            return httpx.Response(200, json={"access_token": f"servicio-{tokens}"})
        if tokens == 1:
            return httpx.Response(401, text="detalle privado")
        return httpx.Response(200, text="<html></html>", headers={"Content-Type": "text/html"})

    client = _cliente(responder)
    with pytest.raises(ErrorAnalitica) as error:
        await client.obtener_tablero("usuario")
    assert error.value.status_code == 401
    assert "detalle privado" not in str(error.value)
    await client.obtener_tablero("usuario")
    assert tokens == 2


@pytest.mark.parametrize("status", [302, 403, 503])
async def test_no_sigue_redirecciones_ni_expone_errores_externos(status: int) -> None:
    pedidos: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "servicio"})
        return httpx.Response(status, text="detalle privado", headers={"Location": "/otro"})

    client = _cliente(responder)
    with pytest.raises(ErrorAnalitica) as error:
        await client.obtener_tablero("usuario")
    assert error.value.status_code == status
    assert "detalle privado" not in str(error.value)
    assert len(pedidos) == 2


async def test_rechaza_respuesta_que_no_es_html() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "servicio"})
        return httpx.Response(200, json={"error": "inesperado"})

    with pytest.raises(ErrorAnalitica):
        await _cliente(responder).obtener_tablero("usuario")


async def test_timeout_de_analitica_y_falla_del_idp() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "servicio"})
        raise httpx.ReadTimeout("demora", request=request)

    with pytest.raises(ErrorAnalitica):
        await _cliente(timeout).obtener_tablero("usuario")

    def idp_caido(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="detalle privado")

    with pytest.raises(ErrorAnalitica) as error:
        await _cliente(idp_caido).obtener_tablero("usuario")
    assert error.value.status_code is None
    assert "detalle privado" not in str(error.value)


async def test_pedidos_concurrentes_comparten_una_sola_obtencion_de_token() -> None:
    tokens = 0

    async def responder(request: httpx.Request) -> httpx.Response:
        nonlocal tokens
        if request.url.path == "/oauth/token":
            tokens += 1
            await asyncio.sleep(0)
            return httpx.Response(200, json={"access_token": "servicio"})
        return httpx.Response(200, text="<html></html>", headers={"Content-Type": "text/html"})

    client = _cliente(responder)
    await asyncio.gather(*(client.obtener_tablero(f"usuario-{i}") for i in range(5)))
    assert tokens == 1


@pytest.mark.parametrize(
    "respuesta_token",
    [
        httpx.Response(302, headers={"Location": "https://otro.example/oauth/token"}),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"access_token": "servicio", "expires_in": 0}),
        httpx.Response(200, text="respuesta inesperada"),
    ],
)
async def test_token_de_servicio_invalido_no_llega_a_analitica(
    respuesta_token: httpx.Response,
) -> None:
    pedidos: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        return respuesta_token

    with pytest.raises(ErrorAnalitica) as error:
        await _cliente(responder).obtener_tablero("jwt-humano-privado")
    assert error.value.status_code is None
    assert "jwt-humano-privado" not in str(error.value)
    assert [pedido.url.path for pedido in pedidos] == ["/oauth/token"]


async def test_fallo_de_red_al_pedir_html_no_filtra_tokens() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "jwt-servicio-privado"})
        raise httpx.ConnectError("sin conexion", request=request)

    with pytest.raises(ErrorAnalitica) as error:
        await _cliente(responder).obtener_tablero("jwt-humano-privado")
    assert "jwt-humano-privado" not in str(error.value)
    assert "jwt-servicio-privado" not in str(error.value)


async def test_timeout_configurado_se_aplica_a_las_dos_llamadas() -> None:
    pedidos: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "servicio"})
        return httpx.Response(200, text="<html></html>", headers={"Content-Type": "text/html"})

    await _cliente(responder, timeout_seconds=2.5).obtener_tablero("usuario")
    assert len(pedidos) == 2
    assert all(pedido.extensions["timeout"]["read"] == 2.5 for pedido in pedidos)


async def test_cierra_su_cliente_http_al_terminar() -> None:
    client = AnaliticaClient("https://analitica.example", _config())
    await client.start()
    http = client._client
    assert http is not None and not http.is_closed
    await client.stop()
    assert http.is_closed
    assert client._client is None
