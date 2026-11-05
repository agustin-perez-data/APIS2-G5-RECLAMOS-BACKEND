"""Persistence and transaction behaviour of buscar_o_crear."""

from __future__ import annotations

import sqlite3
import uuid
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Ciudadano
from app.services.ciudadano_service import CiudadanoService, _es_email_duplicado


@pytest.mark.parametrize("activo", [True, False])
async def test_devuelve_existente_sin_modificarlo(session: AsyncSession, activo: bool) -> None:
    ciudadano = Ciudadano(email="vecina@ejemplo.com", nombre="Nombre original", activo=activo)
    session.add(ciudadano)
    await session.commit()
    await session.refresh(ciudadano)
    datos_antes = (ciudadano.id, ciudadano.nombre, ciudadano.activo, ciudadano.updated_at)

    encontrado = await CiudadanoService(session).buscar_o_crear(
        "  VECINA@EJEMPLO.COM  ", "Nombre nuevo"
    )

    assert encontrado is ciudadano
    assert (
        encontrado.id,
        encontrado.nombre,
        encontrado.activo,
        encontrado.updated_at,
    ) == datos_antes
    assert not session.is_modified(ciudadano)
    assert (await session.scalar(select(func.count()).select_from(Ciudadano))) == 1


async def test_crea_ciudadano_con_uuid_activo_y_nombre_validado(session: AsyncSession) -> None:
    ciudadano = await CiudadanoService(session).buscar_o_crear(
        "  FACUNDO@EJEMPLO.COM  ", "  Facundo Martín  "
    )

    assert isinstance(ciudadano.id, uuid.UUID)
    assert ciudadano.email == "facundo@ejemplo.com"
    assert ciudadano.nombre == "Facundo Martín"
    assert ciudadano.activo is True
    assert (
        await session.scalar(select(Ciudadano).where(Ciudadano.id == ciudadano.id))
    ) is ciudadano


@pytest.mark.parametrize("nombre", [None, "", "   "])
async def test_genera_nombre_provisional_sin_dominio(
    session: AsyncSession, nombre: str | None
) -> None:
    ciudadano = await CiudadanoService(session).buscar_o_crear("JUAN.PEREZ@GMAIL.COM", nombre)

    assert ciudadano.nombre == "Ciudadano juan.perez"
    assert "gmail.com" not in ciudadano.nombre


@pytest.mark.parametrize("email", ["invalido", "", "nombre@"])
async def test_rechaza_email_invalido(session: AsyncSession, email: str) -> None:
    with pytest.raises(ValidationError):
        await CiudadanoService(session).buscar_o_crear(email, "Nombre valido")
    assert (await session.scalar(select(func.count()).select_from(Ciudadano))) == 0


@pytest.mark.parametrize("nombre", [" X ", "A" * 121])
async def test_rechaza_nombre_invalido_al_crear(session: AsyncSession, nombre: str) -> None:
    with pytest.raises(ValidationError):
        await CiudadanoService(session).buscar_o_crear("nuevo@ejemplo.com", nombre)
    assert (await session.scalar(select(func.count()).select_from(Ciudadano))) == 0


async def test_no_confirma_la_transaccion(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    commit = AsyncMock(side_effect=AssertionError("buscar_o_crear no debe hacer commit"))
    monkeypatch.setattr(session, "commit", commit)

    ciudadano = await CiudadanoService(session).buscar_o_crear("nuevo@ejemplo.com")

    assert ciudadano.id is not None
    assert session.in_transaction()
    commit.assert_not_awaited()


async def test_recupera_email_si_la_busqueda_no_vio_al_ganador(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ganador = Ciudadano(email="misma@ejemplo.com", nombre="Nombre ganador")
    session.add(ganador)
    await session.commit()
    servicio = CiudadanoService(session)
    por_email_real = servicio.repo.por_email
    primera_busqueda = True

    async def buscar_con_carrera(email: str) -> Ciudadano | None:
        nonlocal primera_busqueda
        if primera_busqueda:
            primera_busqueda = False
            return None
        return await por_email_real(email)

    monkeypatch.setattr(servicio.repo, "por_email", buscar_con_carrera)

    encontrado = await servicio.buscar_o_crear("MISMA@EJEMPLO.COM", "Nombre perdedor")

    assert encontrado.id == ganador.id
    assert encontrado.nombre == "Nombre ganador"
    assert (await session.scalar(select(func.count()).select_from(Ciudadano))) == 1
    assert session.in_transaction()


@pytest.mark.parametrize(
    "mensaje",
    ["UNIQUE constraint failed: ciudadanos.id", "NOT NULL constraint failed: ciudadanos.nombre"],
)
async def test_no_oculta_otros_errores_de_integridad(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, mensaje: str
) -> None:
    servicio = CiudadanoService(session)
    error = IntegrityError("INSERT", {}, sqlite3.IntegrityError(mensaje))
    monkeypatch.setattr(servicio.repo, "agregar", AsyncMock(side_effect=error))

    with pytest.raises(IntegrityError) as capturado:
        await servicio.buscar_o_crear("nuevo@ejemplo.com", "Nombre valido")

    assert capturado.value is error
    assert (await session.scalar(select(func.count()).select_from(Ciudadano))) == 0


@pytest.mark.parametrize(
    ("codigo", "restriccion", "esperado"),
    [
        pytest.param("23505", "uq_ciudadanos_email", True, id="email-duplicado"),
        pytest.param("23505", "uq_ciudadanos_otro_campo", False, id="otra-restriccion-unica"),
        pytest.param("23502", "uq_ciudadanos_email", False, id="not-null"),
        pytest.param("23503", "uq_ciudadanos_email", False, id="foreign-key"),
    ],
)
def test_identifica_solo_el_email_duplicado_en_postgres(
    codigo: str, restriccion: str, esperado: bool
) -> None:
    # asyncpg expone el SQLSTATE en la excepción adaptada y la restricción en su causa.
    causa = Exception("error original de PostgreSQL")
    causa.constraint_name = restriccion
    adaptado = Exception("error adaptado por asyncpg")
    adaptado.sqlstate = codigo
    adaptado.__cause__ = causa
    error = IntegrityError("INSERT", {}, adaptado)

    assert _es_email_duplicado(error) is esperado
