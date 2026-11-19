"""Project upload and inspection endpoints."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.core.config import Settings, get_settings
from app.core.errors import ProjectError
from app.schemas.project import ProjectMetadata, StructureResponse, UploadResponse
from app.services import upload_service

router = APIRouter(prefix="/projects", tags=["projects"])


def _http_error(exc: ProjectError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/upload", response_model=UploadResponse, status_code=201)
def upload_project(
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    try:
        metadata = upload_service.create_project_from_upload(file, settings)
    except ProjectError as exc:
        raise _http_error(exc) from exc
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
        raise _http_error(exc) from exc


@router.get("/{project_id}/structure", response_model=StructureResponse)
def get_project_structure(
    project_id: str, settings: Settings = Depends(get_settings)
) -> StructureResponse:
    try:
        return upload_service.get_project_structure(project_id, settings)
    except ProjectError as exc:
        raise _http_error(exc) from exc
