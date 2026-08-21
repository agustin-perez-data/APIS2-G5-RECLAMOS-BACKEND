"""Central service configuration.

Everything comes from environment variables (12-factor). See `.env.example`.
"""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application --------------------------------------------------------
    app_name: str = "citypass-reclamos"
    environment: str = "local"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # Module identity inside CityPass+. Used as the `source` of published
    # events and as the prefix of the topics we own.
    service_source: str = "reclamos"

    # --- Database -----------------------------------------------------------
    database_url: str = "postgresql+asyncpg://citypass:citypass@localhost:5432/reclamos"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # --- Kafka / Redpanda ---------------------------------------------------
    kafka_enabled: bool = True
    kafka_bootstrap_servers: str = "localhost:19092"
    kafka_client_id: str = "reclamos-service"
    kafka_consumer_group: str = "reclamos-service"

    # --- Security -----------------------------------------------------------
    # Tokens are issued by Group 2 (Federated Login, LDAP + JWT). This service
    # only validates them: no credentials are ever minted here.
    auth_enabled: bool = True
    jwt_algorithm: str = "HS256"
    jwt_secret: str = "dev-secret-no-usar-en-produccion"
    jwt_issuer: str | None = "citypass-auth"
    jwt_audience: str | None = "citypass"
    jwt_jwks_url: str | None = None
    jwt_roles_claim: str = "roles"

    # --- Development login (scaffolding for Entrega 1) ----------------------
    # Stand-in for Group 2's Federated Login while that service is not up: it
    # mints tokens for a fixed set of users so the module can be demoed on its
    # own. Off by default, and the validator below makes it impossible to turn
    # on outside a development environment. Removal criteria live in
    # `app/api/v1/auth_dev.py`.
    auth_dev_login_enabled: bool = False
    auth_dev_token_horas: int = 8

    # --- HTTP ---------------------------------------------------------------
    # Defaults cover the two dev servers the front end uses: CRA-style (3000)
    # and Vite (5173). Production origins come from CORS_ORIGINS in the env.
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"]
    )

    # --- Business rules -----------------------------------------------------
    # Number of neighbour endorsements that automatically bumps a claim's
    # priority (see `ReclamoService.adherir`).
    adhesiones_para_escalar: int = 10
    # Minimum classifier confidence to accept a suggestion without human triage.
    confianza_minima_clasificador: float = 0.35

    @field_validator("database_url")
    @classmethod
    def _force_async_driver(cls, value: str) -> str:
        """Take the URI Supabase hands out and point it at the async driver."""
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        return value

    @model_validator(mode="after")
    def _dev_login_fuera_de_produccion(self) -> Settings:
        """Refuse to boot with the development login on outside development.

        Hardcoded credentials that stay enabled by accident are exactly the kind
        of thing nobody notices until an audit, so this fails loudly at startup
        instead of trusting the deploy checklist.
        """
        if self.auth_dev_login_enabled and not self.is_local:
            raise ValueError(
                "AUTH_DEV_LOGIN_ENABLED=true no esta permitido con ENVIRONMENT="
                f"'{self.environment}': el login de desarrollo usa usuarios hardcodeados"
            )
        return self

    @property
    def is_local(self) -> bool:
        return self.environment.lower() in {"local", "dev", "development", "test"}

    @property
    def uses_pgbouncer(self) -> bool:
        """True when the URL points at Supabase's transaction pooler.

        That pooler does not support prepared statements, so asyncpg's cache
        has to be turned off (see `app/db/session.py`).
        """
        parts = urlsplit(self.database_url)
        host = parts.hostname or ""
        return parts.port == 6543 or "pooler" in host


@lru_cache
def get_settings() -> Settings:
    """Cached settings: the environment is read once per process."""
    return Settings()


settings = get_settings()
