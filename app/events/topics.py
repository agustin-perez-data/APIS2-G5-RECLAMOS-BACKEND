"""Catalogue of CityPass+ bus topics.

Naming convention agreed with Group 1 (EDA): `<module>.<aggregate>.<fact>`, in
lowercase, with the fact in past tense. The message key is always the aggregate
id, so every event about the same claim lands on the same partition and keeps
its ordering.
"""

from __future__ import annotations

# --- Published by this module ------------------------------------------------
RECLAMO_CREADO = "reclamos.reclamo.creado"
RECLAMO_CLASIFICADO = "reclamos.reclamo.clasificado"
RECLAMO_ESTADO_CAMBIADO = "reclamos.reclamo.estado-cambiado"
RECLAMO_RESUELTO = "reclamos.reclamo.resuelto"
RECLAMO_ADHERIDO = "reclamos.reclamo.adherido"

# Our own dead letter queue: incoming messages we could not process.
DLQ = "reclamos.dlq"

# --- Consumed from other modules ---------------------------------------------
RESIDUOS_CONTENEDOR_DESBORDADO = "residuos.contenedor.desbordado"
EMERGENCIAS_INCIDENTE_CREADO = "emergencias.incidente.creado"
ESPACIOS_RESERVA_CREADA = "espacios.reserva.creada"

PUBLICADOS: tuple[str, ...] = (
    RECLAMO_CREADO,
    RECLAMO_CLASIFICADO,
    RECLAMO_ESTADO_CAMBIADO,
    RECLAMO_RESUELTO,
    RECLAMO_ADHERIDO,
)

CONSUMIDOS: tuple[str, ...] = (
    RESIDUOS_CONTENEDOR_DESBORDADO,
    EMERGENCIAS_INCIDENTE_CREADO,
)
