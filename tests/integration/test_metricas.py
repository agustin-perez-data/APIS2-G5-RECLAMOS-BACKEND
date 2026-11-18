"""Operational metrics: who can read them and what they count.

The counters are global to the process and other tests move them too, so every
assertion here compares a value before and after, never an absolute number.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.metrics import (
    EVENTOS_PUBLICADOS,
    EVENTOS_RECIBIDOS,
    PEDIDOS,
    RUTA_DESCONOCIDA,
    plantilla_de_ruta,
)
from app.events import topics
from app.events.gateway import GatewayEventPublisher
from tests.unit.test_gateway import _config, sobre_creado

TOKEN_WEBHOOK = "secreto-webhook"


def _pedidos(metodo: str, ruta: str, estado: int) -> float:
    return PEDIDOS.labels(metodo, ruta, str(estado))._value.get()


def _publicados(tipo: str, resultado: str) -> float:
    return EVENTOS_PUBLICADOS.labels(tipo, resultado)._value.get()


def _recibidos(topic: str, resultado: str) -> float:
    return EVENTOS_RECIBIDOS.labels(topic, resultado)._value.get()


# --- Access ----------------------------------------------------------------------


async def test_las_metricas_piden_identidad(client: AsyncClient) -> None:
    respuesta = await client.get("/metrics")

    assert respuesta.status_code == 401


@pytest.mark.parametrize("quien", ["token_ciudadano", "token_operador"])
async def test_las_metricas_son_solo_para_administradores(
    client: AsyncClient, auth, quien: str, request: pytest.FixtureRequest
) -> None:
    respuesta = await client.get("/metrics", headers=auth(request.getfixturevalue(quien)))

    assert respuesta.status_code == 403


async def test_un_administrador_las_lee_en_formato_prometheus(
    client: AsyncClient, auth, token_admin: str
) -> None:
    respuesta = await client.get("/metrics", headers=auth(token_admin))

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/plain")
    cuerpo = respuesta.text
    assert "# TYPE reclamos_http_requests_total counter" in cuerpo
    assert "# TYPE reclamos_http_request_duration_seconds histogram" in cuerpo
    assert "# TYPE reclamos_eventos_publicados_total counter" in cuerpo
    assert "# TYPE reclamos_eventos_recibidos_total counter" in cuerpo
    assert 'reclamos_build_info{environment="test"' in cuerpo


# --- HTTP requests ---------------------------------------------------------------


async def test_cuenta_los_pedidos_por_plantilla_de_ruta_y_no_por_url(
    client: AsyncClient, auth, token_operador: str
) -> None:
    """Two different ids must land on the same series, or the registry would
    grow with every claim that is ever looked up."""
    plantilla = f"{settings.api_v1_prefix}/reclamos/{{reclamo_id}}"
    antes = _pedidos("GET", plantilla, 404)

    for _ in range(2):
        await client.get(
            f"{settings.api_v1_prefix}/reclamos/{uuid.uuid4()}", headers=auth(token_operador)
        )

    assert _pedidos("GET", plantilla, 404) == antes + 2


async def test_cuenta_el_status_que_recibio_el_cliente(client: AsyncClient) -> None:
    ruta = f"{settings.api_v1_prefix}/reclamos"
    antes = _pedidos("GET", ruta, 401)

    await client.get(ruta)

    assert _pedidos("GET", ruta, 401) == antes + 1


async def test_una_url_que_no_existe_no_crea_una_serie_propia(client: AsyncClient) -> None:
    antes = _pedidos("GET", RUTA_DESCONOCIDA, 404)

    await client.get(f"/no-existe/{uuid.uuid4()}")

    assert _pedidos("GET", RUTA_DESCONOCIDA, 404) == antes + 1


async def test_un_metodo_inventado_no_crea_una_serie_propia(client: AsyncClient) -> None:
    antes = _pedidos("OTRO", "/health", 405)

    await client.request("INVENTADO", "/health")

    assert _pedidos("OTRO", "/health", 405) == antes + 1


class _Ruta:
    def __init__(self, path: str) -> None:
        self.path = path


@pytest.mark.parametrize(
    ("parte", "pedido", "esperada"),
    [
        # A route in an included router knows only its own part.
        ("/reclamos/{reclamo_id}", "/api/v1/reclamos/123", "/api/v1/reclamos/{reclamo_id}"),
        ("/reclamos", "/api/v1/reclamos", "/api/v1/reclamos"),
        # A route that already carries its whole path stays as it is.
        ("/health", "/health", "/health"),
        ("/api/v1/reclamos/{reclamo_id}", "/api/v1/reclamos/9", "/api/v1/reclamos/{reclamo_id}"),
        ("/", "/", "/"),
    ],
)
def test_la_plantilla_lleva_el_prefijo_y_nunca_el_valor(
    parte: str, pedido: str, esperada: str
) -> None:
    assert plantilla_de_ruta({"route": _Ruta(parte), "path": pedido}) == esperada


def test_sin_ruta_encontrada_la_plantilla_es_la_desconocida() -> None:
    assert plantilla_de_ruta({"path": "/lo-que-sea"}) == RUTA_DESCONOCIDA


# --- Events received -------------------------------------------------------------


async def test_cuenta_un_evento_que_no_manejamos_como_ignorado(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "gateway_webhook_token", TOKEN_WEBHOOK)
    antes = _recibidos("otro", "ignorado")
    sobre = {
        "metadata": {
            "eventId": str(uuid.uuid4()),
            "eventType": "com.citypass.otro.AlgoQueNoEscuchamos",
        },
        "data": {},
    }

    respuesta = await client.post(
        f"{settings.api_v1_prefix}/webhooks/citypass?token={TOKEN_WEBHOOK}", json=sobre
    )

    assert respuesta.status_code == 204
    assert _recibidos("otro", "ignorado") == antes + 1


# --- Events published ------------------------------------------------------------


async def _publicar(respuestas_de_eventos: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """Publish one ReclamoCreado against a gateway that answers that status."""

    async def sin_espera(_segundos: float) -> None:
        return None

    monkeypatch.setattr("app.events.gateway.asyncio.sleep", sin_espera)

    def responder(pedido: httpx.Request) -> httpx.Response:
        if pedido.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 900})
        return httpx.Response(respuestas_de_eventos)

    publisher = GatewayEventPublisher(
        _config(), httpx.AsyncClient(transport=httpx.MockTransport(responder))
    )
    await publisher.publish(topics.RECLAMO_CREADO, sobre_creado().data, correlation_id="corr-1")


@pytest.mark.parametrize(
    ("status_del_gateway", "resultado"),
    [(202, "publicado"), (400, "rechazado"), (503, "fallido")],
)
async def test_cuenta_cada_evento_segun_como_termino(
    status_del_gateway: int, resultado: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    antes = _publicados("ReclamoCreado", resultado)

    await _publicar(status_del_gateway, monkeypatch)

    assert _publicados("ReclamoCreado", resultado) == antes + 1
