"""Static bug detection scan endpoints."""

from fastapi import APIRouter, Depends

from app.api.errors import http_error
from app.core.config import Settings, get_settings
from app.core.errors import ProjectError
from app.schemas.scan import ScanResponse
from app.services import scan_service

router = APIRouter(prefix="/projects", tags=["scans"])


@router.post("/{project_id}/scan", response_model=ScanResponse)
def scan_project(
    project_id: str, settings: Settings = Depends(get_settings)
) -> ScanResponse:
    try:
        return scan_service.run_project_scan(project_id, settings)
    except ProjectError as exc:
        raise http_error(exc) from exc


@router.get("/{project_id}/scan", response_model=ScanResponse)
def get_project_scan(
    project_id: str, settings: Settings = Depends(get_settings)
) -> ScanResponse:
    try:
        return scan_service.get_latest_scan(project_id, settings)
    except ProjectError as exc:
        raise http_error(exc) from exc
