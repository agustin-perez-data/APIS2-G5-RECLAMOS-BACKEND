"""Rehearse a weather alert without the bus (ADR 0014).

    python scripts/ensayar_alerta.py semilla
    python scripts/ensayar_alerta.py confirmar --nivel ALTA --barrios "Palermo,Belgrano" --horas 6
    python scripts/ensayar_alerta.py finalizar
    python scripts/ensayar_alerta.py finalizar --alerta-id <uuid>

In production an alert only arrives when Public Spaces publishes
`CriticidadClimaticaConfirmada`. This builds the same envelope and hands it to
the same handlers, so a demo can be rehearsed with nobody else online.

Two things it will not do:

- **Run against a database that is not local.** Confirming an alert marks every
  open claim in the area and leaves a notice for its owner: against the real
  database those are real neighbours. It refuses unless the database is SQLite
  or on localhost; `--permitir-base-remota` overrides that, on purpose and in
  full view. The `.env` of this repository may well point at production.
- **Publish to a broker.** Events go to an in-memory publisher and are listed at
  the end. Nothing leaves the process, whatever the configuration says.

It opens no ticket in Jira either.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# Run as a script, the repository root is not on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.models import Reclamo  # noqa: E402
from app.domain.enums import CategoriaReclamo, NivelCriticidad  # noqa: E402
from app.events import topics  # noqa: E402
from app.events.handlers import HANDLERS  # noqa: E402
from app.events.producer import InMemoryEventPublisher  # noqa: E402
from app.integrations.tickets import SinTickets  # noqa: E402
from app.schemas.reclamo import ReclamoCrear  # noqa: E402
from app.services.reclamo_service import ReclamoService  # noqa: E402

Sesiones = Callable[[], AbstractAsyncContextManager[AsyncSession]]

HOSTS_LOCALES = frozenset({"localhost", "127.0.0.1", "::1"})

# Enough variety to see every rule of the alert at work: the three categories
# the weather makes worse, two it does not, and a neighbourhood left outside.
SEMILLA: tuple[tuple[str, str, CategoriaReclamo, str], ...] = (
    (
        "Rama grande a punto de caer",
        "Una rama quebrada cuelga sobre la vereda",
        CategoriaReclamo.ARBOLADO,
        "Palermo",
    ),
    (
        "Boca de tormenta tapada",
        "El desague de la esquina esta tapado con hojas",
        CategoriaReclamo.AGUA_CLOACAS,
        "Palermo",
    ),
    (
        "Luminaria apagada en la cuadra",
        "El foco de la cuadra no enciende hace dias",
        CategoriaReclamo.ALUMBRADO,
        "Palermo",
    ),
    (
        "Bache profundo en la calzada",
        "Hay un pozo que ocupa medio carril",
        CategoriaReclamo.BACHES,
        "Palermo",
    ),
    (
        "Arbol inclinado sobre los cables",
        "El arbol se apoya sobre el tendido electrico",
        CategoriaReclamo.ARBOLADO,
        "Belgrano",
    ),
    (
        "Ruidos molestos de madrugada",
        "Un local deja la musica fuerte toda la noche",
        CategoriaReclamo.RUIDOS,
        "Belgrano",
    ),
    (
        "Vereda inundada cuando llueve",
        "El agua se acumula y no escurre en la esquina",
        CategoriaReclamo.AGUA_CLOACAS,
        "Belgrano",
    ),
    (
        "Poste de luz torcido",
        "El poste de alumbrado quedo inclinado",
        CategoriaReclamo.ALUMBRADO,
        "Caballito",
    ),
)


def es_base_local(url: str) -> bool:
    """True for SQLite and for a server on this machine. Anything else is not ours to touch."""
    partes = urlsplit(url)
    if partes.scheme.startswith("sqlite"):
        return True
    return (partes.hostname or "") in HOSTS_LOCALES


def _sobre(topic: str, datos: dict[str, Any]) -> dict[str, Any]:
    """The internal envelope, as the webhook and the bus consumer hand it over."""
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": topic,
        "occurred_at": datetime.now(UTC).isoformat(),
        "source": "ensayo",
        "data": datos,
    }


def _servicio(session: AsyncSession, publisher: InMemoryEventPublisher) -> ReclamoService:
    return ReclamoService(session, publisher, tickets=SinTickets())


def _millis(momento: datetime) -> int:
    return int(momento.timestamp() * 1000)


async def sembrar(sesiones: Sesiones, publisher: InMemoryEventPublisher) -> list[Reclamo]:
    """File the demo claims. Run once; running it again files them again."""
    creados: list[Reclamo] = []
    async with sesiones() as session:
        servicio = _servicio(session, publisher)
        for numero, (titulo, descripcion, categoria, barrio) in enumerate(SEMILLA, start=1):
            creados.append(
                await servicio.crear(
                    ReclamoCrear(
                        titulo=titulo, descripcion=descripcion, categoria=categoria, barrio=barrio
                    ),
                    ciudadano_id=f"vecino-de-ensayo-{numero}",
                )
            )
    return creados


async def confirmar(
    sesiones: Sesiones,
    publisher: InMemoryEventPublisher,
    *,
    nivel: NivelCriticidad,
    barrios: list[str],
    fenomeno: str = "TORMENTA_FUERTE",
    horas: float = 6.0,
    alerta_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Confirm an alert that is in force from now for `horas` hours."""
    alerta_id = alerta_id or uuid.uuid4()
    ahora = datetime.now(UTC)
    sobre = _sobre(
        topics.ESPACIOS_CLIMA_CONFIRMADA,
        {
            "alertaId": str(alerta_id),
            "nivelCriticidad": nivel.value,
            "fenomeno": fenomeno,
            "barrios": barrios,
            "ubicaciones": [],
            # Starts now and is still running: an alert whose window is over is
            # stored and otherwise ignored. Not earlier than now, so the claims
            # that were already open do not count as filed during the alert.
            "vigenciaDesde": _millis(ahora),
            "vigenciaHasta": _millis(ahora + timedelta(hours=horas)),
            "actorSub": "ensayo",
        },
    )
    async with sesiones() as session:
        await HANDLERS[topics.ESPACIOS_CLIMA_CONFIRMADA](sobre, _servicio(session, publisher))

    aplicadas = publisher.eventos_de(topics.CLIMA_APLICADA)
    resumen: dict[str, Any] = {"alerta_id": alerta_id, "nivel": nivel.value, "barrios": barrios}
    if aplicadas:
        datos = aplicadas[-1].data
        resumen.update(
            reclamos_marcados=datos.reclamos_marcados,
            avisos_enviados=datos.avisos_enviados,
            reclamos_sin_ubicacion=datos.reclamos_sin_ubicacion,
            acciones=datos.acciones_aplicadas,
        )
    return resumen


