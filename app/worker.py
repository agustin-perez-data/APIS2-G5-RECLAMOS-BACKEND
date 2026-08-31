"""Entry point of the event worker: `python -m app.worker`.

A separate process from the API so event consumption and HTTP traffic scale and
fail independently of each other.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.session import cerrar_engine, session_scope
from app.events.consumer import EventConsumer
from app.events.producer import EventPublisher, crear_publisher
from app.services.reclamo_service import ReclamoService

log = get_logger(__name__)


async def _job_cierre_automatico(publisher: EventPublisher) -> None:
    """Periodically closes RESUELTO claims once the response window expires (US-17)."""
    while True:
        await asyncio.sleep(settings.intervalo_cierre_automatico_segundos)
        try:
            async with session_scope() as session:
                service = ReclamoService(session, publisher)
                await service.cerrar_resueltos_vencidos()
        except Exception:  # noqa: BLE001 - one bad run must not kill the worker
            log.exception("worker.cierre_automatico.error")


async def main() -> None:
    setup_logging()

    if not settings.kafka_enabled:
        log.warning("worker.kafka_deshabilitado", detalle="KAFKA_ENABLED=false")
        return

    publisher = crear_publisher()
    await publisher.start()

    consumer = EventConsumer(publisher)
    await consumer.start()

    loop = asyncio.get_running_loop()
    parar = asyncio.Event()

    # Graceful shutdown: inside the container the stop signal is SIGTERM.
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows lacks add_signal_handler
            loop.add_signal_handler(sig, parar.set)

    tarea = asyncio.create_task(consumer.run())
    tarea_cierre = asyncio.create_task(_job_cierre_automatico(publisher))
    log.info(
        "worker.iniciado",
        topics=consumer.topics,
        cierre_automatico_cada_segundos=settings.intervalo_cierre_automatico_segundos,
    )

    try:
        await asyncio.wait(
            {tarea, tarea_cierre, asyncio.create_task(parar.wait())},
            return_when="FIRST_COMPLETED",
        )
    finally:
        tarea.cancel()
        tarea_cierre.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tarea
        with contextlib.suppress(asyncio.CancelledError):
            await tarea_cierre
        await publisher.stop()
        await cerrar_engine()
        log.info("worker.detenido")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
