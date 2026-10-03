"""HTTP contracts of the notifications inbox (ADR 0008)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import EstadoReclamo, TipoNotificacion
from app.schemas.common import Page


class NotificacionOut(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "0b7e4f7a-8a57-4d5e-a0f4-3c1a6f0d9b21",
                "tipo": "ESTADO",
                "reclamo_id": "6f1c9a4e-3c2b-4a5d-9e11-2b7d5c8a1f30",
                "titulo": "Tu reclamo pasó a En revisión",
                "mensaje": '"Luminaria apagada en la plaza" pasó de Recibido a En revisión.',
                "estado_nuevo": "EN_REVISION",
                "comentario_id": None,
                "created_at": "2026-09-24T08:59:12Z",
                "leida": False,
                "leida_at": None,
            }
        },
    )

    id: uuid.UUID
    tipo: TipoNotificacion
    reclamo_id: uuid.UUID = Field(description="Para navegar a /reclamos/{reclamo_id}")
    titulo: str
    mensaje: str
    estado_nuevo: EstadoReclamo | None = Field(
        default=None, description="Solo en las de tipo ESTADO"
    )
    comentario_id: uuid.UUID | None = Field(
        default=None, description="Solo en las de tipo COMENTARIO, para ubicar el comentario"
    )
    created_at: datetime
    leida: bool
    leida_at: datetime | None


class BandejaNotificaciones(Page[NotificacionOut]):
    unread_count: int = Field(
        description="No leidas del usuario en total, sin importar la pagina ni el filtro"
    )


class ConteoNotificaciones(BaseModel):
    unread_count: int


class LecturaMasiva(BaseModel):
    marcadas: int = Field(description="Cuantas estaban sin leer y se marcaron ahora")
    unread_count: int
