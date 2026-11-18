"""`scripts/ensayar_alerta.py`: rehearsing a weather alert without the bus.

The script exists so a demo can be rehearsed alone. What must hold is that it
does what the real event does, and that it cannot be pointed at real neighbours
by accident: the `.env` of this repository may point at production.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import EventoClimatico, Reclamo
from app.domain.enums import EstadoEventoClimatico, NivelCriticidad
from app.events import topics

RAIZ = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "ensayar_alerta", RAIZ / "scripts" / "ensayar_alerta.py"
)
ensayar_alerta = importlib.util.module_from_spec(_spec)
sys.modules["ensayar_alerta"] = ensayar_alerta
_spec.loader.exec_module(ensayar_alerta)


@pytest.fixture
def sesiones(engine):
    fabrica = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def abrir():
        async with fabrica() as sesion:
            yield sesion

    return abrir


@pytest.mark.parametrize(
    ("url", "local"),
    [
        ("sqlite+aiosqlite:///ensayo.sqlite", True),
        ("sqlite+aiosqlite:///:memory:", True),
        ("postgresql+asyncpg://u:p@localhost:5432/reclamos", True),
        ("postgresql+asyncpg://u:p@127.0.0.1:5432/reclamos", True),
        ("postgresql+asyncpg://u:p@db.abcdefgh.supabase.co:5432/postgres", False),
        ("postgresql+asyncpg://u:p@aws-0-us-east-1.pooler.supabase.com:6543/postgres", False),
        # A name that merely contains the word must not pass.
        ("postgresql+asyncpg://u:p@localhost.ejemplo.com:5432/reclamos", False),
    ],
)
def test_solo_una_base_de_esta_maquina_es_local(url: str, local: bool) -> None:
    assert ensayar_alerta.es_base_local(url) is local


def test_se_niega_a_correr_contra_una_base_remota(capsys) -> None:
    codigo = ensayar_alerta.main(
        ["confirmar"], url="postgresql+asyncpg://u:p@db.abcdefgh.supabase.co:5432/postgres"
    )

    assert codigo == 2
    salida = capsys.readouterr().out
    assert "db.abcdefgh.supabase.co" in salida
    # The credentials of the URL are never echoed.
    assert "u:p" not in salida


async def test_la_semilla_carga_reclamos_en_varios_barrios(sesiones, publisher, session) -> None:
    creados = await ensayar_alerta.sembrar(sesiones, publisher)

    assert len(creados) == len(ensayar_alerta.SEMILLA)
    assert {r.barrio for r in creados} == {"Palermo", "Belgrano", "Caballito"}
    assert (await session.execute(select(func.count()).select_from(Reclamo))).scalar() == len(
        creados
    )


async def test_confirmar_marca_los_reclamos_del_area_y_no_los_de_afuera(
    sesiones, publisher, session
) -> None:
    await ensayar_alerta.sembrar(sesiones, publisher)

    resumen = await ensayar_alerta.confirmar(
        sesiones, publisher, nivel=NivelCriticidad.ALTA, barrios=["Palermo", "Belgrano"]
    )

    en_el_area = sum(1 for _, _, _, barrio in ensayar_alerta.SEMILLA if barrio != "Caballito")
    assert resumen["reclamos_marcados"] == en_el_area
    marcados = (
        (await session.execute(select(Reclamo).where(Reclamo.alerta_id.is_not(None))))
        .scalars()
        .all()
    )
    assert {r.barrio for r in marcados} == {"Palermo", "Belgrano"}
    assert len(publisher.eventos_de(topics.CLIMA_APLICADA)) == 1


async def test_la_alerta_ensayada_esta_en_vigencia(sesiones, publisher, session) -> None:
    """Otherwise the handler would store it and do nothing else."""
    resumen = await ensayar_alerta.confirmar(
        sesiones, publisher, nivel=NivelCriticidad.MEDIA, barrios=["Palermo"], horas=2
    )

    from app.services.clima_service import ClimaService

    vigentes = await ClimaService(session).vigentes()
    assert [a.alerta_id for a in vigentes] == [resumen["alerta_id"]]


async def test_finalizar_sin_id_cierra_la_ultima_abierta(sesiones, publisher, session) -> None:
    await ensayar_alerta.sembrar(sesiones, publisher)
    confirmada = await ensayar_alerta.confirmar(
        sesiones, publisher, nivel=NivelCriticidad.ALTA, barrios=["Palermo"]
    )

    resumen = await ensayar_alerta.finalizar(sesiones, publisher)

    assert resumen is not None and resumen["alerta_id"] == confirmada["alerta_id"]
    # Open before the alert, so none of them was filed during it.
    assert resumen["reclamos_creados_durante"] == 0
    assert resumen["reclamos_abiertos_al_confirmar"] == confirmada["reclamos_marcados"]
    alerta = await session.get(EventoClimatico, confirmada["alerta_id"])
    await session.refresh(alerta)
    assert alerta.estado is EstadoEventoClimatico.FINALIZADA
    assert len(publisher.eventos_de(topics.CLIMA_LEVANTADA)) == 1


async def test_finalizar_sin_alertas_abiertas_no_hace_nada(sesiones, publisher) -> None:
    assert await ensayar_alerta.finalizar(sesiones, publisher) is None
    assert publisher.publicados == []


async def test_finalizar_una_alerta_que_no_existe_lo_dice(sesiones, publisher) -> None:
    resumen = await ensayar_alerta.finalizar(sesiones, publisher, alerta_id=uuid.uuid4())

    assert resumen is not None and "detalle" in resumen
