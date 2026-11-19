"""AI-powered root cause analysis endpoints (Step 4)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import Settings, get_settings
from app.core.errors import ProjectError
from app.schemas.analysis import AnalysisReportResponse, RootCauseAnalysisItem
from app.services import analysis_service
from app.services.llm_provider import LLMProvider, get_llm_provider

router = APIRouter(prefix="/projects", tags=["analysis"])


def _http_error(exc: ProjectError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/{project_id}/analyze", response_model=AnalysisReportResponse)
def analyze_project(
    project_id: str,
    settings: Settings = Depends(get_settings),
    provider: Optional[LLMProvider] = Depends(get_llm_provider),
) -> AnalysisReportResponse:
    try:
        return analysis_service.analyze_project(project_id, settings, provider=provider)
    except ProjectError as exc:
        raise _http_error(exc) from exc


@router.get("/{project_id}/analysis", response_model=AnalysisReportResponse)
def get_project_analysis(
    project_id: str, settings: Settings = Depends(get_settings)
) -> AnalysisReportResponse:
    try:
        return analysis_service.get_latest_analysis(project_id, settings)
    except ProjectError as exc:
        raise _http_error(exc) from exc


@router.get("/{project_id}/analysis/{analysis_id}", response_model=RootCauseAnalysisItem)
def get_project_analysis_item(
    project_id: str,
    analysis_id: str,
    settings: Settings = Depends(get_settings),
) -> RootCauseAnalysisItem:
    try:
        return analysis_service.get_analysis_by_id(project_id, analysis_id, settings)
    except ProjectError as exc:
        raise _http_error(exc) from exc
