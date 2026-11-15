"""Auto-close triggered over HTTP (US-17).

In production only the API is deployed, so the scheduled workflow
`cierre-automatico.yml` calls this endpoint instead of the worker loop.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from app.domain.enums import EstadoReclamo
from app.events import topics
from app.events.producer import InMemoryEventPublisher
from app.schemas.reclamo import CambioEstado, ReclamoCrear
from app.services.reclamo_service import ReclamoService
from tests.conftest import CIUDADANO_ID

RUTA = "/api/v1/reclamos/mantenimiento/cierre-automatico"
DATOS = ReclamoCrear(
    titulo="Luminaria apagada en la plaza",
    descripcion="El foco del poste no enciende hace dos semanas y quedo todo oscuro",
)


async def _resuelto(service: ReclamoService, operador, *, hace_dias: int) -> str:
    reclamo = await service.crear(DATOS, CIUDADANO_ID)
    for estado in (EstadoReclamo.ASIGNADO, EstadoReclamo.EN_PROCESO, EstadoReclamo.RESUELTO):
        await service.cambiar_estado(reclamo.id, CambioEstado(estado=estado), operador)
    resuelto = await service.obtener(reclamo.id)
    resuelto.resuelto_at = datetime.now(UTC) - timedelta(days=hace_dias)
    await service.session.commit()
    return str(reclamo.id)


async def test_cierra_solo_los_vencidos(
    client: AsyncClient,
    auth,
    token_admin,
    service: ReclamoService,
    usuario_operador,
    publisher: InMemoryEventPublisher,
) -> None:
    vencido = await _resuelto(service, usuario_operador, hace_dias=8)
    reciente = await _resuelto(service, usuario_operador, hace_dias=2)

    respuesta = await client.post(RUTA, headers=auth(token_admin))

    assert respuesta.status_code == 200
    assert respuesta.json() == {"cerrados": 1, "reclamo_ids": [vencido]}

    estados = {
        reclamo_id: (
            await client.get(f"/api/v1/reclamos/{reclamo_id}", headers=auth(token_admin))
        ).json()["estado"]
        for reclamo_id in (vencido, reciente)
    }
    assert estados == {vencido: "CERRADO", reciente: "RESUELTO"}

    # The other modules hear about it like about any other state change.
    ultimo = publisher.eventos_de(topics.RECLAMO_ESTADO_CAMBIADO)[-1]
    assert str(ultimo.data.reclamo_id) == vencido
    assert ultimo.data.estado_nuevo is EstadoReclamo.CERRADO


async def test_el_cierre_queda_en_el_historial_a_nombre_del_sistema(
    client: AsyncClient, auth, token_admin, service: ReclamoService, usuario_operador
) -> None:
    vencido = await _resuelto(service, usuario_operador, hace_dias=8)

    await client.post(RUTA, headers=auth(token_admin))

    historial = (
        await client.get(f"/api/v1/reclamos/{vencido}/historial", headers=auth(token_admin))
    ).json()
    cierre = historial[-1]
    assert cierre["estado_nuevo"] == "CERRADO"
    # Not the admin whose token triggered the run: nobody decided this one.
    assert cierre["usuario_id"] == "sistema"
    assert "Cierre automatico" in cierre["motivo"]


async def test_una_segunda_corrida_no_encuentra_nada(
    client: AsyncClient, auth, token_admin, service: ReclamoService, usuario_operador
) -> None:
    await _resuelto(service, usuario_operador, hace_dias=8)

    primera = await client.post(RUTA, headers=auth(token_admin))
    segunda = await client.post(RUTA, headers=auth(token_admin))

    assert primera.json()["cerrados"] == 1
    assert segunda.status_code == 200
    assert segunda.json() == {"cerrados": 0, "reclamo_ids": []}


async def test_sin_nada_que_cerrar_responde_vacio(client: AsyncClient, auth, token_admin) -> None:
    respuesta = await client.post(RUTA, headers=auth(token_admin))

    assert respuesta.status_code == 200
    assert respuesta.json() == {"cerrados": 0, "reclamo_ids": []}


async def test_solo_un_admin_puede_dispararlo(
    client: AsyncClient, auth, token_ciudadano, token_operador
) -> None:
    assert (await client.post(RUTA)).status_code == 401
    assert (await client.post(RUTA, headers=auth(token_ciudadano))).status_code == 403
    assert (await client.post(RUTA, headers=auth(token_operador))).status_code == 403
