"""Registration and login of the neighbours this module authenticates."""

from __future__ import annotations

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import CredencialesInvalidas, EmailYaRegistrado
from app.core.logging import get_logger
from app.core.passwords import hash_password, necesita_rehash, verificar_password
from app.core.security import emitir_token_ciudadano
from app.db.base import utcnow
from app.db.models import Ciudadano
from app.repositories.ciudadano_repository import CiudadanoRepository
from app.schemas.auth import LoginCiudadano, RegistroCiudadano

log = get_logger(__name__)

# Verified when the email is unknown so a failed login takes the same time
# whether or not the account exists. Without it the response time is a directory
# of who registered.
_HASH_SENUELO = hash_password("senuelo-para-igualar-los-tiempos")


def normalizar_email(email: str) -> str:
    return email.strip().lower()


class CiudadanoService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CiudadanoRepository(session)

    async def registrar(self, datos: RegistroCiudadano) -> Ciudadano:
        email = normalizar_email(str(datos.email))
        if await self.repo.por_email(email) is not None:
            raise EmailYaRegistrado()

        # Hashing is CPU-bound and deliberately slow, so it cannot run inside
        # the event loop (see the rule in CLAUDE.md).
        password_hash = await anyio.to_thread.run_sync(hash_password, datos.password)
        ciudadano = Ciudadano(
            email=email,
            password_hash=password_hash,
            nombre=datos.nombre.strip(),
        )
        await self.repo.agregar(ciudadano)
        await self.session.commit()
        await self.session.refresh(ciudadano)

        log.info("auth.ciudadano.registrado", ciudadano_id=str(ciudadano.id))
        return ciudadano

    async def autenticar(self, datos: LoginCiudadano) -> Ciudadano:
        email = normalizar_email(str(datos.email))
        ciudadano = await self.repo.por_email(email)

        almacenado = ciudadano.password_hash if ciudadano is not None else _HASH_SENUELO
        coincide = await anyio.to_thread.run_sync(verificar_password, datos.password, almacenado)
        if ciudadano is None or not coincide or not ciudadano.activo:
            log.warning("auth.ciudadano.login_fallido")
            raise CredencialesInvalidas()

        ciudadano.ultimo_acceso_at = utcnow()
        # The only moment the plain password is available, so it is the only
        # moment a stronger hash can be applied without asking for a reset.
        if necesita_rehash(ciudadano.password_hash):
            ciudadano.password_hash = await anyio.to_thread.run_sync(hash_password, datos.password)
            log.info("auth.ciudadano.rehash", ciudadano_id=str(ciudadano.id))
        await self.session.commit()
        await self.session.refresh(ciudadano)

        log.info("auth.ciudadano.login", ciudadano_id=str(ciudadano.id))
        return ciudadano

    def emitir_token(self, ciudadano: Ciudadano) -> tuple[str, int]:
        return emitir_token_ciudadano(ciudadano.id, ciudadano.email, ciudadano.nombre)
