"""Project upload and inspection endpoints."""

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.errors import http_error
from app.core.config import Settings, get_settings
from app.core.errors import ProjectError
from app.schemas.project import (
    ProjectMetadata,
    ProjectStatusResponse,
    StructureResponse,
    UploadResponse,
)
from app.services import status_service, upload_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("/upload", response_model=UploadResponse, status_code=201)
def upload_project(
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    try:
        metadata = upload_service.create_project_from_upload(file, settings)
    except ProjectError as exc:
        raise http_error(exc) from exc
    return UploadResponse(
        project_id=metadata.project_id,
        project_name=metadata.project_name,
        status=metadata.status,
        message="Project uploaded, safely extracted and inspected.",
    )


@router.get("/{project_id}", response_model=ProjectMetadata)
def get_project(
    project_id: str, settings: Settings = Depends(get_settings)
) -> ProjectMetadata:
    try:
        return upload_service.load_project(project_id, settings)
    except ProjectError as exc:
        raise http_error(exc) from exc


@router.get("/{project_id}/structure", response_model=StructureResponse)
def get_project_structure(
    project_id: str, settings: Settings = Depends(get_settings)
) -> StructureResponse:
    try:
        return upload_service.get_project_structure(project_id, settings)
    except ProjectError as exc:
        raise http_error(exc) from exc


@router.get("/{project_id}/status", response_model=ProjectStatusResponse)
def get_project_status(
    project_id: str, settings: Settings = Depends(get_settings)
) -> ProjectStatusResponse:
    try:
        return status_service.build_project_status(project_id, settings)
    except ProjectError as exc:
        raise http_error(exc) from exc
