"""Road incidents from Emergencies, and the claim's link to one (ADR 0017).

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "incidentes_viales",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("incidente_origen_id", sa.String(length=64), nullable=False),
        sa.Column("tipo", sa.String(length=80), nullable=True),
        sa.Column("severidad", sa.String(length=40), nullable=True),
        sa.Column("barrio", sa.String(length=120), nullable=True),
        sa.Column("latitud", sa.Float(), nullable=False),
        sa.Column("longitud", sa.Float(), nullable=False),
        sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fin", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_incidentes_viales"),
        sa.UniqueConstraint("incidente_origen_id", name="uq_incidentes_viales_origen"),
    )
    op.create_index("ix_incidentes_viales_inicio_fin", "incidentes_viales", ["inicio", "fin"])

    op.add_column("reclamos", sa.Column("incidente_id", sa.Uuid(), nullable=True))
    op.create_index("ix_reclamos_incidente_id", "reclamos", ["incidente_id"])
    op.create_foreign_key(
        "fk_reclamos_incidente_id",
        "reclamos",
        "incidentes_viales",
        ["incidente_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # The table lives in `public` and Supabase's anon key is public: without RLS
    # anyone could read it. Same rule as every other table in this schema.
    op.execute("ALTER TABLE incidentes_viales ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_constraint("fk_reclamos_incidente_id", "reclamos", type_="foreignkey")
    op.drop_index("ix_reclamos_incidente_id", table_name="reclamos")
    op.drop_column("reclamos", "incidente_id")

    op.drop_index("ix_incidentes_viales_inicio_fin", table_name="incidentes_viales")
    op.drop_table("incidentes_viales")
