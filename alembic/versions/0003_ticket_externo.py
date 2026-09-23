"""Store the key of each claim's ticket in the issue tracker

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-23

Nullable on purpose: claims filed before the Jira integration, or while the
tracker was down, have no ticket. The UNIQUE keeps one claim per ticket.

No RLS statement here: the column lands on an existing table, which already
has row level security on since 0002.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("reclamos", sa.Column("ticket_externo", sa.String(length=64), nullable=True))
    op.create_index("ix_reclamos_ticket_externo", "reclamos", ["ticket_externo"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_reclamos_ticket_externo", table_name="reclamos")
    op.drop_column("reclamos", "ticket_externo")
