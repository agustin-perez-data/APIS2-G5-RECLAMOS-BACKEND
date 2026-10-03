"""In-app notifications for the owner of a claim (ADR 0008).

The rules these pin down: every state change and every comment by someone else
notifies the owner exactly once; the author of a change is never notified of
their own action; and each user only ever sees and marks their own inbox.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotificacionNoEncontrada
from app.core.security import CurrentUser, Roles
from app.db.models import Notificacion
from app.domain.enums import (
    USUARIO_SISTEMA,
    CategoriaReclamo,
    EstadoReclamo,
    PrioridadReclamo,
    TipoNotificacion,
)
from app.events import topics
from app.events.producer import InMemoryEventPublisher
from app.schemas.reclamo import CambioEstado, ReclamoCrear
from app.services.notificacion_service import NotificacionService, resumir
from app.services.reclamo_service import ReclamoService
from tests.conftest import CIUDADANO_ID, OTRO_CIUDADANO_ID

OTRO_VECINO = CurrentUser(
    id=OTRO_CIUDADANO_ID, nombre="Vecina de enfrente", roles=frozenset({Roles.CIUDADANO})
)


def datos_reclamo(**overrides) -> ReclamoCrear:
    base = {
        "titulo": "Luminaria apagada en la plaza",
        "descripcion": "El foco del poste no enciende hace dos semanas y quedo todo oscuro",
        "categoria": CategoriaReclamo.ALUMBRADO,
        "prioridad": PrioridadReclamo.MEDIA,
        "barrio": "Centro",
    }
    base.update(overrides)
    return ReclamoCrear(**base)


async def bandeja(session: AsyncSession, destinatario_id: str = CIUDADANO_ID) -> list[Notificacion]:
    items, _ = await NotificacionService(session).listar(destinatario_id, size=100)
    return items


# --- State changes --------------------------------------------------------------
async def test_un_cambio_de_estado_notifica_al_duenio(
    service: ReclamoService, session: AsyncSession, usuario_operador
) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)
    await service.cambiar_estado(
        reclamo.id,
        CambioEstado(estado=EstadoReclamo.EN_REVISION, motivo="Lo estamos verificando"),
        usuario_operador,
    )

    [notificacion] = await bandeja(session)
    assert notificacion.tipo is TipoNotificacion.ESTADO
    assert notificacion.reclamo_id == reclamo.id
    assert notificacion.titulo == "Tu reclamo pasó a En revisión"
    assert "Recibido a En revisión" in notificacion.mensaje
    assert "Motivo: Lo estamos verificando" in notificacion.mensaje
    assert notificacion.estado_nuevo is EstadoReclamo.EN_REVISION
    assert notificacion.leida is False
    # The operator who made the change gets nothing.
    assert await bandeja(session, usuario_operador.id) == []


async def test_el_alta_no_notifica(service: ReclamoService, session: AsyncSession) -> None:
    await service.crear(datos_reclamo(), CIUDADANO_ID)
    assert await bandeja(session) == []


async def test_cada_cambio_de_estado_es_una_notificacion(
    service: ReclamoService, session: AsyncSession, usuario_operador
) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)
    for estado in (EstadoReclamo.ASIGNADO, EstadoReclamo.EN_PROCESO, EstadoReclamo.RESUELTO):
        await service.cambiar_estado(
            reclamo.id,
            CambioEstado(estado=estado, resolucion="Se cambio la lampara"),
            usuario_operador,
        )

    notificaciones = await bandeja(session)
    # Newest first.
    assert [n.estado_nuevo for n in notificaciones] == [
        EstadoReclamo.RESUELTO,
        EstadoReclamo.EN_PROCESO,
        EstadoReclamo.ASIGNADO,
    ]
    resuelto = notificaciones[0]
    assert resuelto.titulo == "Tu reclamo fue resuelto"
    assert "Resolución: Se cambio la lampara" in resuelto.mensaje


async def test_no_se_notifica_al_duenio_de_su_propio_cambio(
    service: ReclamoService, session: AsyncSession
) -> None:
    # An operator who files a claim and then works it: no point telling them.
    operador = CurrentUser(id="operador-9", roles=frozenset({Roles.OPERADOR}))
    reclamo = await service.crear(datos_reclamo(), operador.id)
    await service.cambiar_estado(reclamo.id, CambioEstado(estado=EstadoReclamo.ASIGNADO), operador)

    assert await bandeja(session, operador.id) == []


async def test_los_reclamos_del_sistema_no_generan_notificaciones(
    service: ReclamoService, session: AsyncSession, usuario_operador
) -> None:
    # Claims opened by another module's event belong to nobody who reads them.
    reclamo = await service.crear(datos_reclamo(), USUARIO_SISTEMA)
    await service.cambiar_estado(
        reclamo.id, CambioEstado(estado=EstadoReclamo.ASIGNADO), usuario_operador
    )

    assert await bandeja(session, USUARIO_SISTEMA) == []


async def test_el_cierre_automatico_notifica(
    service: ReclamoService, session: AsyncSession, usuario_operador
) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)
    for estado in (EstadoReclamo.ASIGNADO, EstadoReclamo.EN_PROCESO, EstadoReclamo.RESUELTO):
        await service.cambiar_estado(reclamo.id, CambioEstado(estado=estado), usuario_operador)
    vencido = await service.obtener(reclamo.id)
    vencido.resuelto_at = datetime.now(UTC) - timedelta(days=30)
    await session.commit()

    await service.cerrar_resueltos_vencidos()

    ultima = (await bandeja(session))[0]
    assert ultima.estado_nuevo is EstadoReclamo.CERRADO
    assert ultima.titulo == "Tu reclamo fue cerrado"


# --- Comments ---------------------------------------------------------------------
async def test_un_comentario_oficial_notifica_al_duenio(
    service: ReclamoService, session: AsyncSession, usuario_operador
) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)
    comentario = await service.comentar(reclamo.id, "Ya lo derivamos al area", usuario_operador)

    [notificacion] = await bandeja(session)
    assert notificacion.tipo is TipoNotificacion.COMENTARIO
    assert notificacion.titulo == "Nuevo comentario oficial en tu reclamo"
    assert notificacion.comentario_id == comentario.id
    # Signed by the city: the operator's name stays internal.
    assert notificacion.mensaje.startswith("El municipio comentó")
    assert usuario_operador.nombre not in notificacion.mensaje


async def test_el_comentario_de_otro_vecino_notifica_al_duenio(
    service: ReclamoService, session: AsyncSession
) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)
    await service.comentar(reclamo.id, "En mi cuadra pasa lo mismo", OTRO_VECINO)

    [notificacion] = await bandeja(session)
    assert notificacion.titulo == "Nuevo comentario en tu reclamo"
    assert notificacion.mensaje.startswith("Vecina de enfrente comentó")
    assert await bandeja(session, OTRO_CIUDADANO_ID) == []


async def test_el_duenio_no_se_notifica_su_propio_comentario(
    service: ReclamoService, session: AsyncSession, usuario_ciudadano
) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)
    await service.comentar(reclamo.id, "Sigue igual", usuario_ciudadano)

    assert await bandeja(session) == []


async def test_un_comentario_publica_su_evento(
    service: ReclamoService, publisher: InMemoryEventPublisher, usuario_operador
) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)
    comentario = await service.comentar(reclamo.id, "Ya lo derivamos al area", usuario_operador)

    [evento] = publisher.eventos_de(topics.RECLAMO_COMENTARIO_CREADO)
    assert evento.data.comentario_id == comentario.id
    assert evento.data.reclamo_id == reclamo.id
    assert evento.data.ciudadano_id == CIUDADANO_ID
    assert evento.data.autor_id == usuario_operador.id
    assert evento.data.es_oficial is True
    # The comment text is citizen content: it does not travel on the bus.
    assert "texto" not in evento.data.model_dump()


async def test_el_comentario_de_un_incidente_notifica_y_se_publica(
    service: ReclamoService, session: AsyncSession, publisher: InMemoryEventPublisher
) -> None:
    await service.crear(datos_reclamo(prioridad=PrioridadReclamo.BAJA), CIUDADANO_ID)

    await service.escalar_por_incidente(barrio="Centro", motivo="Incendio en la zona")

    [notificacion] = await bandeja(session)
    assert notificacion.titulo == "Nuevo comentario oficial en tu reclamo"
    assert "Incendio en la zona" in notificacion.mensaje
    assert len(publisher.eventos_de(topics.RECLAMO_COMENTARIO_CREADO)) == 1


# --- Idempotency --------------------------------------------------------------------
async def test_procesar_dos_veces_el_mismo_cambio_no_duplica(
    service: ReclamoService, session: AsyncSession, usuario_operador
) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)
    await service.cambiar_estado(
        reclamo.id, CambioEstado(estado=EstadoReclamo.ASIGNADO), usuario_operador
    )
    historial = (await service.repo.historial_de(reclamo.id))[-1]

    # A retry of the same change, as a consumer redelivery would do.
    repetida = await NotificacionService(session).por_cambio_de_estado(
        reclamo, historial, actor_id=usuario_operador.id
    )
    await session.commit()

    assert repetida is None
    total = await session.execute(select(func.count()).select_from(Notificacion))
    # 1 ESTADO for the owner + 2 NUEVO_RECLAMO for staff (operador-1, admin-1)
    assert total.scalar_one() == 3


def test_el_resumen_queda_en_una_linea_y_acotado() -> None:
    assert resumir("hola\n\n  mundo") == "hola mundo"
    largo = resumir("palabra " * 100, limite=40)
    assert len(largo) == 40
    assert largo.endswith("…")


# --- Reading ---------------------------------------------------------------------------
async def test_marcar_leida_es_idempotente(
    service: ReclamoService, session: AsyncSession, usuario_operador
) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)
    await service.comentar(reclamo.id, "Ya lo derivamos al area", usuario_operador)
    [notificacion] = await bandeja(session)
    notificaciones = NotificacionService(session)

    primera = await notificaciones.marcar_leida(notificacion.id, CIUDADANO_ID)
    leida_at = primera.leida_at
    segunda = await notificaciones.marcar_leida(notificacion.id, CIUDADANO_ID)

    assert segunda.leida is True
    assert segunda.leida_at == leida_at
    assert await notificaciones.contar_no_leidas(CIUDADANO_ID) == 0


async def test_nadie_marca_la_notificacion_de_otro(
    service: ReclamoService, session: AsyncSession, usuario_operador
) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)
    await service.comentar(reclamo.id, "Ya lo derivamos al area", usuario_operador)
    [notificacion] = await bandeja(session)

    with pytest.raises(NotificacionNoEncontrada):
        await NotificacionService(session).marcar_leida(notificacion.id, OTRO_CIUDADANO_ID)
    assert (await bandeja(session))[0].leida is False


# --- HTTP ------------------------------------------------------------------------------
async def preparar_por_http(client: AsyncClient, auth, token_ciudadano, token_operador) -> str:
    """A claim with two notifications for its owner: a state change and a comment."""
    creado = await client.post(
        "/api/v1/reclamos",
        json={
            "titulo": "Luminaria apagada en la plaza",
            "descripcion": "El foco del poste no enciende hace dos semanas",
            "categoria": "ALUMBRADO",
            "prioridad": "MEDIA",
        },
        headers=auth(token_ciudadano),
    )
    reclamo_id = creado.json()["id"]
    cambio = await client.patch(
        f"/api/v1/reclamos/{reclamo_id}/estado",
        json={"estado": "EN_REVISION"},
        headers=auth(token_operador),
    )
    assert cambio.status_code == 200
    comentario = await client.post(
        f"/api/v1/reclamos/{reclamo_id}/comentarios",
        json={"texto": "Ya lo derivamos al area"},
        headers=auth(token_operador),
    )
    assert comentario.status_code == 201
    return reclamo_id


async def test_el_endpoint_lista_las_notificaciones_propias(
    client: AsyncClient, auth, token_ciudadano, token_operador
) -> None:
    reclamo_id = await preparar_por_http(client, auth, token_ciudadano, token_operador)

    respuesta = await client.get("/api/v1/notificaciones", headers=auth(token_ciudadano))

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["total"] == 2
    assert cuerpo["unread_count"] == 2
    comentario, estado = cuerpo["items"]
    assert comentario["tipo"] == "COMENTARIO"
    assert comentario["comentario_id"] is not None
    assert estado["tipo"] == "ESTADO"
    assert estado["estado_nuevo"] == "EN_REVISION"
    assert estado["reclamo_id"] == reclamo_id
    assert estado["leida"] is False
    assert "destinatario_id" not in estado


async def test_el_operador_no_ve_las_notificaciones_del_vecino(
    client: AsyncClient, auth, token_ciudadano, token_operador
) -> None:
    await preparar_por_http(client, auth, token_ciudadano, token_operador)

    respuesta = await client.get("/api/v1/notificaciones", headers=auth(token_operador))

    assert respuesta.json()["total"] == 0
    assert respuesta.json()["unread_count"] == 0


async def test_leer_una_baja_el_contador(
    client: AsyncClient, auth, token_ciudadano, token_operador
) -> None:
    await preparar_por_http(client, auth, token_ciudadano, token_operador)
    lista = await client.get("/api/v1/notificaciones", headers=auth(token_ciudadano))
    primera = lista.json()["items"][0]["id"]

    leida = await client.patch(
        f"/api/v1/notificaciones/{primera}/leer", headers=auth(token_ciudadano)
    )
    conteo = await client.get("/api/v1/notificaciones/conteo", headers=auth(token_ciudadano))
    no_leidas = await client.get(
        "/api/v1/notificaciones", params={"unread_only": True}, headers=auth(token_ciudadano)
    )

    assert leida.status_code == 200
    assert leida.json()["leida"] is True
    assert leida.json()["leida_at"] is not None
    assert conteo.json() == {"unread_count": 1}
    assert primera not in [n["id"] for n in no_leidas.json()["items"]]
    assert no_leidas.json()["total"] == 1


async def test_leer_la_notificacion_de_otro_da_404(
    client: AsyncClient, auth, token_ciudadano, token_operador, token_otro_ciudadano
) -> None:
    await preparar_por_http(client, auth, token_ciudadano, token_operador)
    lista = await client.get("/api/v1/notificaciones", headers=auth(token_ciudadano))
    ajena = lista.json()["items"][0]["id"]

    respuesta = await client.patch(
        f"/api/v1/notificaciones/{ajena}/leer", headers=auth(token_otro_ciudadano)
    )
    inexistente = await client.patch(
        f"/api/v1/notificaciones/{uuid.uuid4()}/leer", headers=auth(token_otro_ciudadano)
    )

    # Same answer as a notification that does not exist: nothing is revealed.
    assert respuesta.status_code == 404
    assert respuesta.json()["code"] == "notificacion_no_encontrada"
    assert inexistente.status_code == 404


async def test_leer_todas_marca_solo_las_propias_y_es_idempotente(
    client: AsyncClient, auth, token_ciudadano, token_operador, token_otro_ciudadano
) -> None:
    await preparar_por_http(client, auth, token_ciudadano, token_operador)

    ajena = await client.post(
        "/api/v1/notificaciones/leer-todas", headers=auth(token_otro_ciudadano)
    )
    primera = await client.post("/api/v1/notificaciones/leer-todas", headers=auth(token_ciudadano))
    segunda = await client.post("/api/v1/notificaciones/leer-todas", headers=auth(token_ciudadano))

    assert ajena.json() == {"marcadas": 0, "unread_count": 0}
    assert primera.json() == {"marcadas": 2, "unread_count": 0}
    assert segunda.json() == {"marcadas": 0, "unread_count": 0}


async def test_la_paginacion_respeta_el_orden(
    client: AsyncClient, auth, token_ciudadano, token_operador
) -> None:
    await preparar_por_http(client, auth, token_ciudadano, token_operador)
    todas = await client.get("/api/v1/notificaciones", headers=auth(token_ciudadano))
    pagina_2 = await client.get(
        "/api/v1/notificaciones", params={"page": 2, "size": 1}, headers=auth(token_ciudadano)
    )

    assert pagina_2.json()["total"] == 2
    assert [n["id"] for n in pagina_2.json()["items"]] == [todas.json()["items"][1]["id"]]


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [
        ("get", "/api/v1/notificaciones"),
        ("get", "/api/v1/notificaciones/conteo"),
        ("post", "/api/v1/notificaciones/leer-todas"),
        ("patch", f"/api/v1/notificaciones/{uuid.uuid4()}/leer"),
    ],
)
async def test_las_notificaciones_requieren_login(
    client: AsyncClient, metodo: str, ruta: str
) -> None:
    respuesta = await client.request(metodo.upper(), ruta)
    assert respuesta.status_code == 401
