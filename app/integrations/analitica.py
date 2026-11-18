"""Server-to-server access to the Claims dashboard owned by Analytics."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

_TIMEOUT_SEGUNDOS = 10.0
_CABECERAS_TABLERO = frozenset(
    {
        b"content-type",
        b"cache-control",
        b"content-security-policy",
        b"x-content-type-options",
        b"referrer-policy",
    }
)


class ErrorAnalitica(Exception):
    """Analytics did not return a usable dashboard; never expose its body."""

    def __init__(self, status_code: int | None = None, *, timeout: bool = False) -> None:
        self.status_code = status_code
        self.timeout = timeout
        super().__init__("Analitica no disponible")


@dataclass(frozen=True, slots=True)
class TableroAnalitica:
    html: bytes
    # Pairs preserve repeated policies; ASGI requires lowercase header names.
    headers: tuple[tuple[bytes, bytes], ...]


class AnaliticaClient:
    """Fetch the fixed Reclamos dashboard with the validated human token."""

    def __init__(
        self,
        analitica_url: str,
        client: httpx.AsyncClient | None = None,
        *,
        timeout_seconds: float = _TIMEOUT_SEGUNDOS,
    ) -> None:
        self._url = f"{analitica_url.rstrip('/')}/embed/reclamos"
        self._client = client
        self._owns_client = client is None
        self._timeout = timeout_seconds

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

        request = self._client.build_request(
            "GET",
            self._url,
            headers={
                "Authorization": f"Bearer {token_usuario}",
                "Accept": "text/html",
            },
            timeout=self._timeout,
        )
        # The shared HTTP client must not reuse upstream cookies across users.
        request.headers.pop("Cookie", None)
        try:
            # Bound the whole download as well as each individual network wait.
            async with asyncio.timeout(self._timeout):
                respuesta = await self._client.send(request, auth=None, follow_redirects=False)
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise ErrorAnalitica(timeout=True) from exc
        except httpx.HTTPError as exc:
            raise ErrorAnalitica() from exc

        if respuesta.status_code != 200:
            raise ErrorAnalitica(respuesta.status_code)

        content_type = respuesta.headers.get("content-type", "")
        if content_type.split(";", 1)[0].strip().lower() != "text/html":
            raise ErrorAnalitica()
        return TableroAnalitica(
            html=respuesta.content,
            headers=tuple(
                (nombre.lower(), valor)
                for nombre, valor in respuesta.headers.raw
                if nombre.lower() in _CABECERAS_TABLERO
            ),
        )