async def finalizar(
    sesiones: Sesiones, publisher: InMemoryEventPublisher, *, alerta_id: uuid.UUID | None = None
) -> dict[str, Any] | None:
    """Finish an alert: the given one, or the most recent one still open.

    Returns `None` when there is no alert to finish.
    """
    async with sesiones() as session:
        servicio = _servicio(session, publisher)
        if alerta_id is None:
            abiertas = await servicio.clima.repo.activas()
            if not abiertas:
                return None
            alerta_id = abiertas[0].alerta_id
        sobre = _sobre(
            topics.ESPACIOS_CLIMA_FINALIZADA,
            {
                "alertaId": str(alerta_id),
                "finalizadaEn": _millis(datetime.now(UTC)),
                "actorSub": "ensayo",
            },
        )
        await HANDLERS[topics.ESPACIOS_CLIMA_FINALIZADA](sobre, servicio)

    levantadas = publisher.eventos_de(topics.CLIMA_LEVANTADA)
    resumen: dict[str, Any] = {"alerta_id": alerta_id}
    if levantadas:
        datos = levantadas[-1].data
        resumen.update(
            reclamos_abiertos_al_confirmar=datos.reclamos_abiertos_al_confirmar,
            reclamos_creados_durante=datos.reclamos_creados_durante,
            subidos_de_prioridad=datos.subidos_de_prioridad,
            abiertos_al_finalizar=datos.abiertos_al_finalizar,
        )
    else:
        resumen["detalle"] = "la alerta no existe o ya estaba finalizada"
    return resumen


