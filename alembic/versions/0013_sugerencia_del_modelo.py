"""Keep what the classifier suggested, so its accuracy can be measured (ADR 0019).

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All nullable and with no backfill: for the claims filed before this
    # migration the original suggestion was already overwritten by any
    # reclassification, so there is nothing true to put there.
    op.add_column("reclamos", sa.Column("categoria_sugerida", sa.String(length=40), nullable=True))
    op.add_column("reclamos", sa.Column("confianza_sugerida", sa.Float(), nullable=True))
    op.add_column("reclamos", sa.Column("modelo_clasificador", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("reclamos", "modelo_clasificador")
    op.drop_column("reclamos", "confianza_sugerida")
    op.drop_column("reclamos", "categoria_sugerida")
