"""Store short-lived Analytics sessions with encrypted JWTs and RLS.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sesiones_analitica",
        sa.Column("identificador_hash", sa.String(64), nullable=False),
        sa.Column("usuario_id", sa.String(255), nullable=False),
        sa.Column("token_cifrado", sa.LargeBinary(), nullable=False),
        sa.Column("vence_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("identificador_hash", name="pk_sesiones_analitica"),
    )
    op.create_index("ix_sesiones_analitica_vence_at", "sesiones_analitica", ["vence_at"])
    op.execute("ALTER TABLE sesiones_analitica ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_sesiones_analitica_vence_at", table_name="sesiones_analitica")
    op.drop_table("sesiones_analitica")
