"""Schemas for Step 5 automated patch generation and Step 6 review, approval, and safe application."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

PatchStatus = Literal[
    "generated",
    "approved",
    "rejected",
    "applied",
    "application_failed",
    "stale",
]
ApprovalStatus = Literal["pending", "approved", "rejected"]
ApplicationStatus = Literal["not_applied", "applied", "failed", "stale"]
ApplicationResult = Literal["applied", "failed", "stale"]
PatchBatchStatus = Literal["completed", "partial", "empty"]
PatchConfidence = Literal["HIGH", "MEDIUM", "LOW"]


class PatchGenerateRequest(BaseModel):
    """Optional selector narrowing patch generation to a specific finding or analysis."""

    finding_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    analysis_id: Optional[str] = Field(default=None, min_length=1, max_length=128)


class PatchValidationInfo(BaseModel):
    """Verification summary proving the generated unified diff is safe and applicable."""

    is_valid: bool = True
    target_file_verified: bool = True
    workspace_confined: bool = True
    hunks_count: int
    lines_added: int
    lines_removed: int
    original_file_sha256: str
    checks_passed: List[str] = Field(default_factory=list)


class PatchRecord(BaseModel):
    """Persisted candidate patch for a single static finding + root cause analysis."""

    patch_id: str
    project_id: str
    scan_id: str
    analysis_id: str
    finding_id: str
    file_path: str
    line_number: int
    rule_id: str
    status: PatchStatus = "generated"
    approval_status: ApprovalStatus = "pending"
    application_status: ApplicationStatus = "not_applied"
    applied: bool = False
    summary: str
    explanation: str
    confidence: PatchConfidence
    unified_diff: str
    original_snippet: str
    proposed_snippet: str
    assumptions_or_uncertainties: List[str] = Field(default_factory=list)
    validation: PatchValidationInfo
    generated_at: str
    provider: str
    model: str
    reviewed_at: Optional[str] = None
    review_note: Optional[str] = None
    applied_at: Optional[str] = None
    applied_file_sha256: Optional[str] = None
    backup_path: Optional[str] = None
    application_error: Optional[str] = None


class RejectedPatchDetail(BaseModel):
    """Sanitized explanation recorded when an item in a multi-patch batch is rejected."""

    finding_id: str
    analysis_id: str
    file_path: str
    reason: str


class PatchBatchResponse(BaseModel):
    """Complete patch generation batch persisted per project and returned by API routes."""

    batch_id: str
    project_id: str
    scan_id: str
    report_id: str
    status: PatchBatchStatus
    generated_at: str
    provider: str
    model: str
    total_targets: int
    generated_count: int
    rejected_count: int = 0
    patches: List[PatchRecord] = Field(default_factory=list)
    rejected_patches: List[RejectedPatchDetail] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class PatchHistoryStore(BaseModel):
    """On-disk persistence envelope preserving latest patch batch and prior history."""

    latest: PatchBatchResponse
    history: List[PatchBatchResponse] = Field(default_factory=list)


# --- Step 6: Patch Review, Approval, Application, and History schemas ---


class PatchReviewDecisionRequest(BaseModel):
    """Optional developer note attached when approving or rejecting a patch."""

    comment: Optional[str] = Field(default=None, max_length=500)


class PatchReviewResponse(BaseModel):
    """Comprehensive developer review view for a single generated patch."""

    patch_id: str
    project_id: str
    scan_id: str
    analysis_id: str
    finding_id: str
    file_path: str
    line_number: int
    rule_id: str
    status: PatchStatus
    approval_status: ApprovalStatus
    application_status: ApplicationStatus
    applied: bool
    summary: str
    explanation: str
    confidence: PatchConfidence
    unified_diff: str
    original_snippet: str
    proposed_snippet: str
    original_code: Optional[str] = None
    proposed_code: Optional[str] = None
    is_stale: bool = False
    stale_reason: Optional[str] = None
    can_approve: bool = False
    can_reject: bool = False
    can_apply: bool = False
    validation: PatchValidationInfo
    generated_at: str
    reviewed_at: Optional[str] = None
    review_note: Optional[str] = None
    applied_at: Optional[str] = None
    applied_file_sha256: Optional[str] = None
    application_error: Optional[str] = None
    finding_title: Optional[str] = None
    finding_severity: Optional[str] = None
    root_cause: Optional[str] = None


class PatchApplicationHistoryEntry(BaseModel):
    """Audit log entry recording every patch application attempt and its outcome."""

    history_id: str
    patch_id: str
    project_id: str
    finding_id: str
    file_path: str
    applied_at: str
    previous_file_sha256: str
    new_file_sha256: Optional[str] = None
    result: ApplicationResult
    backup_path: Optional[str] = None
    error_message: Optional[str] = None


class PatchApplicationHistoryResponse(BaseModel):
    """Persisted patch application audit trail for a project."""

    project_id: str
    total_events: int
    applied_count: int
    failed_count: int
    stale_count: int
    history: List[PatchApplicationHistoryEntry] = Field(default_factory=list)


class PatchApplyResponse(BaseModel):
    """Response returned when applying an approved patch to the project workspace."""

    message: str
    patch: PatchRecord
    application_record: PatchApplicationHistoryEntry


# --- Internal strict schemas for validating raw LLM JSON responses ---


class LLMPatchItemPayload(BaseModel):
    finding_id: str = Field(..., min_length=1)
    target_file: Optional[str] = None
    unified_diff: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    explanation: str = Field(..., min_length=1)
    confidence: PatchConfidence = "MEDIUM"
    assumptions_or_uncertainties: List[str] = Field(default_factory=list)


class LLMPatchBatchPayload(BaseModel):
    patches: List[LLMPatchItemPayload]
    limitations: List[str] = Field(default_factory=list)
