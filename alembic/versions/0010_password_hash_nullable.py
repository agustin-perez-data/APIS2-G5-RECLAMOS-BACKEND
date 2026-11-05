"""Hace password_hash nullable en la tabla ciudadanos

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-04

Fase 1 de la transicion de autenticacion de ciudadanos sin contrasena.
Permite valores NULL en la columna password_hash para que el nuevo codigo
pueda registrar ciudadanos sin contrasena manteniendo compatibilidad con
versiones anteriores durante el despliegue.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "ciudadanos",
        "password_hash",
        existing_type=sa.String(length=255),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "ciudadanos",
        "password_hash",
        existing_type=sa.String(length=255),
        nullable=False,
    )
