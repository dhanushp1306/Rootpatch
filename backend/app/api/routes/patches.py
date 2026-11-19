"""Automated patch generation, review, approval, and safe application endpoints (Steps 5 & 6)."""

from typing import Optional

from fastapi import APIRouter, Body, Depends

from app.api.errors import http_error
from app.core.config import Settings, get_settings
from app.core.errors import ProjectError
from app.schemas.patch import (
    PatchApplicationHistoryResponse,
    PatchApplyResponse,
    PatchBatchResponse,
    PatchGenerateRequest,
    PatchRecord,
    PatchReviewDecisionRequest,
    PatchReviewResponse,
)
from app.services import patch_service
from app.services.llm_provider import LLMProvider, get_llm_provider

router = APIRouter(prefix="/projects", tags=["patches"])


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
        raise http_error(exc) from exc


@router.get("/{project_id}/patches", response_model=PatchBatchResponse)
def get_project_patches(
    project_id: str,
    settings: Settings = Depends(get_settings),
) -> PatchBatchResponse:
    try:
        return patch_service.get_latest_patches(project_id, settings)
    except ProjectError as exc:
        raise http_error(exc) from exc


# Registered before `/{project_id}/patches/{patch_id}` so "history" is not treated as a patch ID.
@router.get("/{project_id}/patches/history", response_model=PatchApplicationHistoryResponse)
def get_project_patch_history(
    project_id: str,
    settings: Settings = Depends(get_settings),
) -> PatchApplicationHistoryResponse:
    try:
        return patch_service.get_patch_application_history(project_id, settings)
    except ProjectError as exc:
        raise http_error(exc) from exc


@router.get("/{project_id}/patches/{patch_id}", response_model=PatchRecord)
def get_project_patch(
    project_id: str,
    patch_id: str,
    settings: Settings = Depends(get_settings),
) -> PatchRecord:
    try:
        return patch_service.get_patch_by_id(project_id, patch_id, settings)
    except ProjectError as exc:
        raise http_error(exc) from exc


@router.get("/{project_id}/patches/{patch_id}/review", response_model=PatchReviewResponse)
def review_project_patch(
    project_id: str,
    patch_id: str,
    settings: Settings = Depends(get_settings),
) -> PatchReviewResponse:
    try:
        return patch_service.get_patch_review(project_id, patch_id, settings)
    except ProjectError as exc:
        raise http_error(exc) from exc


@router.post("/{project_id}/patches/{patch_id}/approve", response_model=PatchRecord)
def approve_project_patch(
    project_id: str,
    patch_id: str,
    payload: Optional[PatchReviewDecisionRequest] = Body(default=None),
    settings: Settings = Depends(get_settings),
) -> PatchRecord:
    try:
        return patch_service.approve_patch(
            project_id=project_id,
            patch_id=patch_id,
            settings=settings,
            comment=payload.comment if payload else None,
        )
    except ProjectError as exc:
        raise http_error(exc) from exc


@router.post("/{project_id}/patches/{patch_id}/reject", response_model=PatchRecord)
def reject_project_patch(
    project_id: str,
    patch_id: str,
    payload: Optional[PatchReviewDecisionRequest] = Body(default=None),
    settings: Settings = Depends(get_settings),
) -> PatchRecord:
    try:
        return patch_service.reject_patch(
            project_id=project_id,
            patch_id=patch_id,
            settings=settings,
            comment=payload.comment if payload else None,
        )
    except ProjectError as exc:
        raise http_error(exc) from exc


@router.post("/{project_id}/patches/{patch_id}/apply", response_model=PatchApplyResponse)
def apply_project_patch(
    project_id: str,
    patch_id: str,
    settings: Settings = Depends(get_settings),
) -> PatchApplyResponse:
    try:
        return patch_service.apply_patch(
            project_id=project_id,
            patch_id=patch_id,
            settings=settings,
        )
    except ProjectError as exc:
        raise http_error(exc) from exc
