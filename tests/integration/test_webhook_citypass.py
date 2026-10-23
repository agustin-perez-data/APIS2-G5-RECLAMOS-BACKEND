"""CU-INT-01: events from other modules arriving by the gateway's webhook."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.domain.enums import CategoriaReclamo, PrioridadReclamo
from app.repositories.reclamo_repository import FiltroReclamos
from app.schemas.reclamo import ReclamoCrear
from app.services.reclamo_service import ReclamoService
from tests.conftest import CIUDADANO_ID

URL = "/api/v1/webhooks/citypass"
TOKEN = "secreto-webhook"


@pytest.fixture(autouse=True)
def token_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gateway_webhook_token", TOKEN)


def sobre(tipo: str, data: dict) -> dict:
    return {
        "metadata": {
            "eventId": str(uuid.uuid4()),
            "eventType": tipo,
            "source": tipo.split(".")[2],
            "receivedAt": 1792000000000,
        },
        "data": data,
    }


def alerta_saturacion(**cambios) -> dict:
    data = {
        "alertaId": "AL-1",
        "contenedorId": "CT-0421",
        "tipoAlerta": "SATURACION",
        "nivelLlenado": 97.0,
        "zona": "Centro",
        "prioridad": "ALTA",
        "latitud": -34.6118,
        "longitud": -58.3960,
        "correlationId": "corr-res-1",
        "occurredAt": "2026-11-01T15:00:00Z",
    }
    data.update(cambios)
    return sobre("com.citypass.residuos.AlertaGenerada", data)


async def test_sin_token_responde_401(client: AsyncClient) -> None:
    respuesta = await client.post(URL, json=alerta_saturacion())
    assert respuesta.status_code == 401


async def test_con_token_equivocado_responde_401(client: AsyncClient) -> None:
    respuesta = await client.post(URL, params={"token": "otro"}, json=alerta_saturacion())
    assert respuesta.status_code == 401


async def test_el_token_tambien_se_acepta_por_cabecera(client: AsyncClient) -> None:
    # Preferred over the query param: the URL ends up in the access log.
    respuesta = await client.post(URL, headers={"X-Webhook-Token": TOKEN}, json=alerta_saturacion())
    assert respuesta.status_code == 204


async def test_una_cabecera_con_token_equivocado_responde_401(client: AsyncClient) -> None:
    respuesta = await client.post(
        URL, headers={"X-Webhook-Token": "no-es"}, json=alerta_saturacion()
    )
    assert respuesta.status_code == 401


async def test_alerta_de_saturacion_abre_un_reclamo(
    client: AsyncClient, auth, token_operador
) -> None:
    respuesta = await client.post(URL, params={"token": TOKEN}, json=alerta_saturacion())
    assert respuesta.status_code == 204

    listado = await client.get("/api/v1/reclamos", headers=auth(token_operador))
    reclamos = listado.json()["items"]
    assert len(reclamos) == 1
    assert reclamos[0]["categoria"] == "RESIDUOS"
    assert reclamos[0]["barrio"] == "Centro"


async def test_la_misma_alerta_reentregada_no_duplica(
    client: AsyncClient, auth, token_operador
) -> None:
    evento = alerta_saturacion()
    await client.post(URL, params={"token": TOKEN}, json=evento)
    await client.post(URL, params={"token": TOKEN}, json=evento)

    listado = await client.get("/api/v1/reclamos", headers=auth(token_operador))
    assert len(listado.json()["items"]) == 1


async def test_una_alerta_de_incendio_no_es_un_reclamo(
    client: AsyncClient, auth, token_operador
) -> None:
    respuesta = await client.post(
        URL, params={"token": TOKEN}, json=alerta_saturacion(tipoAlerta="INCENDIO")
    )
    assert respuesta.status_code == 204

    listado = await client.get("/api/v1/reclamos", headers=auth(token_operador))
    assert listado.json()["items"] == []


async def test_un_tipo_que_no_consumimos_se_acepta_y_se_ignora(client: AsyncClient) -> None:
    respuesta = await client.post(
        URL,
        params={"token": TOKEN},
        json=sobre("com.citypass.movilidad.ViajeIniciado", {"id": "1"}),
    )
    assert respuesta.status_code == 204


async def test_un_evento_sin_metadata_responde_400(client: AsyncClient) -> None:
    respuesta = await client.post(URL, params={"token": TOKEN}, json={"data": {}})
    assert respuesta.status_code == 400


async def _reclamo_en(service: ReclamoService, barrio: str) -> None:
    await service.crear(
        ReclamoCrear(
            titulo="Bache profundo en la esquina",
            descripcion="Hay un bache grande que complica el paso de autos y bicis",
            categoria=CategoriaReclamo.BACHES,
            prioridad=PrioridadReclamo.BAJA,
            barrio=barrio,
        ),
        ciudadano_id=CIUDADANO_ID,
    )


async def test_un_evento_masivo_eleva_los_reclamos_de_su_zona(
    client: AsyncClient, service: ReclamoService
) -> None:
    await _reclamo_en(service, "Palermo")
    await _reclamo_en(service, "Caballito")

    evento = sobre(
        "com.citypass.espacios.EventoComunitarioPublicado",
        {
            "eventoId": "ev-1",
            "espacioId": "sp-1",
            "titulo": "Feria del libro",
            "zona": "Palermo",
            "inicio": "2026-11-01T15:00:00Z",
            "cupoMaximo": 300,
            "inscriptos": 0,
        },
    )
    respuesta = await client.post(URL, params={"token": TOKEN}, json=evento)
    assert respuesta.status_code == 204

    palermo, _ = await service.listar(FiltroReclamos(barrio="Palermo"))
    caballito, _ = await service.listar(FiltroReclamos(barrio="Caballito"))
    assert palermo[0].prioridad is PrioridadReclamo.MEDIA
    assert caballito[0].prioridad is PrioridadReclamo.BAJA
