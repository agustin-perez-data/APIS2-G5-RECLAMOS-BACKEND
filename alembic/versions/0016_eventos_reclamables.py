"""Replace finished reservations with claimable public events.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Renombrar la tabla anterior y su clave primaria.
    op.rename_table("eventos_finalizados", "eventos_reclamables")
    op.alter_column(
        "eventos_reclamables",
        "reserva_id",
        new_column_name="evento_id",
    )
    op.execute(
        "ALTER TABLE eventos_reclamables "
        "RENAME CONSTRAINT pk_eventos_finalizados TO pk_eventos_reclamables"
    )

    # Permitir eventos cancelados recibidos antes de su publicación.
    op.alter_column(
        "eventos_reclamables",
        "fin_ms",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.add_column(
        "eventos_reclamables",
        sa.Column(
            "cancelado",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Cambiar la referencia del reclamo.
    op.alter_column(
        "reclamos",
        "reserva_id",
        new_column_name="evento_id",
    )
    op.drop_index("ix_reclamos_reserva_id", table_name="reclamos")
    op.create_index(
        "ix_reclamos_evento_id",
        "reclamos",
        ["evento_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_reclamos_evento_id", table_name="reclamos")
    op.alter_column(
        "reclamos",
        "evento_id",
        new_column_name="reserva_id",
    )
    op.create_index(
        "ix_reclamos_reserva_id",
        "reclamos",
        ["reserva_id"],
    )

    op.drop_column("eventos_reclamables", "cancelado")
    op.alter_column(
        "eventos_reclamables",
        "fin_ms",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.execute(
        "ALTER TABLE eventos_reclamables "
        "RENAME CONSTRAINT pk_eventos_reclamables TO pk_eventos_finalizados"
    )
    op.alter_column(
        "eventos_reclamables",
        "evento_id",
        new_column_name="reserva_id",
    )
    op.rename_table("eventos_reclamables", "eventos_finalizados")
