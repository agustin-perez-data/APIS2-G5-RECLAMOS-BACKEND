"""Cross-cutting schemas: pagination and error format.

Field descriptions stay in Spanish on purpose: they end up in the OpenAPI page
that the front end and the other teams read.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Standard paginated response for the whole API."""

    items: list[T]
    total: int = Field(description="Cantidad total de registros que matchean el filtro")
    page: int = Field(ge=1)
    size: int = Field(ge=1)

    @property
    def pages(self) -> int:
        return (self.total + self.size - 1) // self.size if self.size else 0


class ProblemDetail(BaseModel):
    """Error body as defined by RFC 7807 (application/problem+json)."""

    type: str = Field(default="about:blank", description="Identificador del tipo de error")
    # Same value as the last segment of `type`, but on its own field: the client
    # compares it directly instead of parsing a URL.
    code: str = Field(description="Codigo estable del error, para discriminar en el cliente")
    title: str
    status: int
    detail: str | None = None
    instance: str | None = Field(default=None, description="Path del request que fallo")
    errors: list[dict] | None = Field(
        default=None, description="Detalle campo a campo en errores de validacion"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "type": "https://citypass.local/errors/transicion_invalida",
                "code": "transicion_invalida",
                "title": "Transicion de estado invalida",
                "status": 409,
                "detail": "No se puede pasar de RESUELTO a ASIGNADO",
                "instance": "/api/v1/reclamos/6f1c.../estado",
            }
        }
    }
