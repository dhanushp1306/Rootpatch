"""Schemas for Step 4 AI-powered root cause analysis."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

AnalysisConfidence = Literal["HIGH", "MEDIUM", "LOW"]
AnalysisItemStatus = Literal["completed", "partial", "insufficient_context", "failed"]


class RootCauseAnalysisItem(BaseModel):
    """Structured, evidence-based root cause analysis for a single finding."""

    analysis_id: str
    project_id: str
    scan_id: str
    finding_id: str
    file_path: str
    line_number: int
    rule_id: str
    root_cause: str
    technical_explanation: str
    affected_component: str
    impact: str
    recommended_fix: str
    evidence: List[str] = Field(default_factory=list)
    assumptions_or_uncertainties: List[str] = Field(default_factory=list)
    related_finding_ids: List[str] = Field(default_factory=list)
    relationship_explanation: Optional[str] = None
    confidence: AnalysisConfidence
    confidence_reason: str
    analysis_status: AnalysisItemStatus


class SharedRootCauseGroup(BaseModel):
    """Optional grouping of related findings that share an underlying cause."""

    group_id: str
    shared_cause: str
    finding_ids: List[str]
    explanation: str


class AnalysisReportResponse(BaseModel):
    """Complete analysis report persisted per project and returned by API routes."""

    report_id: str
    project_id: str
    scan_id: str
    status: Literal["completed", "partial", "empty", "failed"]
    analyzed_at: str
    provider: str
    model: str
    total_findings_in_scan: int
    analyzed_count: int
    analyses: List[RootCauseAnalysisItem] = Field(default_factory=list)
    shared_root_cause_groups: List[SharedRootCauseGroup] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class AnalysisHistoryStore(BaseModel):
    """On-disk persistence envelope preserving latest report and prior history."""

    latest: AnalysisReportResponse
    history: List[AnalysisReportResponse] = Field(default_factory=list)


# --- Internal strict schemas for validating raw LLM JSON responses ---


class LLMFindingAnalysisPayload(BaseModel):
    finding_id: str = Field(..., min_length=1)
    root_cause: str = Field(..., min_length=1)
    technical_explanation: str = Field(..., min_length=1)
    affected_component: str = Field(..., min_length=1)
    impact: str = Field(..., min_length=1)
    recommended_fix: str = Field(..., min_length=1)
    evidence: List[str] = Field(default_factory=list)
    assumptions_or_uncertainties: List[str] = Field(default_factory=list)
    related_finding_ids: List[str] = Field(default_factory=list)
    relationship_explanation: Optional[str] = None
    confidence: AnalysisConfidence
    confidence_reason: str = Field(..., min_length=1)
    analysis_status: AnalysisItemStatus = "completed"


class LLMSharedGroupPayload(BaseModel):
    shared_cause: str = Field(..., min_length=1)
    finding_ids: List[str] = Field(default_factory=list)
    explanation: str = Field(..., min_length=1)


class LLMAnalysisBatchPayload(BaseModel):
    analyses: List[LLMFindingAnalysisPayload]
    shared_root_cause_groups: List[LLMSharedGroupPayload] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
