"""Initial schema of the claims module

Revision ID: 0001
Revises:
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Domain enums are stored as VARCHAR(32): adding a new category needs no
# migration at all (see `app/db/types.py`).
ENUM = sa.String(length=32)


def upgrade() -> None:
    op.create_table(
        "reclamos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ciudadano_id", sa.String(length=128), nullable=False),
        sa.Column("canal", ENUM, nullable=False),
        sa.Column("titulo", sa.String(length=150), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column("fotos", sa.JSON(), nullable=False),
        sa.Column("categoria", ENUM, nullable=False),
        sa.Column("prioridad", ENUM, nullable=False),
        sa.Column("origen_clasificacion", ENUM, nullable=False),
        sa.Column("confianza_clasificacion", sa.Float(), nullable=True),
        sa.Column("direccion", sa.String(length=255), nullable=True),
        sa.Column("barrio", sa.String(length=120), nullable=True),
        sa.Column("latitud", sa.Float(), nullable=True),
        sa.Column("longitud", sa.Float(), nullable=True),
        sa.Column("estado", ENUM, nullable=False),
        sa.Column("asignado_a", sa.String(length=128), nullable=True),
        sa.Column("area_responsable", sa.String(length=120), nullable=True),
        sa.Column("resolucion", sa.Text(), nullable=True),
        sa.Column("resuelto_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cerrado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("adhesiones_count", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("evento_origen_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_reclamos"),
    )
    op.create_index("ix_reclamos_ciudadano_id", "reclamos", ["ciudadano_id"])
    op.create_index("ix_reclamos_categoria", "reclamos", ["categoria"])
    op.create_index("ix_reclamos_estado", "reclamos", ["estado"])
    op.create_index("ix_reclamos_barrio", "reclamos", ["barrio"])
    op.create_index("ix_reclamos_asignado_a", "reclamos", ["asignado_a"])
    op.create_index("ix_reclamos_correlation_id", "reclamos", ["correlation_id"])
    op.create_index("ix_reclamos_created_at", "reclamos", ["created_at"])
    # UNIQUE: makes consumption of other modules' events idempotent.
    op.create_index("ix_reclamos_evento_origen_id", "reclamos", ["evento_origen_id"], unique=True)
    # Composite indexes for the back-office inbox and the map view.
    op.create_index("ix_reclamos_estado_prioridad", "reclamos", ["estado", "prioridad"])
    op.create_index("ix_reclamos_categoria_estado", "reclamos", ["categoria", "estado"])

    op.create_table(
        "reclamo_historial",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reclamo_id", sa.Uuid(), nullable=False),
        sa.Column("estado_anterior", ENUM, nullable=True),
        sa.Column("estado_nuevo", ENUM, nullable=False),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("usuario_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["reclamo_id"],
            ["reclamos.id"],
            name="fk_reclamo_historial_reclamo_id_reclamos",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reclamo_historial"),
    )
    op.create_index("ix_reclamo_historial_reclamo_id", "reclamo_historial", ["reclamo_id"])

    op.create_table(
        "reclamo_comentarios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reclamo_id", sa.Uuid(), nullable=False),
        sa.Column("autor_id", sa.String(length=128), nullable=False),
        sa.Column("autor_nombre", sa.String(length=150), nullable=True),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("es_oficial", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["reclamo_id"],
            ["reclamos.id"],
            name="fk_reclamo_comentarios_reclamo_id_reclamos",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reclamo_comentarios"),
    )
    op.create_index("ix_reclamo_comentarios_reclamo_id", "reclamo_comentarios", ["reclamo_id"])

    op.create_table(
        "reclamo_adhesiones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reclamo_id", sa.Uuid(), nullable=False),
        sa.Column("ciudadano_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["reclamo_id"],
            ["reclamos.id"],
            name="fk_reclamo_adhesiones_reclamo_id_reclamos",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reclamo_adhesiones"),
        # One endorsement per citizen per claim.
        sa.UniqueConstraint("reclamo_id", "ciudadano_id", name="uq_adhesion_reclamo_ciudadano"),
    )
    op.create_index("ix_reclamo_adhesiones_reclamo_id", "reclamo_adhesiones", ["reclamo_id"])
    op.create_index("ix_reclamo_adhesiones_ciudadano_id", "reclamo_adhesiones", ["ciudadano_id"])


def downgrade() -> None:
    op.drop_table("reclamo_adhesiones")
    op.drop_table("reclamo_comentarios")
    op.drop_table("reclamo_historial")
    op.drop_table("reclamos")
