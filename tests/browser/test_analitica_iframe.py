"""Real HTTPS navigation in browsers; external systems alone are simulated.

Install the browser extra and run playwright install chromium firefox first.
"""

from __future__ import annotations

import asyncio
import socket
import sys
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.responses import HTMLResponse

from app.api.v1.analitica_sesion import COOKIE, RUTA
from tests.analitica_helpers import firmar
from tests.analitica_session_helpers import aplicacion_sesion

playwright = pytest.importorskip("playwright.async_api")


@pytest_asyncio.fixture
async def servidor(engine, monkeypatch, tmp_path):
    app, cfg, clave = aplicacion_sesion(engine, monkeypatch)

    @app.get("/harness", response_class=HTMLResponse)
    async def pagina():
        return "<html><body><div id='host'>Principal</div></body></html>"

    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "localhost")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre)
        .issuer_name(nombre)
        .public_key(privada.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(privada, hashes.SHA256())
    )
    pem, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key.write_bytes(
        privada.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    origen = f"https://localhost:{sock.getsockname()[1]}"
    cfg.analitica_frontend_origins = [origen]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            ssl_certfile=str(pem),
            ssl_keyfile=str(key),
            access_log=False,
            log_level="error",
            lifespan="off",
        )
    )
    tarea = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                await asyncio.sleep(0.01)
        yield origen, cfg, clave, app
    finally:
        server.should_exit = True
        await asyncio.wait_for(tarea, 10)
        sock.close()


@pytest.mark.parametrize(
    "navegador",
    [
        "chromium",
        "firefox",
        pytest.param(
            "webkit",
            marks=pytest.mark.xfail(
                sys.platform == "win32",
                strict=True,
                reason="Playwright CO-006: Windows WebKit reports SameSite=None for Strict",
            ),
        ),
    ],
)
async def test_iframe_real_con_cookie_strict_y_sandbox(servidor, navegador):
    origen, cfg, clave, app = servidor
    async with playwright.async_playwright() as pw:
        browser = await getattr(pw, navegador).launch(headless=True)
        try:
            context = await browser.new_context(ignore_https_errors=True)
            page = await context.new_page()
            await page.goto(origen + "/harness")

            async def iniciar(**claims):
                token = firmar(cfg, clave, **claims)
                return await page.evaluate(
                    """async ([ruta, token]) => {
                    const r = await fetch(ruta+'/sesion', {method:'POST',
                        headers:{'Content-Type':'application/json', Authorization:'Bearer '+token},
                        body:'{}'});
                    return {status:r.status, data:await r.json()};
                }""",
                    [RUTA, token],
                )

            inicio = await iniciar()
            assert inicio["status"] == 200
            cookies = await context.cookies()
            cookie = next(c for c in cookies if c["name"] == COOKIE)
            assert cookie["domain"] == "localhost" and cookie["path"] == RUTA
            assert cookie["httpOnly"] and cookie["secure"] and cookie["sameSite"] == "Strict"
            assert COOKIE not in await page.evaluate("document.cookie")

            async def montar():
                await page.evaluate(
                    """ruta => {
                    document.querySelector('iframe')?.remove();
                    const f=document.createElement('iframe');f.sandbox='allow-scripts';
                    f.src=ruta;document.body.append(f);
                }""",
                    RUTA,
                )
                frame = page.frame_locator("iframe")
                await frame.locator("#ok").wait_for(timeout=10000)
                assert await frame.locator("body").evaluate("() => window.aislado")
                return frame

            await montar()
            await montar()
            assert await page.locator("iframe").get_attribute("sandbox") == "allow-scripts"
            primero = cookie["value"]
            cambio = await iniciar(sub="admin-B")
            assert cambio["status"] == 200
            assert (
                next(c for c in await context.cookies() if c["name"] == COOKIE)["value"] != primero
            )
            await montar()
            salida = await page.evaluate(
                """async ([ruta,csrf]) => (await fetch(ruta+'/sesion',
                {method:'DELETE',headers:{'X-CSRF-Token':csrf}})).status""",
                [RUTA, cambio["data"]["csrf_token"]],
            )
            assert salida == 200
            assert not any(c["name"] == COOKIE for c in await context.cookies())
            contenido = await page.content()
            assert all(token not in contenido for token in app.state.analitica.tokens)
            await context.add_cookies([cookie])
            async with page.expect_response(lambda r: r.url == origen + RUTA) as fallida:
                await page.evaluate(
                    """ruta => {document.querySelector('iframe').src=ruta;}""", RUTA
                )
            assert (await fallida.value).status == 401
            await context.clear_cookies()
            cfg.analitica_session_ttl_seconds = 2
            assert (await iniciar())["status"] == 200
            await asyncio.sleep(2.1)
            async with page.expect_response(lambda r: r.url == origen + RUTA) as vencida:
                await page.evaluate(
                    """ruta => {document.querySelector('iframe').src=ruta;}""", RUTA
                )
            assert (await vencida.value).status == 401
            await context.close()
        finally:
            await browser.close()
