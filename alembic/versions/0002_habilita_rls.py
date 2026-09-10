"""Enable row level security on every table

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-10

Supabase exposes the `public` schema through its REST API (PostgREST) and
grants full privileges on it to the `anon` and `authenticated` roles. The anon
key is public by design, so with RLS off anyone holding it could read, modify
or truncate these tables without going through this service.

Turning RLS on with no policies denies everything to those roles. The service
is unaffected: it connects as `postgres`, which owns the tables and has
BYPASSRLS. Nothing here mentions Supabase's roles, so the migration also runs
on the plain PostgreSQL the CI uses.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# alembic_version lives in `public` too: left open, anyone could delete the row
# and break every future migration.
TABLAS = (
    "reclamos",
    "reclamo_historial",
    "reclamo_comentarios",
    "reclamo_adhesiones",
    "alembic_version",
)


def upgrade() -> None:
    for tabla in TABLAS:
        op.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for tabla in TABLAS:
        op.execute(f"ALTER TABLE {tabla} DISABLE ROW LEVEL SECURITY")
