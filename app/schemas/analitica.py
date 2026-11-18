"""Public iframe session metadata; never serialize session capabilities."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class EstadoSesionAnalitica(BaseModel):
    usuario_id: str
    expires_at: datetime
    estado: str = "activa"


class InicioSesionAnalitica(EstadoSesionAnalitica):
    iframe_url: str
    csrf_token: str
