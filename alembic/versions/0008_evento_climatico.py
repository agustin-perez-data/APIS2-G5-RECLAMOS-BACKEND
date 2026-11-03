"""Weather alert mode: alerts, processed events and the marks on claims

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-03

Squad 3, "weather alert" (ADR 0014). Public Spaces publishes
`CriticidadClimaticaConfirmada` with the points they consulted and a severity
level; we work out the affected area, mark the open claims in it and raise their
priority while the alert lasts.

`eventos_climaticos` keeps the alert because it spans time: it arrives
confirmed, becomes active at `vigencia_desde` and ends when they say so, and
when it ends we have to find the claims it marked. Its primary key is Public
Spaces' own `alerta_id`, so a redelivered event cannot store the same alert
twice.

`eventos_procesados` is the persistent dedup the module did not have. Delivery
is at least once -- the gateway's own README says events may arrive duplicated
-- and handling a confirmation notifies every affected neighbour, so a
redelivery would notify all of them a second time.

The two columns on `reclamos` are nullable: every claim filed before this
migration, and every claim outside any alert, simply has none. **No foreign key
on `alerta_id`** on purpose, unlike `actividad_id` in 0007: the alert is another
module's record and an alert we never received must never stop a neighbour from
filing a claim.

RLS goes on for both new tables (see 0002): they live in `public` and Supabase's
anon key is public by design. `reclamos` already has it since 0002.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NIVELES = ("BAJA", "MEDIA", "ALTA", "CRITICA")
ESTADOS = ("CONFIRMADA", "ACTIVA", "FINALIZADA")
MOTIVOS = ("NORMAL", "ADHESIONES", "ALERTA")


def _varchar_enum(valores: tuple[str, ...], nombre: str) -> sa.Enum:
    # VARCHAR and not a native type, as in every other enum here (see
    # app/db/types.py): SQLite runs the test suite and a native ENUM would need
    # an ALTER TYPE on each change.
    return sa.Enum(*valores, name=nombre, native_enum=False, length=32)


def upgrade() -> None:
    op.create_table(
        "eventos_climaticos",
        sa.Column("alerta_id", sa.Uuid(), nullable=False),
        sa.Column("nivel", _varchar_enum(NIVELES, "nivel_criticidad"), nullable=False),
        sa.Column("fenomeno", sa.String(length=40), nullable=False),
        sa.Column("ubicaciones", sa.JSON(), nullable=False),
        sa.Column("vigencia_desde", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vigencia_hasta", sa.DateTime(timezone=True), nullable=False),
        sa.Column("estado", _varchar_enum(ESTADOS, "estado_evento_climatico"), nullable=False),
        sa.Column("ultimo_occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("alerta_id", name="pk_eventos_climaticos"),
    )
    op.create_index(
        "ix_eventos_climaticos_estado_vigencia",
        "eventos_climaticos",
        ["estado", "vigencia_desde"],
    )
    op.execute("ALTER TABLE eventos_climaticos ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "eventos_procesados",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("tipo", sa.String(length=120), nullable=False),
        sa.Column("procesado_en", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id", name="pk_eventos_procesados"),
    )
    op.execute("ALTER TABLE eventos_procesados ENABLE ROW LEVEL SECURITY")

    op.add_column("reclamos", sa.Column("alerta_id", sa.Uuid(), nullable=True))
    op.create_index("ix_reclamos_alerta_id", "reclamos", ["alerta_id"])
    op.add_column(
        "reclamos",
        sa.Column("motivo_prioridad", _varchar_enum(MOTIVOS, "motivo_prioridad"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reclamos", "motivo_prioridad")
    op.drop_index("ix_reclamos_alerta_id", table_name="reclamos")
    op.drop_column("reclamos", "alerta_id")

    op.drop_table("eventos_procesados")

    op.drop_index("ix_eventos_climaticos_estado_vigencia", table_name="eventos_climaticos")
    op.drop_table("eventos_climaticos")
