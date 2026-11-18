"""Unit tests for the Analytics HTTP client, without external services."""

from __future__ import annotations

import asyncio
import gzip
from collections.abc import Awaitable, Callable

import httpx
import pytest

from app.integrations.analitica import AnaliticaClient, ErrorAnalitica

CABECERAS = {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "no-store, private",
    "Content-Security-Policy": "default-src 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
HTML = "<!doctype html><html><body>Analítica: resolución y categorías</body></html>".encode()
Responder = Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]]


def _cliente(responder: Responder, *, timeout_seconds: float = 10.0) -> AnaliticaClient:
    # Enabled on the injected client to verify the integration overrides it.
    http = httpx.AsyncClient(transport=httpx.MockTransport(responder), follow_redirects=True)
    return AnaliticaClient(
        "https://analitica.example/",
        http,
        timeout_seconds=timeout_seconds,
    )


async def test_envia_solo_el_bearer_humano_y_no_cachea_el_html() -> None:
    pedidos: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        return httpx.Response(200, content=HTML + str(len(pedidos)).encode(), headers=CABECERAS)

    client = _cliente(responder)
    primero = await client.obtener_tablero("usuario-1")
    segundo = await client.obtener_tablero("usuario-2")

    assert len(pedidos) == 2
    assert all(p.method == "GET" for p in pedidos)
    assert all(p.url == "https://analitica.example/embed/reclamos" for p in pedidos)
    assert all(p.content == b"" for p in pedidos)
    assert all(p.headers["Accept"] == "text/html" for p in pedidos)
    assert all("X-Usuario-Token" not in p.headers for p in pedidos)
    assert [p.headers["Authorization"] for p in pedidos] == ["Bearer usuario-1", "Bearer usuario-2"]
    assert primero.html == HTML + b"1"
    assert segundo.html == HTML + b"2"
    assert dict(httpx.Headers(primero.headers)) == {k.lower(): v for k, v in CABECERAS.items()}


async def test_conserva_bytes_y_politicas_repetidas_sin_reenviar_otras_cabeceras() -> None:
    # A BOM and CRLF must survive without decoding and re-encoding the document.
    html = b"\xef\xbb\xbf" + HTML + b"\r\n"
    headers = list(CABECERAS.items()) + [
        ("Content-Security-Policy", "frame-ancestors 'self'"),
        ("Set-Cookie", "sesion-remota=privada; Secure; HttpOnly"),
        ("Location", "https://otro.example"),
        ("Authorization", "Bearer privado"),
        ("X-Usuario-Token", "privado"),
    ]
    remoto = httpx.Response(200, content=html, headers=headers)
    tablero = await _cliente(lambda _request: remoto).obtener_tablero("usuario")

    assert tablero.html == html
    assert tablero.headers == tuple(
        (nombre.lower(), valor)
        for nombre, valor in remoto.headers.raw
        if nombre.lower() in {k.lower().encode() for k in CABECERAS}
    )
    assert httpx.Headers(tablero.headers).get_list("Content-Security-Policy") == [
        "default-src 'none'",
        "frame-ancestors 'self'",
    ]


async def test_el_cuerpo_descomprimido_no_arrastra_cabeceras_de_transporte() -> None:
    remoto = httpx.Response(
        200,
        content=gzip.compress(HTML),
        headers=CABECERAS | {"Content-Encoding": "gzip"},
    )
    tablero = await _cliente(lambda _request: remoto).obtener_tablero("usuario")

    assert tablero.html == HTML
    assert "content-encoding" not in httpx.Headers(tablero.headers)
    assert "content-length" not in httpx.Headers(tablero.headers)


@pytest.mark.parametrize(
    "status", [204, 301, 302, 303, 307, 308, 400, 401, 403, 404, 429, 500, 503]
)
async def test_no_reintenta_ni_sigue_redirecciones_ni_expone_errores(status: int) -> None:
    pedidos: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        return httpx.Response(
            status,
            text="detalle privado jwt-humano-privado",
            headers={"Location": "https://otro.example/"},
        )

    with pytest.raises(ErrorAnalitica) as error:
        await _cliente(responder).obtener_tablero("jwt-humano-privado")

    assert error.value.status_code == status
    assert error.value.timeout is False
    assert "privado" not in str(error.value)
    assert len(pedidos) == 1


@pytest.mark.parametrize("content_type", ["application/json", "text/plain", "image/svg+xml"])
async def test_rechaza_respuesta_que_no_es_html(content_type: str) -> None:
    remoto = httpx.Response(200, content=HTML, headers=CABECERAS | {"Content-Type": content_type})
    with pytest.raises(ErrorAnalitica):
        await _cliente(lambda _request: remoto).obtener_tablero("usuario")


@pytest.mark.parametrize("cabecera", [k for k in CABECERAS if k != "Content-Type"])
async def test_acepta_html_sin_cabeceras_adicionales(cabecera: str) -> None:
    headers = {k: v for k, v in CABECERAS.items() if k != cabecera}
    remoto = httpx.Response(200, content=HTML, headers=headers)
    tablero = await _cliente(lambda _request: remoto).obtener_tablero("usuario")
    assert tablero.html == HTML
    assert cabecera not in httpx.Headers(tablero.headers)


async def test_rechaza_respuesta_sin_content_type_html() -> None:
    remoto = httpx.Response(200, content=HTML)
    with pytest.raises(ErrorAnalitica):
        await _cliente(lambda _request: remoto).obtener_tablero("usuario")


