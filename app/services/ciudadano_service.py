"""Registration and login of the neighbours this module authenticates."""

from __future__ import annotations

import sqlite3

from pydantic import EmailStr, TypeAdapter
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import CuentaInactiva, EmailNoRegistrado, EmailYaRegistrado
from app.core.logging import get_logger
from app.core.security import emitir_token_ciudadano
from app.db.base import utcnow
from app.db.models import Ciudadano
from app.repositories.ciudadano_repository import CiudadanoRepository
from app.schemas.auth import LoginCiudadano, RegistroCiudadano

log = get_logger(__name__)
_email_adapter = TypeAdapter(EmailStr)


def _es_email_duplicado(error: IntegrityError) -> bool:
    """Only the unique constraint on ciudadanos.email is recoverable."""
    if isinstance(error.orig, sqlite3.IntegrityError):
        return str(error.orig) == "UNIQUE constraint failed: ciudadanos.email"

    codigos: set[str] = set()
    restricciones: set[str] = set()
    pendientes: list[BaseException] = [error.orig]
    visitados: set[int] = set()
    while pendientes:
        causa = pendientes.pop()
        if id(causa) in visitados:
            continue
        visitados.add(id(causa))
        codigo = getattr(causa, "sqlstate", None) or getattr(causa, "pgcode", None)
        if codigo:
            codigos.add(codigo)
        restriccion = getattr(causa, "constraint_name", None)
        if not restriccion:
            restriccion = getattr(getattr(causa, "diag", None), "constraint_name", None)
        if restriccion:
            restricciones.add(restriccion)
        for siguiente in (causa.__cause__, causa.__context__):
            if siguiente is not None:
                pendientes.append(siguiente)

    return codigos == {"23505"} and (
        "uq_ciudadanos_email" in restricciones or '"uq_ciudadanos_email"' in str(error.orig)
    )


def normalizar_email(email: str) -> str:
    return email.strip().lower()


class CiudadanoService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CiudadanoRepository(session)

    async def buscar_o_crear(self, email: str, nombre: str | None = None) -> Ciudadano:
        """Resolve a local citizen without committing the caller's transaction.

        Call before adding other pending objects: begin_nested flushes the session
        before opening its savepoint, even when autoflush is disabled.
        """
        email_normalizado = normalizar_email(str(_email_adapter.validate_python(email)))
        existente = await self.repo.por_email(email_normalizado)
        if existente is not None:
            return existente

        nombre_efectivo = (
            nombre
            if nombre and nombre.strip()
            else f"Ciudadano {email_normalizado.split('@', 1)[0]}"
        )
        datos = RegistroCiudadano(email=email_normalizado, nombre=nombre_efectivo)
        ciudadano = Ciudadano(email=email_normalizado, nombre=datos.nombre)

        dentro_del_savepoint = False
        try:
            async with self.session.begin_nested():
                dentro_del_savepoint = True
                await self.repo.agregar(ciudadano)
        except IntegrityError as error:
            if not dentro_del_savepoint or not _es_email_duplicado(error):
                raise
            existente = await self.repo.por_email(email_normalizado)
            if existente is None:
                raise
            return existente

        return ciudadano

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
