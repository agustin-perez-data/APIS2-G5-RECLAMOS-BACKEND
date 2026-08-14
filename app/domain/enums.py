"""The vocabulary of the claims domain.

These values are part of the public contract: they travel over the REST API and
inside event payloads, so changing one means versioning the contract.
"""

from __future__ import annotations

from enum import StrEnum


class EstadoReclamo(StrEnum):
    RECIBIDO = "RECIBIDO"
    EN_REVISION = "EN_REVISION"
    ASIGNADO = "ASIGNADO"
    EN_PROCESO = "EN_PROCESO"
    RESUELTO = "RESUELTO"
    RECHAZADO = "RECHAZADO"
    CERRADO = "CERRADO"


class PrioridadReclamo(StrEnum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"
    CRITICA = "CRITICA"


class CategoriaReclamo(StrEnum):
    ALUMBRADO = "ALUMBRADO"
    BACHES = "BACHES"
    RESIDUOS = "RESIDUOS"
    ARBOLADO = "ARBOLADO"
    AGUA_CLOACAS = "AGUA_CLOACAS"
    TRANSITO = "TRANSITO"
    RUIDOS = "RUIDOS"
    ESPACIOS_PUBLICOS = "ESPACIOS_PUBLICOS"
    SEGURIDAD = "SEGURIDAD"
    OTROS = "OTROS"


class OrigenClasificacion(StrEnum):
    """Who decided the claim's category and priority."""

    CIUDADANO = "CIUDADANO"
    MODELO = "MODELO"
    OPERADOR = "OPERADOR"


class CanalOrigen(StrEnum):
    """How the claim entered the system."""

    APP = "APP"
    WEB = "WEB"
    TELEFONO = "TELEFONO"
    PRESENCIAL = "PRESENCIAL"
    EVENTO = "EVENTO"  # opened automatically by another module's event


# States that accept no further changes.
ESTADOS_FINALES: frozenset[EstadoReclamo] = frozenset(
    {EstadoReclamo.CERRADO, EstadoReclamo.RECHAZADO}
)

# The claim's state machine. Any transition outside this map is rejected with
# `TransicionInvalida` (see `app/services/reclamo_service.py`).
TRANSICIONES_VALIDAS: dict[EstadoReclamo, frozenset[EstadoReclamo]] = {
    EstadoReclamo.RECIBIDO: frozenset(
        {EstadoReclamo.EN_REVISION, EstadoReclamo.ASIGNADO, EstadoReclamo.RECHAZADO}
    ),
    EstadoReclamo.EN_REVISION: frozenset(
        {EstadoReclamo.ASIGNADO, EstadoReclamo.RECHAZADO, EstadoReclamo.RECIBIDO}
    ),
    EstadoReclamo.ASIGNADO: frozenset({EstadoReclamo.EN_PROCESO, EstadoReclamo.RECHAZADO}),
    EstadoReclamo.EN_PROCESO: frozenset({EstadoReclamo.RESUELTO, EstadoReclamo.ASIGNADO}),
    EstadoReclamo.RESUELTO: frozenset({EstadoReclamo.CERRADO, EstadoReclamo.EN_PROCESO}),
    EstadoReclamo.RECHAZADO: frozenset(),
    EstadoReclamo.CERRADO: frozenset(),
}

# Ranking so priorities can be compared and escalated.
ORDEN_PRIORIDAD: dict[PrioridadReclamo, int] = {
    PrioridadReclamo.BAJA: 0,
    PrioridadReclamo.MEDIA: 1,
    PrioridadReclamo.ALTA: 2,
    PrioridadReclamo.CRITICA: 3,
}


def puede_transicionar(actual: EstadoReclamo, nuevo: EstadoReclamo) -> bool:
    return nuevo in TRANSICIONES_VALIDAS.get(actual, frozenset())


def escalar(actual: PrioridadReclamo, minima: PrioridadReclamo) -> PrioridadReclamo:
    """Return the higher of `actual` and `minima`; never lowers a priority."""
    return actual if ORDEN_PRIORIDAD[actual] >= ORDEN_PRIORIDAD[minima] else minima
