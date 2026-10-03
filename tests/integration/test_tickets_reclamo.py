"""Every new claim opens a ticket, and a tracker outage never blocks the claim."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import CanalOrigen, CategoriaReclamo
from app.events.producer import InMemoryEventPublisher
from app.integrations.tickets import TicketsEnMemoria
from app.schemas.reclamo import ReclamoCrear
from app.services.reclamo_service import ReclamoService
from tests.conftest import CIUDADANO_ID, contar_reclamos


def datos_reclamo(**overrides) -> ReclamoCrear:
    base = {
        "titulo": "Luminaria apagada en la plaza",
        "descripcion": "El foco del poste no enciende hace dos semanas y quedo todo oscuro",
        "barrio": "Centro",
        "direccion": "Rivadavia 800",
    }
    base.update(overrides)
    return ReclamoCrear(**base)


async def test_al_crear_un_reclamo_se_abre_su_ticket(
    session: AsyncSession, publisher: InMemoryEventPublisher
) -> None:
    tickets = TicketsEnMemoria()
    service = ReclamoService(session, publisher, tickets=tickets)

    reclamo = await service.crear(datos_reclamo(), ciudadano_id=CIUDADANO_ID)

    assert reclamo.ticket_externo == "REC-1"
    assert len(tickets.creados) == 1
    enviado = tickets.creados[0]
    assert enviado.reclamo_id == reclamo.id
    assert enviado.categoria is CategoriaReclamo.ALUMBRADO
    assert enviado.barrio == "Centro"


async def test_la_clave_del_ticket_queda_guardada_en_la_base(
    session: AsyncSession, publisher: InMemoryEventPublisher
) -> None:
    service = ReclamoService(session, publisher, tickets=TicketsEnMemoria())
    reclamo = await service.crear(datos_reclamo(), ciudadano_id=CIUDADANO_ID)

    # Drop the cached object so the value is read back from the database.
    session.expunge_all()
    guardado = await service.obtener(reclamo.id)
    assert guardado.ticket_externo == "REC-1"


async def test_si_jira_falla_el_reclamo_se_crea_igual(
    session: AsyncSession, publisher: InMemoryEventPublisher
) -> None:
    service = ReclamoService(session, publisher, tickets=TicketsEnMemoria(falla=True))

    reclamo = await service.crear(datos_reclamo(), ciudadano_id=CIUDADANO_ID)

    # The claim is filed and announced; only the ticket is missing, and the empty
    # column is what lets someone find it and retry.
    assert await contar_reclamos(session) == 1
    assert reclamo.ticket_externo is None
    assert publisher.topics  # the creation events still went out


async def test_los_reclamos_nacidos_de_eventos_tambien_abren_ticket(
    session: AsyncSession, publisher: InMemoryEventPublisher
) -> None:
    tickets = TicketsEnMemoria()
    service = ReclamoService(session, publisher, tickets=tickets)

    reclamo = await service.crear_desde_evento(datos_reclamo(), evento_id="evt-residuos-1")

    assert reclamo is not None
    assert reclamo.ticket_externo == "REC-1"
    assert tickets.creados[0].canal is CanalOrigen.EVENTO


async def test_un_evento_repetido_no_abre_un_segundo_ticket(
    session: AsyncSession, publisher: InMemoryEventPublisher
) -> None:
    tickets = TicketsEnMemoria()
    service = ReclamoService(session, publisher, tickets=tickets)

    await service.crear_desde_evento(datos_reclamo(), evento_id="evt-residuos-1")
    await service.crear_desde_evento(datos_reclamo(), evento_id="evt-residuos-1")

    assert len(tickets.creados) == 1
