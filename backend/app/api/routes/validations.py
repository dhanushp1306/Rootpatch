"""Step 7 isolated testing and patch validation API routes."""

from typing import Optional

from fastapi import APIRouter, Body, Depends

from app.api.errors import http_error
from app.core.config import Settings, get_settings
from app.core.errors import ProjectError
from app.schemas.validation import (
    ValidationHistoryListResponse,
    ValidationReportResponse,
    ValidationRunRequest,
)
from app.services import validation_service
from app.services.container_runner import ContainerRunner, get_container_runner

router = APIRouter(prefix="/projects", tags=["validations"])


@router.post(
    "/{project_id}/patches/{patch_id}/validate",
    response_model=ValidationReportResponse,
)
def validate_project_patch(
    project_id: str,
    patch_id: str,
    payload: Optional[ValidationRunRequest] = Body(default=None),
    settings: Settings = Depends(get_settings),
    runner: ContainerRunner = Depends(get_container_runner),
) -> ValidationReportResponse:
    try:
        return validation_service.validate_applied_patch(
            project_id=project_id,
            patch_id=patch_id,
            settings=settings,
            request=payload,
            runner=runner,
        )
    except ProjectError as exc:
        raise http_error(exc) from exc


@router.get(
    "/{project_id}/patches/{patch_id}/validations",
    response_model=ValidationHistoryListResponse,
)
def get_patch_validation_history(
    project_id: str,
    patch_id: str,
    settings: Settings = Depends(get_settings),
) -> ValidationHistoryListResponse:
    try:
        return validation_service.get_patch_validations(
            project_id=project_id,
            patch_id=patch_id,
            settings=settings,
        )
    except ProjectError as exc:
        raise http_error(exc) from exc


@router.get(
    "/{project_id}/validations",
    response_model=ValidationHistoryListResponse,
)
def get_project_validation_history(
    project_id: str,
    settings: Settings = Depends(get_settings),
) -> ValidationHistoryListResponse:
    try:
        return validation_service.get_project_validations(
            project_id=project_id,
            settings=settings,
        )
    except ProjectError as exc:
        raise http_error(exc) from exc


@router.get(
    "/{project_id}/validations/{validation_id}",
    response_model=ValidationReportResponse,
)
def get_validation_report(
    project_id: str,
    validation_id: str,
    settings: Settings = Depends(get_settings),
) -> ValidationReportResponse:
    try:
        return validation_service.get_validation_by_id(
            project_id=project_id,
            validation_id=validation_id,
            settings=settings,
        )
    except ProjectError as exc:
        raise http_error(exc) from exc
