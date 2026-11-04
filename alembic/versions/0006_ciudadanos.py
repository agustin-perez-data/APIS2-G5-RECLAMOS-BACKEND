"""Accounts for the neighbours this module authenticates

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-25

Group 2's Federated Login authenticates municipal staff only, so the people who
file claims need an account here (see ADR 0011). The id is a UUID: it travels as
the token's `sub` and lands in `reclamos.ciudadano_id`, where it has to stay
impossible to confuse with the IdP's `U000042`.

No foreign key from `reclamos.ciudadano_id`: that column holds three kinds of
value at once - a local UUID, an IdP `sub` for staff actions, and "sistema" for
claims opened by another module's event - so a constraint would force inventing
phantom rows for the last two.

RLS goes on here as well (see 0002): the table lives in `public` and Supabase's
anon key is public by design, so without it anyone holding that key could read
the password hashes straight through the REST API.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ciudadanos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("ultimo_acceso_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ciudadanos"),
        sa.UniqueConstraint("email", name="uq_ciudadanos_email"),
    )
    op.create_index("ix_ciudadanos_created_at", "ciudadanos", ["created_at"])
    op.execute("ALTER TABLE ciudadanos ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_ciudadanos_created_at", table_name="ciudadanos")
    op.drop_table("ciudadanos")
