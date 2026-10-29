"""Aggregates the routers of API version 1."""

from fastapi import APIRouter

from app.api.v1 import actividades, notificaciones, reclamos, webhooks
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(reclamos.router)
api_router.include_router(notificaciones.router)
api_router.include_router(webhooks.router)
api_router.include_router(actividades.router)

# Group 2's IdP does not authenticate neighbours, so this module does (ADR 0011).
if settings.ciudadanos_auth_enabled:
    from app.api.v1 import auth_ciudadanos

    api_router.include_router(auth_ciudadanos.router)

# Mounted only while the development login is on, so in any other environment
# the endpoint does not exist at all - not even in the OpenAPI page.
if settings.auth_dev_login_enabled:
    from app.api.v1 import auth_dev

    api_router.include_router(auth_dev.router)
