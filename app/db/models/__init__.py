"""ORM models. Import them from here so Alembic sees the full metadata."""

from app.db.base import Base
from app.db.models.adhesion import Adhesion
from app.db.models.comentario import Comentario
from app.db.models.historial import HistorialEstado
from app.db.models.reclamo import Reclamo

__all__ = ["Adhesion", "Base", "Comentario", "HistorialEstado", "Reclamo"]
