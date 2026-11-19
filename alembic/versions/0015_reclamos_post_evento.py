"""Claims over an event that already ended: finished reservations and `reserva_id`.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eventos_finalizados",
        sa.Column("reserva_id", sa.String(64), nullable=False),
        sa.Column("fin_ms", sa.BigInteger(), nullable=False),
        sa.Column("recibido_en", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("reserva_id", name="pk_eventos_finalizados"),
    )
    op.execute("ALTER TABLE eventos_finalizados ENABLE ROW LEVEL SECURITY")
    op.add_column("reclamos", sa.Column("reserva_id", sa.String(64), nullable=True))
    op.create_index("ix_reclamos_reserva_id", "reclamos", ["reserva_id"])


def downgrade() -> None:
    op.drop_index("ix_reclamos_reserva_id", table_name="reclamos")
    op.drop_column("reclamos", "reserva_id")
    op.drop_table("eventos_finalizados")
