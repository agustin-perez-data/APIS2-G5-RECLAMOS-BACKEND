"""Squad 3: claims filed around a mass activity are related to it (ADR 0013)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.core.config import settings
from app.events import topics
from app.events.gateway import traducir
from app.events.producer import InMemoryEventPublisher

URL_WEBHOOK = "/api/v1/webhooks/citypass"
TOKEN = "secreto-webhook"

# Plaza de Mayo. 0.0018 degrees of latitude are ~200 m; 0.0045 are ~500 m.
PLAZA_LAT, PLAZA_LNG = -34.6083, -58.3712
A_200_METROS = PLAZA_LAT + 0.0018
A_500_METROS = PLAZA_LAT + 0.0045


@pytest.fixture(autouse=True)
def token_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gateway_webhook_token", TOKEN)


def ms(momento: datetime) -> int:
    return int(momento.timestamp() * 1000)


def sobre(tipo: str, data: dict) -> dict:
    return {
        "metadata": {
            "eventId": str(uuid.uuid4()),
            "eventType": tipo,
            "source": "grupo7",
            "receivedAt": ms(datetime.now(UTC)),
        },
        "data": data,
    }


def actividad_creada(
    *,
    empieza_hace: timedelta = timedelta(hours=1),
    termina_en: timedelta = timedelta(hours=2),
    **cambios,
) -> dict:
    """ActividadCreada as the squad's plan defines it: millis and `ubicacion`."""
    ahora = datetime.now(UTC)
    actividad_id = str(uuid.uuid4())
    data = {
        "correlationId": f"act-{actividad_id}",
        "actividadId": actividad_id,
        "titulo": "Festival de Primavera",
        "estado": "PROGRAMADA",
        "capacidad": 5000,
        "fechaHoraInicio": ms(ahora - empieza_hace),
        "fechaHoraFinalizacion": ms(ahora + termina_en),
        "ubicacion": {"lat": PLAZA_LAT, "lng": PLAZA_LNG},
        "direccion": "Av. Rivadavia 1",
        "espacioNombre": "Plaza de Mayo",
        "actorSub": None,
    }
    data.update(cambios)
    return sobre("com.citypass.espacios.ActividadCreada", data)


def actividad_modificada(
    creada: dict, estado_nuevo: str, *, hace: timedelta = timedelta(0), **cambios
) -> dict:
    """ActividadModificada for an activity already announced, as Public Spaces publishes it."""
    data = {
        "correlationId": creada["data"]["correlationId"],
        "actividadId": creada["data"]["actividadId"],
        "estadoAnterior": "PROGRAMADA",
        "estadoNuevo": estado_nuevo,
        "motivo": None,
        "causaId": None,
        "causaTipo": None,
        "modificadaEn": ms(datetime.now(UTC) - hace),
        "actorSub": "op-espacios",
    }
    data.update(cambios)
    return sobre("com.citypass.espacios.ActividadModificada", data)


def reclamo_en(latitud: float | None, longitud: float | None = PLAZA_LNG) -> dict:
    return {
        "titulo": "Basura acumulada en la plaza",
        "descripcion": "Despues del festival quedaron los cestos desbordados y bolsas tiradas.",
        "categoria": "RESIDUOS",
        "prioridad": "MEDIA",
        "latitud": latitud,
        "longitud": longitud if latitud is not None else None,
    }


async def publicar(client: AsyncClient, evento: dict) -> None:
    respuesta = await client.post(URL_WEBHOOK, params={"token": TOKEN}, json=evento)
    assert respuesta.status_code == 204, respuesta.text


async def actividades(client: AsyncClient, auth, token: str, **params) -> list[dict]:
    respuesta = await client.get("/api/v1/actividades", headers=auth(token), params=params)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


async def cargar_reclamo(client: AsyncClient, auth, token: str, datos: dict) -> dict:
    respuesta = await client.post("/api/v1/reclamos", headers=auth(token), json=datos)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


