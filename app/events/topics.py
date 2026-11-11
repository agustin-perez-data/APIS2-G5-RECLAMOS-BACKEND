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
RECLAMO_RECLASIFICADO = "reclamos.reclamo.reclasificado"
RECLAMO_ESTADO_CAMBIADO = "reclamos.reclamo.estado-cambiado"
RECLAMO_RESUELTO = "reclamos.reclamo.resuelto"
RECLAMO_ADHERIDO = "reclamos.reclamo.adherido"
RECLAMO_COMENTARIO_CREADO = "reclamos.reclamo.comentario-creado"

# Our own dead letter queue: incoming messages we could not process.
DLQ = "reclamos.dlq"

# --- Consumed from other modules ---------------------------------------------
RESIDUOS_CONTENEDOR_DESBORDADO = "residuos.contenedor.desbordado"
EMERGENCIAS_INCIDENTE_CREADO = "emergencias.incidente.creado"
EMERGENCIAS_INCIDENTE_ACTUALIZADO = "emergencias.incidente.actualizado"
ESPACIOS_RESERVA_CREADA = "espacios.reserva.creada"
ESPACIOS_EVENTO_PUBLICADO = "espacios.evento.publicado"
ESPACIOS_INTERVENCION_FINALIZADA = "espacios.intervencion.finalizada"
# Squad 3 (ADR 0013): a mass activity whose area relates the claims filed there.
ESPACIOS_ACTIVIDAD_CREADA = "espacios.actividad.creada"
# Squad 3 (ADR 0018): cancelled or suspended, it stops relating new claims.
ESPACIOS_ACTIVIDAD_MODIFICADA = "espacios.actividad.modificada"
CLIMA_APLICADA = "reclamos.clima.aplicada"
CLIMA_LEVANTADA = "reclamos.clima.levantada"
ESPACIOS_CLIMA_CONFIRMADA = "espacios.clima.confirmada"
ESPACIOS_CLIMA_FINALIZADA = "espacios.clima.finalizada"

# --- CityPass+ gateway event types (CU-INT-01) -------------------------------
# What arrives by webhook, mapped to the internal topic whose handler runs it.
GATEWAY_A_TOPIC: dict[str, str] = {
    "com.citypass.residuos.AlertaGenerada": RESIDUOS_CONTENEDOR_DESBORDADO,
    "com.citypass.emergencias.EmergenciaCreada": EMERGENCIAS_INCIDENTE_CREADO,
    "com.citypass.emergencias.EmergenciaActualizada": EMERGENCIAS_INCIDENTE_ACTUALIZADO,
    "com.citypass.espacios.EventoComunitarioPublicado": ESPACIOS_EVENTO_PUBLICADO,
    "com.citypass.espacios.IntervencionFinalizada": ESPACIOS_INTERVENCION_FINALIZADA,
    "com.citypass.espacios.ActividadCreada": ESPACIOS_ACTIVIDAD_CREADA,
    "com.citypass.espacios.ActividadModificada": ESPACIOS_ACTIVIDAD_MODIFICADA,
    "com.citypass.espacios.CriticidadClimaticaConfirmada": ESPACIOS_CLIMA_CONFIRMADA,
    "com.citypass.espacios.CriticidadClimaticaFinalizada": ESPACIOS_CLIMA_FINALIZADA,
}

PUBLICADOS: tuple[str, ...] = (
    RECLAMO_CREADO,
    RECLAMO_CLASIFICADO,
    RECLAMO_RECLASIFICADO,
    RECLAMO_ESTADO_CAMBIADO,
    RECLAMO_RESUELTO,
    RECLAMO_ADHERIDO,
    RECLAMO_COMENTARIO_CREADO,
    CLIMA_APLICADA,
    CLIMA_LEVANTADA,
)

CONSUMIDOS: tuple[str, ...] = (
    RESIDUOS_CONTENEDOR_DESBORDADO,
    EMERGENCIAS_INCIDENTE_CREADO,
    ESPACIOS_EVENTO_PUBLICADO,
    ESPACIOS_INTERVENCION_FINALIZADA,
    ESPACIOS_ACTIVIDAD_CREADA,
    ESPACIOS_ACTIVIDAD_MODIFICADA,
)
