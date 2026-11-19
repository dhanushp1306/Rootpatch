"""Schemas for Step 3 static bug detection findings and scan responses."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

SeverityLevel = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
ConfidenceLevel = Literal["HIGH", "MEDIUM", "LOW"]
ScannerTool = Literal["ast", "ruff", "bandit"]
ScannerExecutionStatus = Literal["completed", "failed", "timed_out", "unavailable", "skipped"]


class FindingRecord(BaseModel):
    """Unified finding representation aggregated across AST, Ruff, and Bandit."""

    id: str
    file_path: str
    line_number: int
    column: Optional[int] = None
    tool: ScannerTool
    secondary_tools: List[str] = Field(default_factory=list)
    rule_id: str
    category: str
    severity: SeverityLevel
    confidence: ConfidenceLevel
    original_severity: Optional[str] = None
    original_confidence: Optional[str] = None
    title: str
    description: str
    evidence: str
    suggested_fix: Optional[str] = None
    related_findings: List[Dict[str, Any]] = Field(default_factory=list)


class ScannerToolSummary(BaseModel):
    """Execution status and metadata for an individual static analysis tool."""

    status: ScannerExecutionStatus
    findings_count: int = 0
    duration_ms: int = 0
    error: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)


class SkippedScanFile(BaseModel):
    """Record of a file excluded or unreadable during static scanning."""

    file_path: str
    reason: str


class ScanResponse(BaseModel):
    """Structured output returned by POST/GET /api/projects/{project_id}/scan."""

    project_id: str
    scan_id: str
    status: Literal["completed", "partial", "failed"]
    scanned_at: str
    files_scanned: int
    files_skipped: int = 0
    skipped_files: List[SkippedScanFile] = Field(default_factory=list)
    total_findings: int
    severity_summary: Dict[SeverityLevel, int]
    tool_summary: Dict[str, int]
    findings: List[FindingRecord]
    scanner_summary: Dict[str, str]
    scanner_details: Dict[str, ScannerToolSummary]
    limitations: List[str] = Field(default_factory=list)
