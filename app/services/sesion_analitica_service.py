"""Lifecycle of revocable Analytics sessions, independent of HTTP and cookies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.analitica_auth import autenticar_admin_analitica
from app.core.analitica_session_crypto import (
    AnaliticaSessionCrypto,
    hash_identificador,
    nuevo_identificador,
)
from app.core.config import Settings, settings
from app.core.exceptions import SesionAnaliticaConflicto, SesionAnaliticaInvalida
from app.core.security import CurrentUser
from app.db.base import utcnow
from app.db.models.sesion_analitica import SesionAnalitica
from app.repositories.sesion_analitica_repository import SesionAnaliticaRepository


@dataclass(frozen=True, slots=True)
class SesionAnaliticaCreada:
    identificador: str = field(repr=False)
    usuario_id: str
    vence_at: datetime


@dataclass(frozen=True, slots=True)
class SesionAnaliticaVigente:
    usuario: CurrentUser
    token_humano: str = field(repr=False)
    vence_at: datetime


class SesionAnaliticaService:
    def __init__(
        self,
        session: AsyncSession,
        cfg: Settings | None = None,
        *,
        reloj: Callable[[], datetime] = utcnow,
    ) -> None:
        self.session = session
        self.repo = SesionAnaliticaRepository(session)
        self.cfg = cfg or settings
        self.reloj = reloj
        if self.cfg.analitica_session_key is None:
            raise ValueError("Falta ANALITICA_SESSION_KEY para las sesiones de Analitica")
        self.crypto = AnaliticaSessionCrypto(self.cfg.analitica_session_key.get_secret_value())

    async def crear(self, token: str, *, anterior: str | None = None) -> SesionAnaliticaCreada:
        usuario = autenticar_admin_analitica(token, self.cfg)
        ahora = self.reloj().astimezone(UTC)
        vence_jwt = datetime.fromtimestamp(float(usuario.claims["exp"]), UTC)
        vence_at = min(
            ahora + timedelta(seconds=min(self.cfg.analitica_session_ttl_seconds, 300)), vence_jwt
        )
        if vence_at <= ahora:
            raise SesionAnaliticaInvalida()
        identificador = nuevo_identificador()
        verificador = hash_identificador(identificador)
        sesion = SesionAnalitica(
            identificador_hash=verificador,
            usuario_id=usuario.id,
            token_cifrado=self.crypto.cifrar(token, verificador),
            vence_at=vence_at,
        )
        try:
            if anterior is not None:
                consumida = await self.repo.consumir(hash_identificador(anterior), ahora)
                if consumida is None:
                    raise SesionAnaliticaConflicto()
            await self.repo.agregar(sesion)
            await self.session.commit()
        except BaseException:
            await self.session.rollback()
            raise
        return SesionAnaliticaCreada(identificador, usuario.id, vence_at)

    async def obtener(
        self, identificador: str, *, usuario_id: str | None = None
    ) -> SesionAnaliticaVigente:
        verificador = hash_identificador(identificador)
        sesion = await self.repo.obtener(verificador)
        # SQLite strips tzinfo; PostgreSQL returns UTC-aware values.
        if sesion is None or sesion.vence_at.replace(tzinfo=UTC) <= self.reloj().astimezone(UTC):
            raise SesionAnaliticaInvalida()
        if usuario_id is not None and sesion.usuario_id != usuario_id:
            raise SesionAnaliticaConflicto()
        token = self.crypto.descifrar(sesion.token_cifrado, verificador)
        usuario = autenticar_admin_analitica(token, self.cfg)
        if usuario.id != sesion.usuario_id:
            raise SesionAnaliticaInvalida()
        return SesionAnaliticaVigente(usuario, token, sesion.vence_at.replace(tzinfo=UTC))

    async def revocar(self, identificador: str) -> bool:
        try:
            eliminada = await self.repo.eliminar(hash_identificador(identificador))
            await self.session.commit()
            return eliminada
        except BaseException:
            await self.session.rollback()
            raise

    async def limpiar_expiradas(self) -> int:
        try:
            eliminadas = await self.repo.eliminar_expiradas(self.reloj())
            await self.session.commit()
            return eliminadas
        except BaseException:
            await self.session.rollback()
            raise
