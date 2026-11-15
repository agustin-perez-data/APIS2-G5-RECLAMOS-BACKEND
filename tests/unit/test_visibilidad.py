"""What each kind of user may see of a claim (ADR 0020)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.api.visibilidad import (
    NOMBRE_MUNICIPIO,
    comentarios_visibles,
    historial_visible,
    reclamo_visible,
)
from app.core.security import CurrentUser, Roles
from app.domain.enums import USUARIO_MUNICIPIO, USUARIO_SISTEMA, EstadoReclamo
from app.schemas.reclamo import ComentarioOut, HistorialOut, ReclamoDetalle, ReclamoOut

DUENO = "vecino-dueno"
OTRO = "vecino-ajeno"
OPERADOR = "U000016"
AHORA = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
RECLAMO_ID = uuid.uuid4()


def usuario(identificador: str, *roles: str) -> CurrentUser:
    return CurrentUser(id=identificador, nombre=identificador, roles=frozenset(roles))


VECINO_DUENO = usuario(DUENO, Roles.CIUDADANO)
VECINO_AJENO = usuario(OTRO, Roles.CIUDADANO)
STAFF = usuario(OPERADOR, Roles.OPERADOR)


def entrada(autor: str, estado: EstadoReclamo) -> HistorialOut:
    return HistorialOut(
        id=uuid.uuid4(),
        estado_anterior=None,
        estado_nuevo=estado,
        motivo="motivo",
        usuario_id=autor,
        created_at=AHORA,
    )


def comentario(autor: str, *, oficial: bool, nombre: str | None = None) -> ComentarioOut:
    return ComentarioOut(
        id=uuid.uuid4(),
        reclamo_id=RECLAMO_ID,
        autor_id=autor,
        autor_nombre=nombre,
        texto="texto",
        es_oficial=oficial,
        created_at=AHORA,
    )


def detalle() -> ReclamoDetalle:
    return ReclamoDetalle(
        id=RECLAMO_ID,
        ciudadano_id=DUENO,
        titulo="Luminaria apagada",
        descripcion="No enciende hace una semana",
        categoria="ALUMBRADO",
        prioridad="MEDIA",
        estado="ASIGNADO",
        origen_clasificacion="MODELO",
        confianza_clasificacion=0.9,
        objeto_afectado=None,
        canal="APP",
        direccion=None,
        barrio="Centro",
        latitud=None,
        longitud=None,
        fotos=[],
        asignado_a=OPERADOR,
        area_responsable="Alumbrado publico",
        resolucion=None,
        adhesiones_count=0,
        correlation_id="corr-123",
        ticket_externo="REC-12",
        created_at=AHORA,
        updated_at=AHORA,
        resuelto_at=None,
        cerrado_at=None,
        historial=[
            entrada(DUENO, EstadoReclamo.RECIBIDO),
            entrada(OPERADOR, EstadoReclamo.ASIGNADO),
            entrada(USUARIO_SISTEMA, EstadoReclamo.CERRADO),
        ],
        comentarios=[
            comentario(OPERADOR, oficial=True, nombre="operador-rec"),
            comentario(OTRO, oficial=False, nombre="Otro vecino"),
            comentario(USUARIO_SISTEMA, oficial=True),
        ],
    )


# --- staff -------------------------------------------------------------------


def test_el_personal_ve_todo() -> None:
    original = detalle()

    assert reclamo_visible(original, STAFF) is original


@pytest.mark.parametrize("rol", [Roles.OPERADOR, Roles.ADMIN])
def test_operador_y_admin_son_personal(rol: str) -> None:
    visto = reclamo_visible(detalle(), usuario("alguien", rol))

    assert visto.asignado_a == OPERADOR
    assert visto.historial[1].usuario_id == OPERADOR
    assert visto.comentarios[0].autor_nombre == "operador-rec"


# --- the owner ---------------------------------------------------------------


def test_el_dueno_conserva_sus_identificadores_pero_no_ve_quien_lo_atiende() -> None:
    visto = reclamo_visible(detalle(), VECINO_DUENO)

    assert visto.ticket_externo == "REC-12"
    assert visto.correlation_id == "corr-123"
    assert visto.asignado_a is None
    # Which area has it is not internal: that is what the neighbour is told.
    assert visto.area_responsable == "Alumbrado publico"


# --- another neighbour -------------------------------------------------------


def test_otro_vecino_no_ve_identificadores_internos() -> None:
    visto = reclamo_visible(detalle(), VECINO_AJENO)

    assert visto.asignado_a is None
    assert visto.ticket_externo is None
    assert visto.correlation_id is None


def test_lo_demas_del_reclamo_sigue_a_la_vista() -> None:
    original = detalle()
    visto = reclamo_visible(original, VECINO_AJENO)

    ocultos = {"asignado_a", "ticket_externo", "correlation_id", "historial", "comentarios"}
    assert visto.model_dump(exclude=ocultos) == original.model_dump(exclude=ocultos)


# --- history -----------------------------------------------------------------


@pytest.mark.parametrize("vecino", [VECINO_DUENO, VECINO_AJENO])
def test_en_el_historial_el_personal_figura_como_municipio(vecino: CurrentUser) -> None:
    visto = reclamo_visible(detalle(), vecino)

    assert [e.usuario_id for e in visto.historial] == [DUENO, USUARIO_MUNICIPIO, USUARIO_SISTEMA]
    # Only the author changes: what happened and why stays as it was.
    assert [e.estado_nuevo for e in visto.historial] == [
        EstadoReclamo.RECIBIDO,
        EstadoReclamo.ASIGNADO,
        EstadoReclamo.CERRADO,
    ]
    assert all(e.motivo == "motivo" for e in visto.historial)


def test_el_historial_suelto_aplica_la_misma_regla() -> None:
    entradas = detalle().historial

    assert [e.usuario_id for e in historial_visible(entradas, VECINO_AJENO, DUENO)] == [
        DUENO,
        USUARIO_MUNICIPIO,
        USUARIO_SISTEMA,
    ]
    assert historial_visible(entradas, STAFF, DUENO) == entradas


# --- comments ----------------------------------------------------------------


def test_un_comentario_oficial_lo_firma_el_municipio() -> None:
    oficial, de_vecino, automatico = comentarios_visibles(detalle().comentarios, VECINO_AJENO)

    assert (oficial.autor_id, oficial.autor_nombre) == (USUARIO_MUNICIPIO, NOMBRE_MUNICIPIO)
    assert oficial.es_oficial is True
    assert oficial.texto == "texto"
    # A neighbour's comment keeps its author...
    assert (de_vecino.autor_id, de_vecino.autor_nombre) == (OTRO, "Otro vecino")
    # ...and so does the system's, which the client renders differently.
    assert automatico.autor_id == USUARIO_SISTEMA


def test_el_personal_ve_quien_escribio_cada_comentario() -> None:
    comentarios = detalle().comentarios

    assert comentarios_visibles(comentarios, STAFF) == comentarios


# --- safety ------------------------------------------------------------------


def test_ocultar_no_modifica_el_original() -> None:
    original = detalle()

    reclamo_visible(original, VECINO_AJENO)

    assert original.asignado_a == OPERADOR
    assert original.ticket_externo == "REC-12"
    assert original.historial[1].usuario_id == OPERADOR
    assert original.comentarios[0].autor_nombre == "operador-rec"


def test_el_esquema_sin_historial_tambien_se_filtra() -> None:
    simple = ReclamoOut.model_validate(detalle().model_dump(exclude={"historial", "comentarios"}))

    visto = reclamo_visible(simple, VECINO_AJENO)

    assert type(visto) is ReclamoOut
    assert visto.asignado_a is None
    assert visto.ticket_externo is None