# --- Receiving the activity ---------------------------------------------------
async def test_una_actividad_masiva_queda_registrada(
    client: AsyncClient, auth, token_operador
) -> None:
    await publicar(client, actividad_creada())

    [actividad] = await actividades(client, auth, token_operador)
    assert actividad["titulo"] == "Festival de Primavera"
    assert actividad["capacidad"] == 5000
    assert actividad["espacio_nombre"] == "Plaza de Mayo"
    assert actividad["latitud"] == PLAZA_LAT
    assert actividad["reclamos_relacionados"] == 0


async def test_una_reentrega_no_duplica_la_actividad(
    client: AsyncClient, auth, token_operador
) -> None:
    evento = actividad_creada()
    await publicar(client, evento)
    await publicar(client, evento)
    # Same activity republished under a new eventId: still one.
    otra_entrega = sobre(evento["metadata"]["eventType"], evento["data"])
    await publicar(client, otra_entrega)

    assert len(await actividades(client, auth, token_operador)) == 1


@pytest.mark.parametrize(
    "cambios",
    [
        pytest.param({"estado": "CANCELADA"}, id="cancelada"),
        pytest.param({"estado": "CANCELLED"}, id="cancelled"),
        pytest.param({"capacidad": 999}, id="no-es-masiva"),
        pytest.param({"capacidad": None}, id="sin-capacidad"),
        pytest.param({"ubicacion": None}, id="sin-coordenadas"),
    ],
)
async def test_las_actividades_que_no_aplican_se_ignoran(
    client: AsyncClient, auth, token_operador, cambios: dict
) -> None:
    await publicar(client, actividad_creada(**cambios))

    assert await actividades(client, auth, token_operador, incluir_finalizadas=True) == []


async def test_acepta_los_nombres_del_primer_borrador(
    client: AsyncClient, auth, token_operador
) -> None:
    # English names, ISO dates and loose coordinates, as Public Spaces first sent it.
    ahora = datetime.now(UTC)
    evento = sobre(
        "com.citypass.espacios.ActividadCreada",
        {
            "communityEventId": str(uuid.uuid4()),
            "title": "Recital en la plaza",
            "status": "ACTIVE",
            "capacity": 3000,
            "startDate": (ahora - timedelta(hours=1)).isoformat(),
            "endDate": (ahora + timedelta(hours=1)).isoformat(),
            "latitude": PLAZA_LAT,
            "longitude": PLAZA_LNG,
        },
    )
    await publicar(client, evento)

    [actividad] = await actividades(client, auth, token_operador)
    assert actividad["titulo"] == "Recital en la plaza"
    assert actividad["longitud"] == PLAZA_LNG


async def test_sin_fecha_de_inicio_cuenta_desde_que_llega(
    client: AsyncClient, auth, token_operador, token_ciudadano
) -> None:
    evento = actividad_creada()
    del evento["data"]["fechaHoraInicio"]
    await publicar(client, evento)

    reclamo = await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(A_200_METROS))
    assert reclamo["actividad"]["titulo"] == "Festival de Primavera"


async def test_sin_fecha_de_fin_el_evento_es_invalido(client: AsyncClient) -> None:
    evento = actividad_creada()
    del evento["data"]["fechaHoraFinalizacion"]

    # Same as every other malformed payload: the handler fails (a 500 for the
    # dispatcher), which retries and then leaves it in its dead letter queue.
    with pytest.raises(ValidationError, match="fechaHoraFinalizacion"):
        await client.post(URL_WEBHOOK, params={"token": TOKEN}, json=evento)


