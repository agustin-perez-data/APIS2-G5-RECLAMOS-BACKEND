"""Opt-in migration and race tests against a disposable local PostgreSQL database.

PG_ANALITICA_TEST_URL must name a local g5d466_analitica_test* database.
This module migrates that database up and down; never point it at shared data.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import SesionAnaliticaConflicto, SesionAnaliticaInvalida
from app.db.models.sesion_analitica import SesionAnalitica
from app.services.sesion_analitica_service import SesionAnaliticaCreada, SesionAnaliticaService
from tests.analitica_helpers import entorno_federado, firmar

URL_POSTGRES = os.getenv("PG_ANALITICA_TEST_URL")
pytestmark = pytest.mark.skipif(not URL_POSTGRES, reason="PG_ANALITICA_TEST_URL no configurada")


def _entorno(url: str) -> dict[str, str]:
    return os.environ | {
        "DATABASE_URL": url,
        "ENVIRONMENT": "test",
        "KAFKA_ENABLED": "false",
        "GATEWAY_ENABLED": "false",
        "BUS_KAFKA_ENABLED": "false",
        "ANALITICA_ENABLED": "false",
        "JIRA_ENABLED": "false",
        "JWT_ALGORITHM": "HS256",
    }


def _alembic(url: str, *argumentos: str) -> None:
    resultado = subprocess.run(
        [sys.executable, "-m", "alembic", *argumentos],
        env=_entorno(url),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr


@pytest.fixture(scope="module")
def pg_url():
    assert URL_POSTGRES is not None
    partes = urlsplit(URL_POSTGRES)
    assert partes.hostname in {"localhost", "127.0.0.1"}
    assert partes.path.lstrip("/").startswith("g5d466_analitica_test")
    _alembic(URL_POSTGRES, "upgrade", "head")
    yield URL_POSTGRES
    _alembic(URL_POSTGRES, "downgrade", "base")


@pytest_asyncio.fixture
async def motor(pg_url):
    engine = create_async_engine(pg_url)
    yield engine
    async with engine.begin() as conexion:
        await conexion.execute(text("DELETE FROM sesiones_analitica"))
    await engine.dispose()


async def test_migracion_crea_rls_indice_y_downgrade_reversible(motor, pg_url):
    async with motor.connect() as conexion:
        assert await conexion.scalar(text("SELECT version_num FROM alembic_version")) == "0014"
        assert await conexion.scalar(
            text("SELECT relrowsecurity FROM pg_class WHERE oid='sesiones_analitica'::regclass")
        )
        assert (
            await conexion.scalar(
                text("SELECT count(*) FROM pg_policies WHERE tablename='sesiones_analitica'")
            )
            == 0
        )
        assert (
            await conexion.scalar(
                text(
                    "SELECT count(*) FROM pg_indexes "
                    "WHERE indexname='ix_sesiones_analitica_vence_at'"
                )
            )
            == 1
        )
    await asyncio.to_thread(_alembic, pg_url, "downgrade", "0013")
    async with motor.connect() as conexion:
        assert await conexion.scalar(text("SELECT to_regclass('sesiones_analitica')")) is None
    await asyncio.to_thread(_alembic, pg_url, "upgrade", "head")


async def test_solo_un_proceso_puede_rotar_la_misma_sesion(motor, monkeypatch):
    cfg, clave = entorno_federado(monkeypatch)
    token = firmar(cfg, clave)
    fabrica = async_sessionmaker(motor, expire_on_commit=False)
    async with fabrica() as conexion:
        anterior = await SesionAnaliticaService(conexion, cfg).crear(token)
    barrera = asyncio.Barrier(2)

    async def rotar():
        async with fabrica() as conexion:
            await barrera.wait()
            return await SesionAnaliticaService(conexion, cfg).crear(
                token, anterior=anterior.identificador
            )

    resultados = await asyncio.wait_for(
        asyncio.gather(rotar(), rotar(), return_exceptions=True), timeout=15
    )
    ganadoras = [r for r in resultados if isinstance(r, SesionAnaliticaCreada)]
    assert len(ganadoras) == 1
    assert sum(isinstance(r, SesionAnaliticaConflicto) for r in resultados) == 1
    async with fabrica() as conexion:
        servicio = SesionAnaliticaService(conexion, cfg)
        with pytest.raises(SesionAnaliticaInvalida):
            await servicio.obtener(anterior.identificador)
        assert (await servicio.obtener(ganadoras[0].identificador)).token_humano == token
        assert await conexion.scalar(select(func.count()).select_from(SesionAnalitica)) == 1


async def test_revocaciones_concurrentes_son_idempotentes(motor, monkeypatch):
    cfg, clave = entorno_federado(monkeypatch)
    fabrica = async_sessionmaker(motor, expire_on_commit=False)
    async with fabrica() as conexion:
        creada = await SesionAnaliticaService(conexion, cfg).crear(firmar(cfg, clave))

    async def revocar():
        async with fabrica() as conexion:
            return await SesionAnaliticaService(conexion, cfg).revocar(creada.identificador)

    resultados = await asyncio.wait_for(asyncio.gather(revocar(), revocar()), timeout=15)
    assert sorted(resultados) == [False, True]


async def test_otro_proceso_puede_revocar_la_sesion(motor, pg_url, monkeypatch):
    cfg, clave = entorno_federado(monkeypatch)
    fabrica = async_sessionmaker(motor, expire_on_commit=False)
    async with fabrica() as conexion:
        creada = await SesionAnaliticaService(conexion, cfg).crear(firmar(cfg, clave))
    codigo = """
import asyncio, os
from app.db.session import SessionLocal, cerrar_engine
from app.services.sesion_analitica_service import SesionAnaliticaService

async def main():
    async with SessionLocal() as session:
        assert await SesionAnaliticaService(session).revocar(os.environ['TEST_SESSION_ID'])
    await cerrar_engine()

asyncio.run(main())
"""
    # Secrets go through the child environment, never the command line or output.
    entorno = _entorno(pg_url) | {
        "ANALITICA_SESSION_KEY": cfg.analitica_session_key.get_secret_value(),
        "TEST_SESSION_ID": creada.identificador,
    }
    resultado = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-c", codigo],
        env=entorno,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert resultado.returncode == 0, "The isolated revocation process failed"
    async with fabrica() as conexion:
        with pytest.raises(SesionAnaliticaInvalida):
            await SesionAnaliticaService(conexion, cfg).obtener(creada.identificador)
