"""Mass activities and the claims related to them

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-28

Squad 3, "smart collection after a mass event" (ADR 0013). Public Spaces
announces an activity with `ActividadCreada`; the mass ones are stored here, and
every claim filed near one while it lasts, or in the hours after it ends, keeps
its id in `reclamos.actividad_id`.

`actividad_origen_id` is Public Spaces' id, UNIQUE so that a redelivered event
cannot register the same activity twice.

The new column on `reclamos` is nullable - every claim filed before this
migration, and every claim far from any activity, simply has none - and the
foreign key is SET NULL: losing an activity must never take a neighbour's claim
with it.

RLS goes on for the new table (see 0002): it lives in `public`, and Supabase's
anon key is public by design. `reclamos` already has it since 0002.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "actividades_masivas",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actividad_origen_id", sa.String(length=64), nullable=False),
        sa.Column("titulo", sa.String(length=150), nullable=False),
        sa.Column("capacidad", sa.Integer(), nullable=False),
        sa.Column("latitud", sa.Float(), nullable=False),
        sa.Column("longitud", sa.Float(), nullable=False),
        sa.Column("direccion", sa.String(length=255), nullable=True),
        sa.Column("espacio_nombre", sa.String(length=150), nullable=True),
        sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fin", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_actividades_masivas"),
        sa.UniqueConstraint(
            "actividad_origen_id", name="uq_actividades_masivas_actividad_origen_id"
        ),
    )
    op.create_index("ix_actividades_masivas_inicio_fin", "actividades_masivas", ["inicio", "fin"])
    op.create_index("ix_actividades_masivas_created_at", "actividades_masivas", ["created_at"])
    op.execute("ALTER TABLE actividades_masivas ENABLE ROW LEVEL SECURITY")

    op.add_column("reclamos", sa.Column("actividad_id", sa.Uuid(), nullable=True))
    op.create_index("ix_reclamos_actividad_id", "reclamos", ["actividad_id"])
    op.create_foreign_key(
        "fk_reclamos_actividad_id_actividades_masivas",
        "reclamos",
        "actividades_masivas",
        ["actividad_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_reclamos_actividad_id_actividades_masivas", "reclamos", type_="foreignkey"
    )
    op.drop_index("ix_reclamos_actividad_id", table_name="reclamos")
    op.drop_column("reclamos", "actividad_id")

    op.drop_index("ix_actividades_masivas_created_at", table_name="actividades_masivas")
    op.drop_index("ix_actividades_masivas_inicio_fin", table_name="actividades_masivas")
    op.drop_table("actividades_masivas")
