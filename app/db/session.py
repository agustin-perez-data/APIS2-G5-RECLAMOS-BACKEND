"""Async SQLAlchemy engine and sessions.

Supabase quirks handled here:

* The URI the dashboard hands out uses `postgresql://`; the Settings validator
  rewrites it to `postgresql+asyncpg://`.
* asyncpg does not understand libpq's `sslmode` parameter, so it is translated
  into an SSL context.
* The *transaction pooler* (port 6543, pgbouncer) does not support prepared
  statements, so the caches are disabled and NullPool is used.
"""

from __future__ import annotations

import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings, settings

_SSL_MODES_CON_TLS = {"require", "verify-ca", "verify-full"}


def _es_postgres(url: str) -> bool:
    return url.startswith(("postgresql", "postgres"))


def _preparar_url(cfg: Settings) -> tuple[str, dict]:
    """Return the sanitised URL plus the connect_args asyncpg expects."""
    connect_args: dict = {}

    if not _es_postgres(cfg.database_url):
        # SQLite (tests) and anything else pass through untouched: rebuilding
        # the URL would mangle forms like `sqlite+aiosqlite:///:memory:`.
        return cfg.database_url, connect_args

    partes = urlsplit(cfg.database_url)
    query = dict(parse_qsl(partes.query))

    sslmode = query.pop("sslmode", None)
    if sslmode in _SSL_MODES_CON_TLS:
        contexto = ssl.create_default_context()
        if sslmode == "require":
            # Some Supabase pools present their own certificates. `require`
            # encrypts the traffic without validating the chain, same as libpq.
            contexto.check_hostname = False
            contexto.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = contexto

    if cfg.uses_pgbouncer:
        query["prepared_statement_cache_size"] = "0"
        connect_args["statement_cache_size"] = 0

    url = urlunsplit(partes._replace(query=urlencode(query)))
    return url, connect_args


def crear_engine(cfg: Settings | None = None) -> AsyncEngine:
    cfg = cfg or settings
    url, connect_args = _preparar_url(cfg)

    kwargs: dict = {
        "echo": cfg.db_echo,
        "pool_pre_ping": True,
        "connect_args": connect_args,
    }
    if cfg.uses_pgbouncer:
        # pgbouncer already pools connections. Pooling on top of it leaks
        # connections and triggers prepared-statement errors.
        kwargs["poolclass"] = NullPool
    elif _es_postgres(url):
        kwargs["pool_size"] = cfg.db_pool_size
        kwargs["max_overflow"] = cfg.db_max_overflow
    # Other dialects (SQLite in the tests) keep the pool their dialect picks:
    # StaticPool does not even accept `pool_size`.

    return create_async_engine(url, **kwargs)


engine: AsyncEngine = crear_engine()

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request."""
    async with SessionLocal() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Session for non-HTTP processes (the event worker, scripts)."""
    async with SessionLocal() as session:
        yield session


async def cerrar_engine() -> None:
    await engine.dispose()
