"""Translation of exceptions into uniform HTTP responses (RFC 7807).

The whole API answers errors with the same body, so the front end and the other
modules only ever parse one shape.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import DomainError
from app.core.logging import get_logger
from app.schemas.common import ProblemDetail

log = get_logger(__name__)

BASE_TIPO_ERROR = "https://citypass.local/errors"
CONTENT_TYPE = "application/problem+json"


def _problema(
    request: Request,
    *,
    status_code: int,
    title: str,
    code: str,
    detail: str | None = None,
    errors: list[dict] | None = None,
) -> JSONResponse:
    cuerpo = ProblemDetail(
        type=f"{BASE_TIPO_ERROR}/{code}",
        title=title,
        status=status_code,
        detail=detail,
        instance=request.url.path,
        errors=errors,
    )
    return JSONResponse(
        status_code=status_code,
        content=cuerpo.model_dump(exclude_none=True),
        media_type=CONTENT_TYPE,
    )


def registrar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(request: Request, exc: DomainError) -> JSONResponse:
        return _problema(
            request,
            status_code=exc.status_code,
            title=exc.title,
            code=exc.code,
            detail=exc.detail,
        )

    @app.exception_handler(RequestValidationError)
    async def _validacion(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _problema(
            request,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Datos de entrada invalidos",
            code="validacion",
            detail="Revisar los campos indicados en `errors`",
            errors=[
                {
                    "campo": ".".join(str(p) for p in error["loc"][1:]),
                    "mensaje": error["msg"],
                    "tipo": error["type"],
                }
                for error in exc.errors()
            ],
        )

    @app.exception_handler(IntegrityError)
    async def _integridad(request: Request, exc: IntegrityError) -> JSONResponse:
        # Typically a UNIQUE violation that won the race against the service
        # layer's own check (two concurrent requests).
        log.warning("db.integrity_error", error=str(exc.orig))
        return _problema(
            request,
            status_code=status.HTTP_409_CONFLICT,
            title="Conflicto de datos",
            code="conflicto",
            detail="La operacion viola una restriccion de integridad",
        )

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException) -> JSONResponse:
        respuesta = _problema(
            request,
            status_code=exc.status_code,
            title=str(exc.detail),
            code=f"http_{exc.status_code}",
        )
        if exc.headers:
            respuesta.headers.update(exc.headers)
        return respuesta

    @app.exception_handler(Exception)
    async def _inesperado(request: Request, exc: Exception) -> JSONResponse:
        log.exception("error.inesperado", path=request.url.path)
        return _problema(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="Error interno del servidor",
            code="interno",
            # The exception detail is never leaked to the client.
            detail="Ocurrio un error inesperado. Revisar los logs del servicio.",
        )
