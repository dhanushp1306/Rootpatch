"""Aggregates all route modules under the `/api` prefix."""

from fastapi import APIRouter

from app.api.routes.analysis import router as analysis_router
from app.api.routes.health import router as health_router
from app.api.routes.projects import router as projects_router
from app.api.routes.scans import router as scans_router

api_router = APIRouter(prefix="/api")

api_router.include_router(health_router)
api_router.include_router(projects_router)
api_router.include_router(scans_router)
api_router.include_router(analysis_router)
