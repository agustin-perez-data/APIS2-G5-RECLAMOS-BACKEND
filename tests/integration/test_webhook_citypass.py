"""CU-INT-01: events from other modules arriving by the gateway's webhook."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.domain.enums import USUARIO_SISTEMA, CanalOrigen, CategoriaReclamo, PrioridadReclamo
from app.events import topics
from app.repositories.reclamo_repository import FiltroReclamos
from app.schemas.reclamo import ReclamoCrear
from app.services.emergencia_via_service import TITULO_RECLAMO_VIAL
from app.services.reclamo_service import ReclamoService
from tests.conftest import CIUDADANO_ID

URL = "/api/v1/webhooks/citypass"
TOKEN = "secreto-webhook"

# How Emergencies sends the position since 6/11: base64 ciphertext we cannot read.
LATITUD_CIFRADA = "RUxDAQExuIWL05EIEbZ+pYcyRW/K80OxpZXy4Qcz56ETZxfmAL0vlgcQeUjGZq4ZEP+PEg=="
LONGITUD_CIFRADA = "RUxDAQExgnptTMas+gjNvow+FKmMMYGk8p9W9PO+Ca4YjRqnMcCsz39YUHSsdYhSivnvkA=="


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


async def test_una_intervencion_finalizada_cierra_el_reclamo(
    client: AsyncClient, auth, token_ciudadano
) -> None:
    """The last link of CU-INT-01, through the door the gateway really uses."""
    creado = await client.post(
        "/api/v1/reclamos",
        json={
            "titulo": "Auto estacionado sobre la ciclovia",
            "descripcion": "Hay un auto arriba de la bicisenda y no se puede pasar",
            "barrio": "Palermo",
        },
        headers=auth(token_ciudadano),
    )
    reclamo_id = creado.json()["id"]

    respuesta = await client.post(
        URL,
        headers={"X-Webhook-Token": TOKEN},
        json=sobre(
            "com.citypass.espacios.IntervencionFinalizada",
            {
                "reclamoId": reclamo_id,
                "resultado": "RESUELTO",
                "idAuto": "AB123CD",
                "solicitadoAt": 1792346000000,
                "resueltoAt": 1792349999000,
            },
        ),
    )
    assert respuesta.status_code == 204, respuesta.text

    detalle = await client.get(f"/api/v1/reclamos/{reclamo_id}", headers=auth(token_ciudadano))
    assert detalle.json()["estado"] == "RESUELTO"
    assert detalle.json()["resolucion"]


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


async def test_una_emergencia_con_coordenadas_cifradas_escala_por_barrio(
    client: AsyncClient, service: ReclamoService
) -> None:
    """The EmergenciaCreada that bounced on 6/11, as the gateway delivered it.

    Emergencies encrypts the position, so the coordinates are unreadable. That
    used to fail the whole event with a 500 until it landed in the gateway's
    dead letter queue; the neighbourhood travels in clear and is enough.
    """
    await _reclamo_en(service, "San Nicolas")
    await _reclamo_en(service, "Caballito")

    evento = sobre(
        "com.citypass.emergencias.EmergenciaCreada",
        {
            "emergenciaId": "07181734-9403-4a3a-9a3e-c347e359e18b",
            "categoria": "INCENDIO",
            "prioridad": "ALTA",
            "estado": "PENDIENTE",
            "barrio": "SAN NICOLAS",
            "ubicacion": {
                "barrio": "SAN NICOLAS",
                "latitud": LATITUD_CIFRADA,
                "longitud": LONGITUD_CIFRADA,
            },
            "afectaCirculacion": True,
            "causaId": None,
            "causaTipo": None,
            "prioridadOriginal": None,
            "ciudadanoId": "CIT-JuanPanico",
            "correlationId": "07181734-9403-4a3a-9a3e-c347e359e18b",
            "createdAt": "2026-11-06T07:26:45.959Z",
        },
    )
    respuesta = await client.post(URL, params={"token": TOKEN}, json=evento)
    assert respuesta.status_code == 204

    san_nicolas, _ = await service.listar(FiltroReclamos(barrio="San Nicolas"))
    caballito, _ = await service.listar(FiltroReclamos(barrio="Caballito"))
    assert san_nicolas[0].prioridad is PrioridadReclamo.CRITICA
    assert caballito[0].prioridad is PrioridadReclamo.BAJA


async def test_emergencia_actualizada_crea_a5_por_webhook_sin_incidente_previo(
    client: AsyncClient, service: ReclamoService, publisher
) -> None:
    emergencia_id = "07181734-9403-4a3a-9a3e-c347e359e18b"
    evento = sobre(
        "com.citypass.emergencias.EmergenciaActualizada",
        {
            "emergenciaId": emergencia_id,
            "estadoAnterior": "EN_CURSO",
            "estadoNuevo": "RESUELTA",
            "updatedAt": "2026-11-13T12:00:00Z",
            "resueltoAt": "2026-11-13T12:00:00Z",
            "causasRelacionadas": ["VIA"],
            "descripcionProblema": "Quedo un bache profundo en la calzada tras el choque.",
            "barrio": "SAN NICOLAS",
            "latitud": -34.604,
            "longitud": -58.382,
            "ubicacion": {
                "barrio": "SAN NICOLAS",
                "latitud": LATITUD_CIFRADA,
                "longitud": LONGITUD_CIFRADA,
            },
            "correlationId": "corr-a5-webhook",
        },
    )

    respuesta = await client.post(URL, headers={"X-Webhook-Token": TOKEN}, json=evento)

    assert respuesta.status_code == 204, respuesta.text
    reclamo = await service.repo.obtener_por_evento_origen(f"emergencia:{emergencia_id}")
    assert reclamo is not None
    assert reclamo.ciudadano_id == USUARIO_SISTEMA
    assert reclamo.titulo == TITULO_RECLAMO_VIAL
    assert reclamo.canal is CanalOrigen.EVENTO
    assert reclamo.latitud == -34.604
    assert reclamo.longitud == -58.382
    assert reclamo.prioridad in {PrioridadReclamo.ALTA, PrioridadReclamo.CRITICA}
    assert reclamo.correlation_id == "corr-a5-webhook"
    creado = publisher.eventos_de(topics.RECLAMO_CREADO)
    assert len(creado) == 1
    assert creado[0].data.reclamo_id == reclamo.id
