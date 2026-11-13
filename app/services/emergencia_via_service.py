"""A5: file a road claim from a resolved Emergencies event.

The event handler calls this use case after closing any registered incident.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.core.logging import get_logger
from app.db.models import Reclamo
from app.domain.enums import USUARIO_SISTEMA, PrioridadReclamo
from app.events.contracts import IncidenteActualizado
from app.schemas.reclamo import ReclamoCrear
from app.services.reclamo_service import ReclamoService

log = get_logger(__name__)

TITULO_RECLAMO_VIAL = "Problema en la vía pública reportado por Emergencias"
PREFIJO_ORIGEN_EMERGENCIA = "emergencia:"
LARGO_MAXIMO_ORIGEN = 64  # reclamos.evento_origen_id
INDICE_UNICO_ORIGEN = "ix_reclamos_evento_origen_id"


def _clave_emergencia(emergencia_id: str) -> str:
    """Keep the original id readable and separate from other event id namespaces."""
    if not emergencia_id or emergencia_id != emergencia_id.strip():
        raise ValueError("La emergencia no tiene un emergenciaId valido")
    clave = f"{PREFIJO_ORIGEN_EMERGENCIA}{emergencia_id}"
    if len(clave) > LARGO_MAXIMO_ORIGEN:
        raise ValueError("emergenciaId supera el limite de evento_origen_id")
    return clave


def _es_colision_de_origen(error: IntegrityError) -> bool:
    """Recognize only PostgreSQL's unique violation for evento_origen_id."""
    # SQLAlchemy's asyncpg adapter wraps the driver error in error.orig.orig.
    # The driver exposes structured fields, unlike the localized error text.
    adaptado = error.orig
    original = getattr(adaptado, "orig", None) or adaptado
    codigo = getattr(original, "sqlstate", None) or getattr(adaptado, "sqlstate", None)
    restriccion = getattr(original, "constraint_name", None)
    return codigo == "23505" and restriccion == INDICE_UNICO_ORIGEN


async def crear_reclamo_por_emergencia_vial(
    evento: IncidenteActualizado,
    service: ReclamoService,
    *,
    correlation_id: str | None = None,
) -> Reclamo | None:
    """Create one claim per emergency, or return None when A5 does not apply.

    Missing claim data is an error only for a qualifying event. In particular,
    both coordinates must be usable; a neighbourhood alone is insufficient.
    """
    if evento.estado_nuevo != "RESUELTA" or "VIA" not in evento.causas_relacionadas:
        return None

    if evento.latitud is None or evento.longitud is None:
        raise ValueError("A5 requiere latitud y longitud validas")
    if evento.descripcion_problema is None or not evento.descripcion_problema.strip():
        raise ValueError("A5 requiere descripcionProblema")

    clave = _clave_emergencia(evento.incidente_id)
    correlacion = correlation_id if correlation_id is not None else evento.correlation_id
    if correlacion is not None and len(correlacion) > 64:
        raise ValueError("correlationId supera el limite de reclamos.correlation_id")

    datos = ReclamoCrear(
        titulo=TITULO_RECLAMO_VIAL,
        descripcion=evento.descripcion_problema,
        barrio=evento.barrio,
        latitud=evento.latitud,
        longitud=evento.longitud,
    )
    try:
        return await service.crear_desde_evento(
            datos,
            evento_id=clave,
            correlation_id=correlacion,
            ciudadano_id=USUARIO_SISTEMA,
            prioridad_minima=PrioridadReclamo.ALTA,
        )
    except IntegrityError as error:
        # Two deliveries can both pass crear_desde_evento's initial lookup.
        # The UNIQUE index selects one winner. Only that index's violation can
        # be interpreted as a duplicate; every other integrity error propagates.
        await service.session.rollback()
        if not _es_colision_de_origen(error):
            raise
        existente = await service.repo.obtener_por_evento_origen(clave)
        if existente is None:
            raise
        log.info("emergencia_via.reclamo_duplicado", emergencia_id=evento.incidente_id)
        return None
