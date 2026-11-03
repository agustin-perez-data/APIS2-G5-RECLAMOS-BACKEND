"""Domain exceptions.

The service and repository layers raise these; the HTTP layer turns them into
RFC 7807 responses in `app/api/errors.py`. That way the domain never has to
know FastAPI exists.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for every business error in this module."""

    status_code: int = 400
    title: str = "Error de negocio"
    code: str = "domain_error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.title
        super().__init__(self.detail)


class ReclamoNoEncontrado(DomainError):
    status_code = 404
    title = "Reclamo no encontrado"
    code = "reclamo_no_encontrado"


class TransicionInvalida(DomainError):
    status_code = 409
    title = "Transicion de estado invalida"
    code = "transicion_invalida"


class AdhesionDuplicada(DomainError):
    status_code = 409
    title = "El ciudadano ya adhirio a este reclamo"
    code = "adhesion_duplicada"


class AdhesionDelAutor(DomainError):
    status_code = 422
    title = "El autor no puede adherir a su propio reclamo"
    code = "adhesion_del_autor"


class ReclamoCerrado(DomainError):
    status_code = 409
    title = "El reclamo esta cerrado y no admite modificaciones"
    code = "reclamo_cerrado"


class NotificacionNoEncontrada(DomainError):
    # Also raised for someone else's notification: a 403 would confirm it exists.
    status_code = 404
    title = "Notificacion no encontrada"
    code = "notificacion_no_encontrada"


class PermisoDenegado(DomainError):
    status_code = 403
    title = "No tiene permisos sobre este recurso"
    code = "permiso_denegado"


class EmailYaRegistrado(DomainError):
    status_code = 409
    title = "Ese email ya tiene una cuenta"
    code = "email_ya_registrado"


class CredencialesInvalidas(DomainError):
    # Deliberately the same answer for a password that does not match, an email
    # that was never registered and a disabled account: telling them apart
    # turns the login into a directory of who is registered.
    status_code = 401
    title = "Email o contrasena incorrectos"
    code = "credenciales_invalidas"
