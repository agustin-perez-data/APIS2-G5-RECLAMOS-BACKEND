"""Opt-in PostgreSQL race test for A5's evento_origen_id unique index.

PG_A5_TEST_URL must point to a disposable local database: this test creates
the application's tables and leaves its claim in place.
"""

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.events import topics
from app.events.contracts import IncidenteActualizado
from app.events.producer import InMemoryEventPublisher
from app.repositories.reclamo_repository import ReclamoRepository
from app.services.emergencia_via_service import crear_reclamo_por_emergencia_vial
from app.services.reclamo_service import ReclamoService

URL_POSTGRES_A5 = os.getenv("PG_A5_TEST_URL")
pytestmark = pytest.mark.skipif(not URL_POSTGRES_A5, reason="PG_A5_TEST_URL no configurada")


class ServicioConBarrera(ReclamoService):
    def __init__(self, session, publisher, barrera: asyncio.Barrier) -> None:
        super().__init__(session, publisher)
        self.barrera = barrera

    async def crear(self, *args, **kwargs):
        # Both services have already passed crear_desde_evento's lookup.
        await self.barrera.wait()
        return await super().crear(*args, **kwargs)


@pytest.mark.asyncio
async def test_dos_entregas_concurrentes_crean_un_solo_reclamo_en_postgres() -> None:
    assert URL_POSTGRES_A5 is not None
    parsed = urlsplit(URL_POSTGRES_A5)
    assert parsed.hostname in {"127.0.0.1", "localhost"}, "La prueba requiere PostgreSQL local"
    engine = create_async_engine(URL_POSTGRES_A5)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(engine, expire_on_commit=False)
        publisher_1 = InMemoryEventPublisher()
        publisher_2 = InMemoryEventPublisher()
        barrera = asyncio.Barrier(2)
        emergencia_id = str(uuid4())
        evento = IncidenteActualizado.model_validate(
            {
                "emergenciaId": emergencia_id,
                "estadoNuevo": "RESUELTA",
                "causasRelacionadas": ["VIA"],
                "descripcionProblema": "Quedo un pozo profundo en la calzada tras la emergencia.",
                "latitud": -34.589,
                "longitud": -58.431,
            }
        )

        async with factory() as session_1, factory() as session_2:
            service_1 = ServicioConBarrera(session_1, publisher_1, barrera)
            service_2 = ServicioConBarrera(session_2, publisher_2, barrera)
            resultados = await asyncio.wait_for(
                asyncio.gather(
                    crear_reclamo_por_emergencia_vial(evento, service_1),
                    crear_reclamo_por_emergencia_vial(evento, service_2),
                ),
                timeout=15,
            )

        assert sum(resultado is not None for resultado in resultados) == 1
        assert sum(resultado is None for resultado in resultados) == 1
        async with factory() as session:
            reclamo = await ReclamoRepository(session).obtener_por_evento_origen(
                f"emergencia:{emergencia_id}"
            )
            assert reclamo is not None
        assert (
            sum(
                len(publisher.eventos_de(topics.RECLAMO_CREADO))
                for publisher in (publisher_1, publisher_2)
            )
            == 1
        )
    finally:
        await engine.dispose()
