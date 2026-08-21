"""Fixtures shared by the whole suite.

Environment variables are set **before** importing `app`, because
`app.core.config.settings` is instantiated at import time.

The test database is in-memory SQLite: the suite runs on any machine and in CI
without depending on Postgres or Supabase. The models avoid vendor-specific
types precisely so this stays possible.
"""

from __future__ import annotations

import os

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "KAFKA_ENABLED": "false",
        "AUTH_ENABLED": "true",
        "AUTH_DEV_LOGIN_ENABLED": "true",
        "JWT_ALGORITHM": "HS256",
        "JWT_SECRET": "secreto-de-test",
        "JWT_ISSUER": "citypass-auth",
        "JWT_AUDIENCE": "citypass",
    }
)

import uuid  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

import jwt  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.api.deps import get_publisher  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.security import CurrentUser, Roles  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import Reclamo  # noqa: E402  (registers the models in the metadata)
from app.db.session import get_session  # noqa: E402
from app.events.producer import InMemoryEventPublisher  # noqa: E402
from app.main import app  # noqa: E402
from app.services.reclamo_service import ReclamoService  # noqa: E402

CIUDADANO_ID = "ciudadano-001"
OTRO_CIUDADANO_ID = "ciudadano-002"
OPERADOR_ID = "operador-001"
ADMIN_ID = "admin-001"


def crear_token(sub: str, roles: list[str], *, expira_en: timedelta = timedelta(hours=1)) -> str:
    ahora = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": sub,
            "roles": roles,
            "email": f"{sub}@citypass.local",
            "name": sub,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": ahora,
            "exp": ahora + expira_en,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


@pytest.fixture
def token_ciudadano() -> str:
    return crear_token(CIUDADANO_ID, [Roles.CIUDADANO])


@pytest.fixture
def token_otro_ciudadano() -> str:
    return crear_token(OTRO_CIUDADANO_ID, [Roles.CIUDADANO])


@pytest.fixture
def token_operador() -> str:
    return crear_token(OPERADOR_ID, [Roles.OPERADOR])


@pytest.fixture
def token_admin() -> str:
    return crear_token(ADMIN_ID, [Roles.OPERADOR, Roles.ADMIN])


@pytest.fixture
def usuario_ciudadano() -> CurrentUser:
    return CurrentUser(id=CIUDADANO_ID, nombre="Vecino", roles=frozenset({Roles.CIUDADANO}))


@pytest.fixture
def usuario_operador() -> CurrentUser:
    return CurrentUser(id=OPERADOR_ID, nombre="Operador", roles=frozenset({Roles.OPERADOR}))


@pytest_asyncio.fixture
async def engine() -> AsyncIterator:
    # StaticPool: without it every connection would open its own in-memory db.
    motor = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with motor.begin() as conexion:
        await conexion.run_sync(Base.metadata.create_all)
    yield motor
    await motor.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    fabrica = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with fabrica() as sesion:
        yield sesion


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
    return InMemoryEventPublisher()


@pytest.fixture
def service(session: AsyncSession, publisher: InMemoryEventPublisher) -> ReclamoService:
    return ReclamoService(session, publisher)


@pytest_asyncio.fixture
async def client(engine, publisher: InMemoryEventPublisher) -> AsyncIterator[AsyncClient]:
    """HTTP client against the real app, with database and bus swapped out."""
    fabrica = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def _session_override() -> AsyncIterator[AsyncSession]:
        async with fabrica() as sesion:
            yield sesion

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_publisher] = lambda: publisher

    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://test") as http:
        yield http

    app.dependency_overrides.clear()


@pytest.fixture
def auth() -> callable:
    """Sugar: `auth(token)` -> headers ready to hand to httpx."""

    def _headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    return _headers


def evento_contenedor_desbordado(**overrides) -> dict:
    """Sample message shaped the way the Waste module would publish it."""
    payload = {
        "event_id": str(uuid.uuid4()),
        "event_type": "residuos.contenedor.desbordado",
        "occurred_at": datetime.now(UTC).isoformat(),
        "source": "residuos",
        "correlation_id": "corr-residuos-1",
        "data": {
            "contenedor_id": "CT-1234",
            "nivel_llenado": 98.5,
            "direccion": "San Martin 1500",
            "barrio": "Centro",
            "latitud": -34.60,
            "longitud": -58.38,
        },
    }
    payload.update(overrides)
    return payload


async def contar_reclamos(session: AsyncSession) -> int:
    from sqlalchemy import func, select

    resultado = await session.execute(select(func.count()).select_from(Reclamo))
    return int(resultado.scalar_one())