# --- Relating the claims filed around it -------------------------------------
async def test_un_reclamo_cerca_durante_la_actividad_queda_relacionado(
    client: AsyncClient, auth, token_ciudadano, token_operador
) -> None:
    await publicar(client, actividad_creada())

    reclamo = await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(A_200_METROS))
    assert reclamo["actividad"]["titulo"] == "Festival de Primavera"

    detalle = await client.get(f"/api/v1/reclamos/{reclamo['id']}", headers=auth(token_ciudadano))
    assert detalle.json()["actividad"]["id"] == reclamo["actividad"]["id"]

    [actividad] = await actividades(client, auth, token_operador)
    assert actividad["reclamos_relacionados"] == 1


async def test_un_reclamo_lejos_no_se_relaciona(client: AsyncClient, auth, token_ciudadano) -> None:
    await publicar(client, actividad_creada())

    reclamo = await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(A_500_METROS))
    assert reclamo["actividad"] is None


async def test_un_reclamo_sin_coordenadas_no_se_relaciona(
    client: AsyncClient, auth, token_ciudadano
) -> None:
    await publicar(client, actividad_creada())

    reclamo = await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(None))
    assert reclamo["actividad"] is None


async def test_un_reclamo_antes_de_que_empiece_no_se_relaciona(
    client: AsyncClient, auth, token_ciudadano
) -> None:
    await publicar(client, actividad_creada(empieza_hace=timedelta(hours=-1)))

    reclamo = await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(A_200_METROS))
    assert reclamo["actividad"] is None


async def test_en_las_horas_siguientes_al_fin_todavia_se_relaciona(
    client: AsyncClient, auth, token_ciudadano
) -> None:
    # Ended 5 h ago: inside the 6 h window, the clean-up is still going on.
    await publicar(
        client,
        actividad_creada(empieza_hace=timedelta(hours=8), termina_en=timedelta(hours=-5)),
    )

    reclamo = await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(A_200_METROS))
    assert reclamo["actividad"] is not None


async def test_pasada_la_ventana_ya_no_se_relaciona(
    client: AsyncClient, auth, token_ciudadano, token_operador
) -> None:
    await publicar(
        client,
        actividad_creada(empieza_hace=timedelta(hours=10), termina_en=timedelta(hours=-7)),
    )

    reclamo = await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(A_200_METROS))
    assert reclamo["actividad"] is None
    # Out of the default list, still there when asked for.
    assert await actividades(client, auth, token_operador) == []
    assert len(await actividades(client, auth, token_operador, incluir_finalizadas=True)) == 1


async def test_con_dos_actividades_cerca_gana_la_mas_cercana(
    client: AsyncClient, auth, token_ciudadano
) -> None:
    await publicar(client, actividad_creada(titulo="En la plaza"))
    await publicar(
        client,
        actividad_creada(
            titulo="A 250 m",
            ubicacion={"lat": PLAZA_LAT + 0.00225, "lng": PLAZA_LNG},
        ),
    )

    # ~20 m from the square, ~230 m from the other one.
    reclamo = await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(PLAZA_LAT + 0.0002))
    assert reclamo["actividad"]["titulo"] == "En la plaza"


async def test_un_reclamo_automatico_de_residuos_tambien_se_relaciona(
    client: AsyncClient, auth, token_operador
) -> None:
    await publicar(client, actividad_creada())
    alerta = sobre(
        "com.citypass.residuos.AlertaGenerada",
        {
            "alertaId": "AL-9",
            "contenedorId": "CT-0005",
            "tipoAlerta": "SATURACION",
            "nivelLlenado": 97.0,
            "zona": "Monserrat",
            "latitud": A_200_METROS,
            "longitud": PLAZA_LNG,
        },
    )
    await publicar(client, alerta)

    listado = await client.get(
        "/api/v1/reclamos", headers=auth(token_operador), params={"categoria": "RESIDUOS"}
    )
    [reclamo] = listado.json()["items"]
    assert reclamo["actividad"]["titulo"] == "Festival de Primavera"


