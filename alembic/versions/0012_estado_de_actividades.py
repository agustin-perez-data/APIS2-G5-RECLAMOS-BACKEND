"""State of a mass activity, moved by ActividadModificada (ADR 0018).

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Every activity stored so far arrived as PROGRAMADA: cancelled ones were
    # never kept, so the default is also the right value for existing rows.
    op.add_column(
        "actividades_masivas",
        sa.Column("estado", sa.String(length=20), nullable=False, server_default="PROGRAMADA"),
    )
    op.add_column(
        "actividades_masivas",
        sa.Column("estado_cambiado_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("actividades_masivas", "estado_cambiado_at")
    op.drop_column("actividades_masivas", "estado")
