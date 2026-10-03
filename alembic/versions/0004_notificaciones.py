"""In-app notifications for the owner of a claim

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-24

A new table in `public`, so RLS goes on here as well (see 0002): without it,
anyone holding Supabase's public anon key could read every user's
notifications through the REST API.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notificaciones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("destinatario_id", sa.String(length=128), nullable=False),
        sa.Column("reclamo_id", sa.Uuid(), nullable=False),
        sa.Column("tipo", sa.String(length=32), nullable=False),
        sa.Column("referencia_id", sa.Uuid(), nullable=False),
        sa.Column("titulo", sa.String(length=150), nullable=False),
        sa.Column("mensaje", sa.Text(), nullable=False),
        sa.Column("datos", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("leida_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["reclamo_id"],
            ["reclamos.id"],
            name="fk_notificaciones_reclamo_id_reclamos",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notificaciones"),
        sa.UniqueConstraint(
            "destinatario_id", "tipo", "referencia_id", name="uq_notificacion_referencia"
        ),
    )
    op.create_index("ix_notificaciones_reclamo_id", "notificaciones", ["reclamo_id"])
    op.create_index(
        "ix_notificaciones_destinatario_fecha", "notificaciones", ["destinatario_id", "created_at"]
    )
    op.create_index(
        "ix_notificaciones_destinatario_leida", "notificaciones", ["destinatario_id", "leida_at"]
    )
    op.execute("ALTER TABLE notificaciones ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("notificaciones")