# --- Cancelled, suspended, resumed (ADR 0018) ---------------------------------
async def test_una_actividad_cancelada_deja_de_relacionar_reclamos(
    client: AsyncClient, auth, token_ciudadano, token_operador
) -> None:
    creada = actividad_creada()
    await publicar(client, creada)
    await publicar(client, actividad_modificada(creada, "CANCELADA"))

    reclamo = await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(A_200_METROS))
    assert reclamo["actividad"] is None

    # Still listed, with its state, so the operator knows why nothing relates.
    [actividad] = await actividades(client, auth, token_operador)
    assert actividad["estado"] == "CANCELADA"


async def test_los_reclamos_ya_relacionados_conservan_la_relacion(
    client: AsyncClient, auth, token_ciudadano, token_operador
) -> None:
    creada = actividad_creada()
    await publicar(client, creada)
    antes = await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(A_200_METROS))

    await publicar(client, actividad_modificada(creada, "CANCELADA"))

    detalle = await client.get(f"/api/v1/reclamos/{antes['id']}", headers=auth(token_ciudadano))
    assert detalle.json()["actividad"]["titulo"] == "Festival de Primavera"
    [actividad] = await actividades(client, auth, token_operador)
    assert actividad["reclamos_relacionados"] == 1


async def test_una_suspendida_que_se_reanuda_vuelve_a_relacionar(
    client: AsyncClient, auth, token_ciudadano
) -> None:
    creada = actividad_creada()
    await publicar(client, creada)

    await publicar(client, actividad_modificada(creada, "SUSPENDIDA", hace=timedelta(minutes=5)))
    durante = await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(A_200_METROS))
    assert durante["actividad"] is None

    await publicar(client, actividad_modificada(creada, "PROGRAMADA", estadoAnterior="SUSPENDIDA"))
    despues = await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(A_200_METROS))
    assert despues["actividad"]["titulo"] == "Festival de Primavera"


async def test_una_finalizada_sigue_relacionando_en_las_horas_siguientes(
    client: AsyncClient, auth, token_ciudadano
) -> None:
    # The clean-up after the festival is the whole case: ending is not cancelling.
    creada = actividad_creada(empieza_hace=timedelta(hours=4), termina_en=timedelta(hours=-1))
    await publicar(client, creada)
    await publicar(client, actividad_modificada(creada, "FINALIZADA"))

    reclamo = await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(A_200_METROS))
    assert reclamo["actividad"] is not None


async def test_una_modificacion_vieja_no_pisa_una_nueva(
    client: AsyncClient, auth, token_ciudadano, token_operador
) -> None:
    creada = actividad_creada()
    await publicar(client, creada)
    await publicar(client, actividad_modificada(creada, "CANCELADA"))
    # A resume from before the cancellation, delivered late by the bus.
    await publicar(client, actividad_modificada(creada, "PROGRAMADA", hace=timedelta(minutes=10)))

    [actividad] = await actividades(client, auth, token_operador)
    assert actividad["estado"] == "CANCELADA"
    reclamo = await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(A_200_METROS))
    assert reclamo["actividad"] is None


async def test_una_reentrega_de_la_modificacion_no_hace_nada(
    client: AsyncClient, auth, token_operador
) -> None:
    creada = actividad_creada()
    await publicar(client, creada)
    cancelacion = actividad_modificada(creada, "CANCELADA")
    await publicar(client, cancelacion)
    await publicar(client, cancelacion)

    [actividad] = await actividades(client, auth, token_operador)
    assert actividad["estado"] == "CANCELADA"


async def test_sin_actividad_id_se_encuentra_por_correlation_id(
    client: AsyncClient, auth, token_operador
) -> None:
    creada = actividad_creada()
    await publicar(client, creada)
    modificada = actividad_modificada(creada, "CANCELADA")
    del modificada["data"]["actividadId"]
    await publicar(client, modificada)

    [actividad] = await actividades(client, auth, token_operador)
    assert actividad["estado"] == "CANCELADA"


