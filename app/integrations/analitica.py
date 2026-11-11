"""Server-to-server access to the Claims dashboard owned by Analytics."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx

from app.core.config import Settings, settings

_MARGEN_TOKEN_SEGUNDOS = 30
_TIMEOUT_SEGUNDOS = 10.0


class ErrorAnalitica(Exception):
    """Analytics or the token endpoint did not return a usable dashboard."""

    def __init__(self, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__("Analitica no disponible")


@dataclass(frozen=True, slots=True)
class TableroAnalitica:
    html: str
    content_type: str
    cache_control: str | None
    content_security_policy: str | None


class AnaliticaClient:
    """Fetch the fixed Reclamos dashboard using the existing service identity."""

    def __init__(
        self,
        analitica_url: str,
        cfg: Settings | None = None,
        client: httpx.AsyncClient | None = None,
        *,
        timeout_seconds: float = _TIMEOUT_SEGUNDOS,
    ) -> None:
        self._url = f"{analitica_url.rstrip('/')}/embed/reclamos"
        self._cfg = cfg or settings
        self._client = client
        self._owns_client = client is None
        self._timeout = timeout_seconds
        self._token: str | None = None
        self._token_vence = 0.0
        self._token_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout, follow_redirects=False)

    async def stop(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def obtener_tablero(self, token_usuario: str) -> TableroAnalitica:
        """Return HTML and the response headers the API must preserve."""
        if self._client is None:
            raise RuntimeError("El cliente de Analitica no fue inicializado (falta start())")

        token_servicio = await self._obtener_token()
        try:
            respuesta = await self._client.get(
                self._url,
                headers={
                    "Authorization": f"Bearer {token_servicio}",
                    "X-Usuario-Token": token_usuario,
                },
                timeout=self._timeout,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise ErrorAnalitica() from exc

        if respuesta.status_code == 401:
            if self._token == token_servicio:
                self._token = None
            raise ErrorAnalitica(401)
        if respuesta.status_code != 200:
            raise ErrorAnalitica(respuesta.status_code)

        content_type = respuesta.headers.get("content-type", "")
        if content_type.split(";", 1)[0].strip().lower() != "text/html":
            raise ErrorAnalitica()

        return TableroAnalitica(
            html=respuesta.text,
            content_type=content_type,
            cache_control=respuesta.headers.get("cache-control"),
            content_security_policy=respuesta.headers.get("content-security-policy"),
        )

    async def _obtener_token(self) -> str:
        if self._token and time.monotonic() < self._token_vence - _MARGEN_TOKEN_SEGUNDOS:
            return self._token

        async with self._token_lock:
            if self._token and time.monotonic() < self._token_vence - _MARGEN_TOKEN_SEGUNDOS:
                return self._token
            assert self._client is not None
            try:
                respuesta = await self._client.post(
                    self._cfg.gateway_token_url,
                    data={"grant_type": "client_credentials"},
                    auth=(self._cfg.gateway_client_id, self._cfg.gateway_client_secret),
                    timeout=self._timeout,
                    follow_redirects=False,
                )
                respuesta.raise_for_status()
                cuerpo = respuesta.json()
                token = cuerpo["access_token"]
                ttl = float(cuerpo.get("expires_in", 900))
                if not isinstance(token, str) or not token or ttl <= 0:
                    raise ValueError("Respuesta de token invalida")
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                raise ErrorAnalitica() from exc

            self._token = token
            self._token_vence = time.monotonic() + ttl
            return token
