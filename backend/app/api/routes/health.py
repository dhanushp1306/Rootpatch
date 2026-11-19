"""Health-check endpoint."""

from fastapi import APIRouter

from app.core.config import settings
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(
        status="healthy",
        app=settings.app_name,
        version=settings.app_version,
        message=f"{settings.app_name} backend is running.",
    )
