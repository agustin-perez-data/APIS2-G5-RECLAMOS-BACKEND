"""What each kind of user gets to see of a claim (ADR 0020).

Reading a claim is open to any authenticated user on purpose: a neighbour has
to see other people's claims to endorse them instead of filing a duplicate.
What is not open is the municipality's internal side of it:

* **Who on the staff touched the claim.** The operator's identity is internal;
  official comments are signed by the city, not by a person. No neighbour sees
  it, not even the owner of the claim.
* **Internal identifiers** (issue-tracker key, correlation id). The owner may
  need them to follow up; anybody else has no use for them.

Staff see everything. The functions here take the response schemas, never the
ORM objects, so nothing they blank out can end up written to the database.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from app.core.security import CurrentUser
from app.domain.enums import USUARIO_MUNICIPIO, USUARIO_SISTEMA
from app.schemas.reclamo import ComentarioOut, HistorialOut, ReclamoDetalle, ReclamoOut

NOMBRE_MUNICIPIO = "El municipio"

R = TypeVar("R", bound=ReclamoOut)


def _es_del_personal(autor_id: str, ciudadano_id: str) -> bool:
    """A history entry is written by the claim's owner, the system or the staff."""
    return autor_id not in (ciudadano_id, USUARIO_SISTEMA)


def historial_visible(
    historial: Sequence[HistorialOut], usuario: CurrentUser, ciudadano_id: str
) -> list[HistorialOut]:
    if usuario.es_staff:
        return list(historial)
    return [
        entrada.model_copy(update={"usuario_id": USUARIO_MUNICIPIO})
        if _es_del_personal(entrada.usuario_id, ciudadano_id)
        else entrada
        for entrada in historial
    ]


def comentarios_visibles(
    comentarios: Sequence[ComentarioOut], usuario: CurrentUser
) -> list[ComentarioOut]:
    if usuario.es_staff:
        return list(comentarios)
    return [
        comentario.model_copy(
            update={"autor_id": USUARIO_MUNICIPIO, "autor_nombre": NOMBRE_MUNICIPIO}
        )
        # The system's own comments keep their author: the client tells them
        # apart by it, and there is no person behind them to protect.
        if comentario.es_oficial and comentario.autor_id != USUARIO_SISTEMA
        else comentario
        for comentario in comentarios
    ]


def reclamo_visible(reclamo: R, usuario: CurrentUser) -> R:
    """The claim as `usuario` may see it. Returns a copy; staff get it untouched."""
    if usuario.es_staff:
        return reclamo

    cambios: dict[str, object] = {"asignado_a": None}
    if reclamo.ciudadano_id != usuario.id:
        cambios["ticket_externo"] = None
        cambios["correlation_id"] = None
    if isinstance(reclamo, ReclamoDetalle):
        cambios["historial"] = historial_visible(reclamo.historial, usuario, reclamo.ciudadano_id)
        cambios["comentarios"] = comentarios_visibles(reclamo.comentarios, usuario)
    return reclamo.model_copy(update=cambios)
