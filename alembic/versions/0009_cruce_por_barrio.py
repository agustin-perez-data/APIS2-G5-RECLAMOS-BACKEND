"""Weather alert: cross by neighbourhood, with geography as the fallback

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-04

Adjusts 0008 to the contract Public Spaces finally confirmed. 0008 is already
applied in production, so this corrects it forward instead of being edited.

**What changed in the contract.** Their event does carry `barrios`: Didier works
out the affected ones and sends them. So the cross stops being geographic and
becomes primary by neighbourhood -- `reclamos.barrio_codigo` against the alert's
list -- with the radius over `ubicaciones` left as the fallback for when the
list arrives empty. Knowing which neighbourhoods are affected beats estimating
an area from a single point.

`barrio_codigo` is `barrio` normalised (upper case, no accents, collapsed
whitespace). It exists as a column, and not as a function applied on each query,
so the filter runs on an index. The free text the neighbour typed is left
untouched: it is what the claim shows, and normalising is for comparing, not for
correcting.

The existing claims are backfilled here. The SQL only handles case, whitespace
and the five accented vowels -- enough for the data that is already there -- and
from now on the column is written by `app/domain/barrios.py`, which also
preserves the N with tilde.

**`motivo_prioridad` goes away.** 0008 created it and the feature ended up not
using it: Analytics gets its number from the summary event instead, so the
column would have stayed empty forever. It is dropped while it is still empty.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MOTIVOS = ("NORMAL", "ADHESIONES", "ALERTA")

# Postgres has `unaccent`, but it needs an extension that Supabase does not
# enable by default, and this runs once over a handful of rows.
_SIN_TILDES = "barrio"
for _con, _sin in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
    _SIN_TILDES = f"replace({_SIN_TILDES}, '{_con}', '{_sin}')"


def upgrade() -> None:
    op.add_column("reclamos", sa.Column("barrio_codigo", sa.String(length=120), nullable=True))
    op.create_index("ix_reclamos_barrio_codigo", "reclamos", ["barrio_codigo"])

    # Backfill: every claim already filed keeps working with the new cross.
    # `regexp_replace` collapses runs of whitespace, which `trim` alone does not:
    # without it "Villa   Crespo" would be backfilled as "VILLA   CRESPO" while
    # `normalizar_barrio` writes "VILLA CRESPO" from now on, and the two would
    # never match each other.
    op.execute(
        f"""
        UPDATE reclamos
           SET barrio_codigo = upper(trim(regexp_replace({_SIN_TILDES}, '\\s+', ' ', 'g')))
         WHERE barrio IS NOT NULL
           AND trim(barrio) <> ''
        """
    )

    op.add_column(
        "eventos_climaticos",
        sa.Column("barrios", sa.JSON(), nullable=False, server_default="[]"),
    )

    op.drop_column("reclamos", "motivo_prioridad")


def downgrade() -> None:
    op.add_column(
        "reclamos",
        sa.Column(
            "motivo_prioridad",
            sa.Enum(*MOTIVOS, name="motivo_prioridad", native_enum=False, length=32),
            nullable=True,
        ),
    )
    op.drop_column("eventos_climaticos", "barrios")
    op.drop_index("ix_reclamos_barrio_codigo", table_name="reclamos")
    op.drop_column("reclamos", "barrio_codigo")
