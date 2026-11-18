"""Real API and SQL storage with only external identity and Analytics simulated."""

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.errors import registrar_manejadores
from app.api.v1 import analitica
from app.db.session import get_session
from app.integrations.analitica import TableroAnalitica
from tests.analitica_helpers import entorno_federado


def aplicacion_sesion(engine, monkeypatch):
    cfg, clave = entorno_federado(monkeypatch)
    cfg.analitica_frontend_origins = ["https://localhost"]
    monkeypatch.setattr(analitica, "settings", cfg)
    app = FastAPI()
    registrar_manejadores(app)
    app.include_router(analitica.router, prefix="/api/v1")
    fabrica = async_sessionmaker(engine, expire_on_commit=False)

    async def sesiones():
        async with fabrica() as session:
            yield session

    class Cliente:
        tokens = []

        async def obtener_tablero(self, token):
            self.tokens.append(token)
            return TableroAnalitica(
                b"<html><body><p id='ok'>Tablero</p><script>"
                b"window.aislado=false;try{parent.document.body}catch(e){window.aislado=true}"
                b"</script></body></html>",
                (
                    (b"content-type", b"text/html; charset=utf-8"),
                    (
                        b"content-security-policy",
                        b"script-src 'unsafe-inline'; frame-ancestors 'self'",
                    ),
                ),
            )

    app.state.analitica = Cliente()
    app.dependency_overrides[get_session] = sesiones
    return app, cfg, clave
