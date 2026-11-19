"""Automated patch generation and retrieval endpoints (Step 5)."""

from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from app.core.config import Settings, get_settings
from app.core.errors import ProjectError
from app.schemas.patch import PatchBatchResponse, PatchGenerateRequest, PatchRecord
from app.services import patch_service
from app.services.llm_provider import LLMProvider, get_llm_provider

router = APIRouter(prefix="/projects", tags=["patches"])


def _http_error(exc: ProjectError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/{project_id}/patches/generate", response_model=PatchBatchResponse)
def generate_project_patches(
    project_id: str,
    payload: Optional[PatchGenerateRequest] = Body(default=None),
    settings: Settings = Depends(get_settings),
    provider: Optional[LLMProvider] = Depends(get_llm_provider),
) -> PatchBatchResponse:
    try:
        return patch_service.generate_patches(
            project_id=project_id,
            settings=settings,
            request=payload,
            provider=provider,
        )
    except ProjectError as exc:
        raise _http_error(exc) from exc


@router.get("/{project_id}/patches", response_model=PatchBatchResponse)
def get_project_patches(
    project_id: str,
    settings: Settings = Depends(get_settings),
) -> PatchBatchResponse:
    try:
        return patch_service.get_latest_patches(project_id, settings)
    except ProjectError as exc:
        raise _http_error(exc) from exc


@router.get("/{project_id}/patches/{patch_id}", response_model=PatchRecord)
def get_project_patch(
    project_id: str,
    patch_id: str,
    settings: Settings = Depends(get_settings),
) -> PatchRecord:
    try:
        return patch_service.get_patch_by_id(project_id, patch_id, settings)
    except ProjectError as exc:
        raise _http_error(exc) from exc
