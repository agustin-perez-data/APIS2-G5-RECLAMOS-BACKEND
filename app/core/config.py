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

    # --- CityPass+ event gateway (Group 1) ---------------------------------
    # CU-INT-01. When enabled, domain events are published through the shared
    # gateway (HTTP + Avro contracts) instead of our own Kafka, and other
    # modules' events arrive by webhook at POST /api/v1/webhooks/citypass.
    gateway_enabled: bool = False
    gateway_url: str = "http://localhost:8080"
    gateway_token_url: str = "http://localhost:8083/oauth/token"
    gateway_client_id: str = "svc-reclamos"
    gateway_client_secret: str = ""
    gateway_namespace: str = "com.citypass.reclamos"
    # The dispatcher does not sign deliveries: the secret travels in the
    # subscription URL (?token=...). Empty = the webhook rejects everything.
    gateway_webhook_token: str = ""
    gateway_timeout_seconds: float = 5.0

    # --- Security: municipal staff ------------------------------------------
    # Group 2's Federated Login (LDAP + JWT) issues these and we only validate
    # them. Their IdP covers staff only, so citizens have their own issuer
    # below (see ADR 0011).
    auth_enabled: bool = True
    jwt_algorithm: str = "HS256"
    jwt_secret: str = "dev-secret-no-usar-en-produccion"
    jwt_issuer: str | None = "citypass-auth"
    jwt_audience: str | None = "citypass"
    jwt_jwks_url: str | None = None
    jwt_roles_claim: str = "roles"
    # Group 2 marks person tokens apart from service ones. Left as None while
    # the development login is the issuer, since it does not emit the claim.
    jwt_token_use_esperado: str | None = None
    # The IdP hands out raw LDAP group names; our delegate chooses them, so the
    # mapping to roles lives here and not in their directory.
    jwt_staff_grupos_operador: list[str] = []
    jwt_staff_grupos_admin: list[str] = []
    # Turns on the rules that only make sense against the real IdP: the
    # token_use check, the group mapping and the role whitelist. A group that
    # maps to nothing grants nothing, deliberately: an employee with no groups
    # assigned yet must not end up with staff access.
    jwt_staff_estricto: bool = False

    # --- Security: citizens (issued here) -----------------------------------
    # Group 2's IdP does not authenticate neighbours, so this module registers
    # and authenticates them. The algorithm is not configurable on purpose:
    # there is no reason an .env should be able to weaken it.
    ciudadanos_auth_enabled: bool = True
    jwt_ciudadanos_issuer: str = "citypass-reclamos"
    jwt_ciudadanos_audience: str = "citypass-reclamos-ciudadanos"
    jwt_ciudadanos_secret: str = "dev-secret-ciudadanos-no-usar-en-produccion"
    jwt_ciudadanos_ttl_horas: int = 12

    # --- Development login (scaffolding for Entrega 1) ----------------------
    # Stand-in for Group 2's Federated Login while that service is not up: it
    # mints tokens for a fixed set of users so the module can be demoed on its
    # own. Off by default, and the validator below makes it impossible to turn
    # on outside a development environment. Removal criteria live in
    # `app/api/v1/auth_dev.py`.
    auth_dev_login_enabled: bool = False
    auth_dev_token_horas: int = 8

    # --- Rate limiting ------------------------------------------------------
    # In-memory, per-process. Good enough for a single-instance deploy
    # (Railway). Disable in tests so fast request bursts do not trip 429s.
    rate_limit_enabled: bool = True
    rate_limit_login: str = "10/minute"
    # Tighter than login: a registration costs CPU (hashing) and creates rows.
    rate_limit_registro: str = "5/hour"
    rate_limit_creacion: str = "10/minute"
    rate_limit_comentarios: str = "15/minute"
    rate_limit_adhesiones: str = "20/minute"
    # Generous on purpose: the gateway can deliver bursts and a dropped event
    # ends in its dead letter queue. What protects the endpoint is the secret;
    # this only caps a flood from an unauthenticated client.
    rate_limit_webhook: str = "120/minute"

    # --- HTTP ---------------------------------------------------------------
    # Defaults cover the two dev servers the front end uses: CRA-style (3000)
    # and Vite (5173). Production origins come from CORS_ORIGINS in the env.
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"]
    )
    # For origins that cannot be listed one by one, such as Vercel preview
    # deployments. Anchor it to the project and its team slug: a bare
    # `https://.*\.vercel\.app` would let every site hosted on Vercel in.
    cors_origin_regex: str | None = None

    # --- Ticketing (Jira) ---------------------------------------------------
    # Every new claim also opens a ticket in the city's Jira project so the
    # back office can work it from there. Off by default: tests and local
    # development never talk to Jira.
    jira_enabled: bool = False
    jira_url: str | None = None
    jira_email: str | None = None
    jira_api_token: str | None = None
    jira_project_key: str = "REC"
    jira_issue_type: str = "Tarea"
    # Upper bound the tracker can add to the filing of a claim.
    jira_timeout_segundos: float = 5.0

    # --- Business rules -----------------------------------------------------
    # Number of neighbour endorsements that automatically bumps a claim's
    # priority (see `ReclamoService.adherir`).
    adhesiones_para_escalar: int = 10
    # Minimum classifier confidence to accept a suggestion without human triage.
    confianza_minima_clasificador: float = 0.35
    # Days a claim can sit in RESUELTO before the worker closes it on its own
    # (US-17: no response from the citizen).
    dias_cierre_automatico: int = 7
    # How often the worker checks for claims to auto-close.
    intervalo_cierre_automatico_segundos: int = 3600

    # --- Similar claims (ADR 0007) --------------------------------------------
    # Only open claims of the same category, filed within the window and, when
    # both have coordinates, within the radius, are compared at all.
    similares_radio_metros: int = 300
    similares_ventana_dias: int = 30
    # score = texto * peso + cercania * (1 - peso). With 0.7 and a 0.20 floor, a
    # claim under 100 m away shows up even when worded differently; farther
    # away, the text has to match too.
    similares_peso_texto: float = 0.7
    similares_puntaje_minimo: float = 0.20
    similares_maximo: int = 5

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

    @model_validator(mode="after")
    def _emisores_no_se_pisan(self) -> Settings:
        """The two issuers must stay distinguishable.

        A token is routed to its issuer by its `iss` claim; if both ends shared
        it, a citizen token and a staff token would validate against the same
        configuration and the role whitelist would stop meaning anything.
        """
        if self.jwt_ciudadanos_issuer == self.jwt_issuer:
            raise ValueError(
                "JWT_CIUDADANOS_ISSUER no puede ser igual a JWT_ISSUER "
                f"('{self.jwt_issuer}'): son dos emisores distintos"
            )
        if self.jwt_ciudadanos_audience == self.jwt_audience:
            raise ValueError(
                f"JWT_CIUDADANOS_AUDIENCE no puede ser igual a JWT_AUDIENCE ('{self.jwt_audience}')"
            )
        return self

    @model_validator(mode="after")
    def _idp_real_exige_modo_estricto(self) -> Settings:
        """Fail closed once the real IdP is wired.

        An asymmetric algorithm means we are pointing at Group 2's JWKS rather
        than at the development login, and at that point the checks that guard
        staff access are no longer optional.
        """
        asimetrico = self.jwt_algorithm.startswith(("RS", "ES"))
        if not asimetrico:
            return self
        if not self.jwt_staff_estricto:
            raise ValueError(
                f"JWT_ALGORITHM='{self.jwt_algorithm}' apunta al IdP real: "
                "JWT_STAFF_ESTRICTO tiene que estar en true"
            )
        if not self.jwt_token_use_esperado:
            raise ValueError(
                f"JWT_ALGORITHM='{self.jwt_algorithm}' apunta al IdP real: "
                "falta JWT_TOKEN_USE_ESPERADO (el Grupo 2 emite 'human')"
            )
        if self.auth_dev_login_enabled:
            # It signs HS256 with our own secret and the staff issuer, so once
            # that slot points at Group 2 its tokens no longer validate. Leaving
            # it on would mint credentials that open nothing, and the symptom
            # (a 401 on a token that was just issued) sends you looking in the
            # wrong place.
            raise ValueError(
                f"JWT_ALGORITHM='{self.jwt_algorithm}' apunta al IdP real: "
                "AUTH_DEV_LOGIN_ENABLED tiene que estar en false, sus tokens ya no validan"
            )
        return self

    @model_validator(mode="after")
    def _secreto_de_ciudadanos_fuera_de_desarrollo(self) -> Settings:
        """The default signing secret is public: it must not reach a deploy."""
        default = "dev-secret-ciudadanos-no-usar-en-produccion"
        usa_el_default = self.jwt_ciudadanos_secret == default
        if self.ciudadanos_auth_enabled and not self.is_local and usa_el_default:
            raise ValueError(
                "JWT_CIUDADANOS_SECRET sigue siendo el valor de ejemplo con "
                f"ENVIRONMENT='{self.environment}': cualquiera podria firmar tokens"
            )
        return self

    @model_validator(mode="after")
    def _jira_completo(self) -> Settings:
        """With Jira on, a missing credential should stop the boot, not every claim."""
        if self.jira_enabled:
            faltan = [
                nombre
                for nombre, valor in (
                    ("JIRA_URL", self.jira_url),
                    ("JIRA_EMAIL", self.jira_email),
                    ("JIRA_API_TOKEN", self.jira_api_token),
                )
                if not valor
            ]
            if faltan:
                raise ValueError(f"JIRA_ENABLED=true pero faltan: {', '.join(faltan)}")
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
