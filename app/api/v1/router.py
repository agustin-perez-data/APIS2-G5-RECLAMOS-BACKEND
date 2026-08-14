"""Aggregates the routers of API version 1."""

from fastapi import APIRouter

from app.api.v1 import reclamos

api_router = APIRouter()
api_router.include_router(reclamos.router)
