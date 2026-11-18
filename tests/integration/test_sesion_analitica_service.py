"""Persisted session lifecycle, with real JWT validation and no external calls."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.analitica_session_crypto import hash_identificador, nuevo_identificador
from app.core.exceptions import SesionAnaliticaConflicto, SesionAnaliticaInvalida
from app.core.security import TokenInvalido
from app.db.models.sesion_analitica import SesionAnalitica
from app.services.sesion_analitica_service import SesionAnaliticaService
from tests.analitica_helpers import entorno_federado, firmar


@pytest.fixture
def identidad(monkeypatch):
    return entorno_federado(monkeypatch)


async def test_guarda_hash_y_jwt_cifrado_y_comparte_sesiones_entre_conexiones(engine, identidad):
    cfg, clave = identidad
    token = firmar(cfg, clave)
    fabrica = async_sessionmaker(engine, expire_on_commit=False)
    async with fabrica() as conexion:
        servicio = SesionAnaliticaService(conexion, cfg)
        creada = await servicio.crear(token)
        fila = await servicio.repo.obtener(hash_identificador(creada.identificador))
        assert fila.usuario_id == creada.usuario_id
        assert fila.identificador_hash != creada.identificador
        assert token.encode() not in fila.token_cifrado
        assert creada.identificador not in repr(creada)
    async with fabrica() as otra:
        vigente = await SesionAnaliticaService(otra, cfg).obtener(creada.identificador)
        assert vigente.token_humano == token
        assert token not in repr(vigente)
        assert vigente.usuario.id == creada.usuario_id


@pytest.mark.parametrize("ttl,restante", [(300, 900), (300, 30), (20, 900)])
async def test_vence_por_ttl_o_por_jwt_lo_que_ocurra_primero(session, identidad, ttl, restante):
    cfg, clave = identidad
    cfg = cfg.model_copy(update={"analitica_session_ttl_seconds": ttl})
    ahora = datetime.now(UTC).replace(microsecond=0)
    token = firmar(cfg, clave, exp=int(ahora.timestamp()) + restante)
    reloj = [ahora]
    servicio = SesionAnaliticaService(session, cfg, reloj=lambda: reloj[0])
    creada = await servicio.crear(token)
    assert creada.vence_at == ahora + timedelta(seconds=min(ttl, restante))
    reloj[0] = creada.vence_at
    with pytest.raises(SesionAnaliticaInvalida):
        await servicio.obtener(creada.identificador)
    assert await servicio.limpiar_expiradas() == 1
    assert await servicio.limpiar_expiradas() == 0


async def test_rotar_consume_el_id_anterior_y_no_permite_reutilizarlo(session, identidad):
    cfg, clave = identidad
    servicio = SesionAnaliticaService(session, cfg)
    anterior = await servicio.crear(firmar(cfg, clave))
    nueva = await servicio.crear(firmar(cfg, clave, sub="admin-B"), anterior=anterior.identificador)
    assert nueva.identificador != anterior.identificador
    assert (await servicio.obtener(nueva.identificador)).usuario.id == "admin-B"
    with pytest.raises(SesionAnaliticaInvalida):
        await servicio.obtener(anterior.identificador)
    with pytest.raises(SesionAnaliticaConflicto):
        await servicio.crear(firmar(cfg, clave), anterior=anterior.identificador)
    assert await session.scalar(select(func.count()).select_from(SesionAnalitica)) == 1


async def test_revocacion_idempotente_visible_desde_otra_conexion(engine, identidad):
    cfg, clave = identidad
    fabrica = async_sessionmaker(engine, expire_on_commit=False)
    async with fabrica() as uno, fabrica() as dos:
        creador = SesionAnaliticaService(uno, cfg)
        lector = SesionAnaliticaService(dos, cfg)
        creada = await creador.crear(firmar(cfg, clave))
        await lector.obtener(creada.identificador)
        await dos.rollback()
        assert await creador.revocar(creada.identificador)
        with pytest.raises(SesionAnaliticaInvalida):
            await lector.obtener(creada.identificador)
        assert not await creador.revocar(creada.identificador)


async def test_aisla_usuarios_y_detecta_intercambio_de_cifrados(session, identidad):
    cfg, clave = identidad
    servicio = SesionAnaliticaService(session, cfg)
    uno = await servicio.crear(firmar(cfg, clave, sub="admin-A"))
    dos = await servicio.crear(firmar(cfg, clave, sub="admin-B"))
    with pytest.raises(SesionAnaliticaConflicto):
        await servicio.obtener(uno.identificador, usuario_id="admin-B")
    fila_uno = await servicio.repo.obtener(hash_identificador(uno.identificador))
    fila_dos = await servicio.repo.obtener(hash_identificador(dos.identificador))
    fila_uno.token_cifrado = fila_dos.token_cifrado
    await session.commit()
    with pytest.raises(SesionAnaliticaInvalida):
        await servicio.obtener(uno.identificador)
    assert (await servicio.obtener(dos.identificador)).usuario.id == "admin-B"


async def test_fallo_al_insertar_no_revoca_la_sesion_anterior(session, identidad, monkeypatch):
    cfg, clave = identidad
    servicio = SesionAnaliticaService(session, cfg)
    token = firmar(cfg, clave)
    creada = await servicio.crear(token)

    async def fallar(_sesion: SesionAnalitica) -> None:
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(servicio.repo, "agregar", fallar)
    with pytest.raises(RuntimeError):
        await servicio.crear(token, anterior=creada.identificador)
    assert (await servicio.obtener(creada.identificador)).token_humano == token


async def test_token_invalido_no_crea_ni_rota_sesiones(session, identidad):
    cfg, clave = identidad
    servicio = SesionAnaliticaService(session, cfg)
    creada = await servicio.crear(firmar(cfg, clave))
    with pytest.raises(TokenInvalido):
        await servicio.crear(firmar(cfg, clave, exp=1), anterior=creada.identificador)
    assert (await servicio.obtener(creada.identificador)).usuario.id == creada.usuario_id
    with pytest.raises(SesionAnaliticaInvalida):
        await servicio.obtener(nuevo_identificador())


async def test_revalida_el_jwt_en_cada_lectura(session, identidad):
    cfg, clave = identidad
    servicio = SesionAnaliticaService(session, cfg)
    creada = await servicio.crear(firmar(cfg, clave))
    fila = await servicio.repo.obtener(hash_identificador(creada.identificador))
    fila.token_cifrado = servicio.crypto.cifrar(firmar(cfg, clave, exp=1), fila.identificador_hash)
    await session.commit()
    with pytest.raises(TokenInvalido):
        await servicio.obtener(creada.identificador)


def test_no_arranca_el_servicio_sin_clave(session, identidad):
    cfg, _clave = identidad
    with pytest.raises(ValueError, match="ANALITICA_SESSION_KEY"):
        SesionAnaliticaService(session, cfg.model_copy(update={"analitica_session_key": None}))
