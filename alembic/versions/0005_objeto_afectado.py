"""Urban space or asset each claim is about

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-22

Orthogonal axis to the category: the category says what happened, this says what
it happened to. It lets the mobility module subscribe to one value instead of
tracking every category that can affect a bike lane.

Nullable on purpose: claims filed before this column exists have no value, and
the citizen may leave it out. Being optional is also what keeps the event
contract on version 1.0 for the modules already consuming it.

Stored as VARCHAR like every other enum here, so adding a value later needs no
migration. No RLS statement: the column lands on an existing table, which has
row level security on since 0002.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("reclamos", sa.Column("objeto_afectado", sa.String(length=32), nullable=True))
    op.create_index("ix_reclamos_objeto_afectado", "reclamos", ["objeto_afectado"])


def downgrade() -> None:
    op.drop_index("ix_reclamos_objeto_afectado", table_name="reclamos")
    op.drop_column("reclamos", "objeto_afectado")
