"""Structured JSON logging, so the cloud provider can consume it."""

from __future__ import annotations

import logging
import re
import sys

import structlog

from app.core.config import settings


class OcultarTokenEnUrl(logging.Filter):
    """Mask `?token=...` in uvicorn's access log.

    The gateway's dispatcher cannot always send headers, so the webhook also
    accepts its secret as a query parameter - and uvicorn logs the full URL on
    every delivery, which would leave the secret in plain text in the platform
    logs. Preferring the `X-Webhook-Token` header avoids this entirely; this
    filter is the net for when the header is not an option.
    """

    _patron = re.compile(r"(token=)[^&\s\"']+")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                self._patron.sub(r"***", arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True


def setup_logging() -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.DEBUG if settings.debug else logging.INFO,
    )

    # Human-readable output while developing, JSON everywhere else so the cloud
    # log aggregator can index the fields.
    renderer = (
        structlog.dev.ConsoleRenderer()
        if settings.is_local
        else structlog.processors.JSONRenderer()
    )

    logging.getLogger("uvicorn.access").addFilter(OcultarTokenEnUrl())

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
