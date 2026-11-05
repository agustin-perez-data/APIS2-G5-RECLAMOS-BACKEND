"""Registration and login of the neighbours this module authenticates."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import CuentaInactiva, EmailNoRegistrado, EmailYaRegistrado
from app.core.logging import get_logger
from app.core.security import emitir_token_ciudadano
from app.db.base import utcnow
from app.db.models import Ciudadano
from app.repositories.ciudadano_repository import CiudadanoRepository
from app.schemas.auth import LoginCiudadano, RegistroCiudadano

log = get_logger(__name__)


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

        ciudadano = Ciudadano(
            email=email,
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

        if ciudadano is None:
            log.warning("auth.ciudadano.login_fallido", motivo="email_no_registrado")
            raise EmailNoRegistrado()

        if not ciudadano.activo:
            log.warning(
                "auth.ciudadano.login_fallido",
                motivo="cuenta_inactiva",
                ciudadano_id=str(ciudadano.id),
            )
            raise CuentaInactiva()

        ciudadano.ultimo_acceso_at = utcnow()
        await self.session.commit()
        await self.session.refresh(ciudadano)

        log.info("auth.ciudadano.login", ciudadano_id=str(ciudadano.id))
        return ciudadano

    def emitir_token(self, ciudadano: Ciudadano) -> tuple[str, int]:
        return emitir_token_ciudadano(ciudadano.id, ciudadano.email, ciudadano.nombre)
