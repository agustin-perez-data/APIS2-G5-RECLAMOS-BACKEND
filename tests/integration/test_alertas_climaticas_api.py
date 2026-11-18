"""`GET /alertas-climaticas/activas`: what the operator's panel shows (ADR 0014).

"Active" is narrower than "not finished". The point of these tests is the three
alerts that are stored, are not finished, and still must not be shown.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from app.db.models import EventoClimatico
from app.domain.enums import EstadoEventoClimatico, NivelCriticidad

RUTA = "/api/v1/alertas-climaticas/activas"


def _alerta(
    *,
    desde: timedelta,
    hasta: timedelta,
    estado: EstadoEventoClimatico = EstadoEventoClimatico.CONFIRMADA,
    nivel: NivelCriticidad = NivelCriticidad.ALTA,
) -> EventoClimatico:
    ahora = datetime.now(UTC)
    return EventoClimatico(
        alerta_id=uuid.uuid4(),
        nivel=nivel,
        fenomeno="TORMENTA_FUERTE",
        barrios=["PALERMO", "BELGRANO"],
        ubicaciones=[],
        vigencia_desde=ahora + desde,
        vigencia_hasta=ahora + hasta,
        estado=estado,
    )


async def test_muestra_la_alerta_en_vigencia(
    client: AsyncClient, auth, token_operador, session
) -> None:
    vigente = _alerta(desde=timedelta(hours=-1), hasta=timedelta(hours=5))
    session.add(vigente)
    await session.commit()

    respuesta = await client.get(RUTA, headers=auth(token_operador))

    assert respuesta.status_code == 200
    (alerta,) = respuesta.json()
    assert alerta["alerta_id"] == str(vigente.alerta_id)
    assert alerta["nivel"] == "ALTA"
    assert alerta["fenomeno"] == "TORMENTA_FUERTE"
    assert alerta["barrios"] == ["PALERMO", "BELGRANO"]
    assert alerta["estado"] == "CONFIRMADA"
    # With an offset: without it the panel would read the hour as local time.
    assert datetime.fromisoformat(alerta["vigencia_hasta"]).tzinfo is not None


async def test_no_muestra_las_que_no_rigen(
    client: AsyncClient, auth, token_operador, session
) -> None:
    vigente = _alerta(desde=timedelta(hours=-1), hasta=timedelta(hours=5))
    session.add_all(
        [
            vigente,
            # Announced for tonight: confirmed, but it has not started.
            _alerta(desde=timedelta(hours=3), hasta=timedelta(hours=9)),
            # Its window ended and the closing event never arrived.
            _alerta(desde=timedelta(days=-2), hasta=timedelta(days=-1)),
            # Closed by Public Spaces before its window ran out.
            _alerta(
                desde=timedelta(hours=-2),
                hasta=timedelta(hours=4),
                estado=EstadoEventoClimatico.FINALIZADA,
            ),
        ]
    )
    await session.commit()

    respuesta = await client.get(RUTA, headers=auth(token_operador))

    assert [a["alerta_id"] for a in respuesta.json()] == [str(vigente.alerta_id)]


async def test_sin_alertas_responde_una_lista_vacia(
    client: AsyncClient, auth, token_operador
) -> None:
    respuesta = await client.get(RUTA, headers=auth(token_operador))

    assert respuesta.status_code == 200
    assert respuesta.json() == []


async def test_es_solo_para_el_personal(client: AsyncClient, auth, token_ciudadano) -> None:
    assert (await client.get(RUTA)).status_code == 401
    assert (await client.get(RUTA, headers=auth(token_ciudadano))).status_code == 403