@pytest.mark.parametrize(
    "cache_control",
    ["public, max-age=600", "no-cache", "x-no-store", 'extension="private,no-store,other"', ""],
)
async def test_acepta_html_sin_directiva_no_store(cache_control: str) -> None:
    remoto = httpx.Response(200, content=HTML, headers=CABECERAS | {"Cache-Control": cache_control})
    tablero = await _cliente(lambda _request: remoto).obtener_tablero("usuario")
    assert tablero.html == HTML
    assert httpx.Headers(tablero.headers)["cache-control"] == cache_control


@pytest.mark.parametrize("cabecera", [k for k in CABECERAS if k != "Content-Type"])
async def test_conserva_cabeceras_adicionales_con_valor_vacio(cabecera: str) -> None:
    remoto = httpx.Response(200, content=HTML, headers=CABECERAS | {cabecera: " "})
    tablero = await _cliente(lambda _request: remoto).obtener_tablero("usuario")
    assert tablero.html == HTML
    assert httpx.Headers(tablero.headers)[cabecera] == " "


async def test_conserva_los_valores_originales_de_las_cabeceras() -> None:
    headers = CABECERAS | {
        "Content-Type": "Text/HTML; charset=UTF-8",
        "Cache-Control": "private, No-Store",
        "Referrer-Policy": "strict-origin-when-cross-origin",
    }
    remoto = httpx.Response(200, content=HTML, headers=headers)
    tablero = await _cliente(lambda _request: remoto).obtener_tablero("usuario")
    assert dict(httpx.Headers(tablero.headers)) == {k.lower(): v for k, v in headers.items()}


@pytest.mark.parametrize(
    "error_http", [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout]
)
async def test_identifica_los_timeouts_sin_filtrar_detalles(
    error_http: type[httpx.TimeoutException],
) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        raise error_http("jwt-humano-privado", request=request)

    with pytest.raises(ErrorAnalitica) as error:
        await _cliente(responder).obtener_tablero("jwt-humano-privado")

    assert error.value.timeout is True
    assert error.value.status_code is None
    assert "jwt-humano-privado" not in str(error.value)


async def test_limita_el_tiempo_total_aunque_el_transporte_no_aplique_timeout() -> None:
    async def responder(_request: httpx.Request) -> httpx.Response:
        await asyncio.Event().wait()
        raise AssertionError("The total deadline must interrupt this request")

    with pytest.raises(ErrorAnalitica) as error:
        await _cliente(responder, timeout_seconds=0.01).obtener_tablero("usuario")
    assert error.value.timeout is True


async def test_fallo_de_red_al_pedir_html_no_filtra_tokens() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("jwt-humano-privado", request=request)

    with pytest.raises(ErrorAnalitica) as error:
        await _cliente(responder).obtener_tablero("jwt-humano-privado")
    assert error.value.timeout is False
    assert error.value.status_code is None
    assert "jwt-humano-privado" not in str(error.value)


async def test_pedidos_concurrentes_conservan_el_token_y_html_de_cada_usuario() -> None:
    pedidos: list[httpx.Request] = []

    async def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        await asyncio.sleep(0)
        numero = request.headers["Authorization"].removeprefix("Bearer usuario-")
        return httpx.Response(200, content=HTML + numero.encode(), headers=CABECERAS)

    client = _cliente(responder)
    tableros = await asyncio.gather(*(client.obtener_tablero(f"usuario-{i}") for i in range(5)))

    assert len(pedidos) == 5
    assert all(p.method == "GET" and p.url.path == "/embed/reclamos" for p in pedidos)
    assert [tablero.html for tablero in tableros] == [HTML + str(i).encode() for i in range(5)]
    assert all("X-Usuario-Token" not in p.headers for p in pedidos)


async def test_no_reutiliza_cookies_remotas_entre_usuarios() -> None:
    pedidos: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        return httpx.Response(
            200, content=HTML, headers=CABECERAS | {"Set-Cookie": "sesion-remota=usuario-1; Path=/"}
        )

    client = _cliente(responder)
    await client.obtener_tablero("usuario-1")
    await client.obtener_tablero("usuario-2")

    assert len(pedidos) == 2
    assert all("Cookie" not in p.headers for p in pedidos)


async def test_timeout_configurado_se_aplica_a_la_llamada_http() -> None:
    pedidos: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        return httpx.Response(200, content=HTML, headers=CABECERAS)

    await _cliente(responder, timeout_seconds=2.5).obtener_tablero("usuario")
    assert len(pedidos) == 1
    assert pedidos[0].extensions["timeout"] == dict.fromkeys(
        ["connect", "read", "write", "pool"], 2.5
    )


async def test_la_cancelacion_del_pedido_no_se_convierte_en_error_remoto() -> None:
    iniciado = asyncio.Event()

    async def responder(_request: httpx.Request) -> httpx.Response:
        iniciado.set()
        await asyncio.Event().wait()
        raise AssertionError("The caller must cancel this request")

    tarea = asyncio.create_task(_cliente(responder).obtener_tablero("usuario"))
    await asyncio.wait_for(iniciado.wait(), timeout=1)
    tarea.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarea


async def test_cierra_su_cliente_http_al_terminar_y_puede_reiniciarse() -> None:
    client = AnaliticaClient("https://analitica.example")
    await client.stop()
    with pytest.raises(RuntimeError, match="no fue inicializado"):
        await client.obtener_tablero("usuario")

    await client.start()
    http = client._client
    assert http is not None and not http.is_closed
    await client.start()
    assert client._client is http
    await client.stop()
    assert http.is_closed
    assert client._client is None

    await client.start()
    assert client._client is not http
    await client.stop()


async def test_no_cierra_un_cliente_http_inyectado_por_el_llamador() -> None:
    async with httpx.AsyncClient() as http:
        client = AnaliticaClient("https://analitica.example", http)
        await client.start()
        await client.stop()
        assert not http.is_closed