async def test_la_modificacion_de_una_actividad_que_no_guardamos_se_ignora(
    client: AsyncClient, auth, token_operador
) -> None:
    # Below the mass cut: never stored, so its cancellation has nothing to cancel.
    chica = actividad_creada(capacidad=200)
    await publicar(client, chica)
    await publicar(client, actividad_modificada(chica, "CANCELADA"))

    assert await actividades(client, auth, token_operador, incluir_finalizadas=True) == []


async def test_una_actividad_nueva_aparece_como_programada(
    client: AsyncClient, auth, token_operador
) -> None:
    await publicar(client, actividad_creada())

    [actividad] = await actividades(client, auth, token_operador)
    assert actividad["estado"] == "PROGRAMADA"


# --- What Analytics receives (ADR 0016) ---------------------------------------
def creado_en_el_bus(publisher: InMemoryEventPublisher) -> dict:
    """The ReclamoCreado fields exactly as the gateway gets them."""
    [creado] = publisher.eventos_de(topics.RECLAMO_CREADO)
    _, datos = traducir(topics.RECLAMO_CREADO, creado)
    return datos


async def test_el_reclamo_relacionado_sale_con_la_actividad_como_causa(
    client: AsyncClient, auth, token_ciudadano, publisher: InMemoryEventPublisher
) -> None:
    evento = actividad_creada()
    await publicar(client, evento)

    await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(A_200_METROS))

    datos = creado_en_el_bus(publisher)
    # Public Spaces' id, not ours: it is what Analytics joins with ActividadCreada.
    actividad_id = evento["data"]["actividadId"]
    assert datos["causaTipo"] == "EVENTO_PUBLICO"
    assert datos["causaId"] == actividad_id
    assert datos["actividadId"] == actividad_id


async def test_un_reclamo_sin_actividad_sale_sin_causa(
    client: AsyncClient, auth, token_ciudadano, publisher: InMemoryEventPublisher
) -> None:
    await publicar(client, actividad_creada())

    await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(A_500_METROS))

    datos = creado_en_el_bus(publisher)
    assert datos["causaId"] is None
    assert datos["causaTipo"] is None
    assert datos["actividadId"] is None


# --- What the operator sees ---------------------------------------------------
async def test_se_pueden_filtrar_los_reclamos_de_una_actividad(
    client: AsyncClient, auth, token_ciudadano, token_operador
) -> None:
    await publicar(client, actividad_creada())
    relacionado = await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(A_200_METROS))
    await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(A_500_METROS))
    actividad_id = relacionado["actividad"]["id"]

    listado = await client.get(
        "/api/v1/reclamos", headers=auth(token_operador), params={"actividad_id": actividad_id}
    )
    cuerpo = listado.json()
    assert cuerpo["total"] == 1
    assert cuerpo["items"][0]["id"] == relacionado["id"]
    assert cuerpo["items"][0]["actividad"]["id"] == actividad_id


async def test_la_bandeja_muestra_la_actividad(
    client: AsyncClient, auth, token_ciudadano, token_operador
) -> None:
    await publicar(client, actividad_creada())
    await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(A_200_METROS))

    bandeja = await client.get("/api/v1/reclamos/bandeja", headers=auth(token_operador))
    [item] = bandeja.json()["items"]
    assert item["actividad"]["titulo"] == "Festival de Primavera"


async def test_los_reclamos_de_siempre_no_traen_actividad(
    client: AsyncClient, auth, token_ciudadano
) -> None:
    # No activity at all: the field is there and empty, nothing else changes.
    reclamo = await cargar_reclamo(client, auth, token_ciudadano, reclamo_en(A_200_METROS))
    assert reclamo["actividad"] is None


async def test_un_vecino_no_ve_el_listado_de_actividades(
    client: AsyncClient, auth, token_ciudadano
) -> None:
    respuesta = await client.get("/api/v1/actividades", headers=auth(token_ciudadano))
    assert respuesta.status_code == 403
