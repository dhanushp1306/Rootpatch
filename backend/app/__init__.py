"""API package: aggregates all route modules under the `/api` prefix."""

from fastapi import APIRouter

from app.api.routes import health

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