def _argumentos(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ensayar_alerta.py", description="Ensaya una alerta climatica sin pasar por el bus."
    )
    parser.add_argument(
        "--permitir-base-remota",
        action="store_true",
        help="corre aunque la base no sea local: marca y avisa reclamos reales",
    )
    comandos = parser.add_subparsers(dest="comando", required=True)
    comandos.add_parser("semilla", help="carga reclamos de demo en varios barrios")

    alta = comandos.add_parser("confirmar", help="confirma una alerta vigente desde ahora")
    alta.add_argument("--nivel", default="ALTA", choices=[n.value for n in NivelCriticidad])
    alta.add_argument("--barrios", default="Palermo,Belgrano", help="separados por coma")
    alta.add_argument("--fenomeno", default="TORMENTA_FUERTE")
    alta.add_argument("--horas", type=float, default=6.0, help="duracion de la vigencia")
    alta.add_argument("--alerta-id", type=uuid.UUID, default=None)

    baja = comandos.add_parser("finalizar", help="finaliza una alerta")
    baja.add_argument(
        "--alerta-id", type=uuid.UUID, default=None, help="por defecto, la mas reciente abierta"
    )
    return parser.parse_args(argv)


def _mostrar(titulo: str, resumen: dict[str, Any]) -> None:
    print(titulo)
    for clave, valor in resumen.items():
        print(f"  {clave}: {valor}")


async def _ejecutar(
    args: argparse.Namespace, sesiones: Sesiones, publisher: InMemoryEventPublisher
) -> int:
    if args.comando == "semilla":
        creados = await sembrar(sesiones, publisher)
        print(f"Reclamos de demo cargados: {len(creados)}")
        for reclamo in creados:
            print(f"  {reclamo.barrio:<10} {reclamo.categoria.value:<13} {reclamo.titulo}")
    elif args.comando == "confirmar":
        barrios = [b.strip() for b in args.barrios.split(",") if b.strip()]
        resumen = await confirmar(
            sesiones,
            publisher,
            nivel=NivelCriticidad(args.nivel),
            barrios=barrios,
            fenomeno=args.fenomeno,
            horas=args.horas,
            alerta_id=args.alerta_id,
        )
        _mostrar("Alerta confirmada", resumen)
    else:
        resumen = await finalizar(sesiones, publisher, alerta_id=args.alerta_id)
        if resumen is None:
            print("No hay ninguna alerta abierta para finalizar.")
            return 1
        _mostrar("Alerta finalizada", resumen)

    publicados = [topic for topic, _, _ in publisher.publicados]
    print(f"Eventos que habrian salido al bus (quedaron en memoria): {len(publicados)}")
    for topic in sorted(set(publicados)):
        print(f"  {publicados.count(topic)} x {topic}")
    return 0


async def _correr(args: argparse.Namespace) -> int:
    from app.db.base import Base
    from app.db.session import SessionLocal, engine

    # A fresh SQLite file has no tables, and Alembic is not worth a rehearsal.
    # A local PostgreSQL is expected to be migrated already.
    if engine.url.get_backend_name() == "sqlite":
        async with engine.begin() as conexion:
            await conexion.run_sync(Base.metadata.create_all)
    try:
        return await _ejecutar(args, SessionLocal, InMemoryEventPublisher())
    finally:
        await engine.dispose()


def main(argv: list[str], *, url: str | None = None) -> int:
    args = _argumentos(argv)
    url = url if url is not None else settings.database_url
    if not es_base_local(url) and not args.permitir_base_remota:
        host = urlsplit(url).hostname or "desconocido"
        print(
            f"No corre: DATABASE_URL apunta a '{host}', que no es una base local.\n"
            "Confirmar una alerta marca reclamos reales y les deja un aviso a sus vecinos.\n"
            "Usa una base SQLite o en localhost, o agrega --permitir-base-remota si es a proposito."
        )
        return 2
    return asyncio.run(_correr(args))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
