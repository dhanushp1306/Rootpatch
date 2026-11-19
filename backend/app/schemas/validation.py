"""Schemas for Step 7 isolated testing and patch validation."""

from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field

ValidationStatus = Literal[
    "PENDING",
    "RUNNING",
    "PASSED",
    "FAILED",
    "TIMED_OUT",
    "BLOCKED",
    "ERROR",
]
TestFrameworkName = Literal[
    "pytest",
    "unittest",
    "npm",
    "vitest",
    "jest",
    "node_test",
    "unsupported",
    "none",
]
CommandSource = Literal["auto_detected", "override", "none"]


class ValidationRunRequest(BaseModel):
    """Optional parameters controlling a patch validation run."""

    test_command: Optional[Union[str, List[str]]] = Field(
        default=None,
        description="Optional allowlisted test command override (no shell execution).",
    )
    run_regression: bool = Field(
        default=True,
        description="When true and original archive exists, compare baseline vs. patched test outcomes.",
    )
    target_tests_only: bool = Field(
        default=False,
        description="When true and matching test files are detected, narrow execution to relevant tests.",
    )


class TestDetectionResult(BaseModel):
    """Result of statically detecting the project's test framework and safe command."""

    __test__ = False

    detected: bool
    ecosystem: Optional[str] = None
    framework: TestFrameworkName
    command: List[str] = Field(default_factory=list)
    container_image: Optional[str] = None
    test_files_found: List[str] = Field(default_factory=list)
    config_files_found: List[str] = Field(default_factory=list)
    reason: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)


class ContainerExecutionSpec(BaseModel):
    """Hardened Docker isolation settings applied to each test execution container."""

    image: str
    command: List[str]
    timeout_seconds: int
    memory_limit: str
    cpus: str
    pids_limit: int
    network_disabled: bool = True
    read_only_root: bool = True
    non_root_user: str = "65534:65534"
    capabilities_dropped: List[str] = Field(default_factory=lambda: ["ALL"])
    no_new_privileges: bool = True


class ContainerRunResult(BaseModel):
    """Raw bounded output and exit metadata returned by the container runner."""

    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timed_out: bool = False
    output_truncated: bool = False
    container_available: bool = True
    error_message: Optional[str] = None


class ParsedTestSummary(BaseModel):
    """Structured test counts and per-case outcomes parsed from test runner output."""

    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    skipped_tests: int = 0
    error_tests: int = 0
    passed_case_ids: List[str] = Field(default_factory=list)
    failed_case_ids: List[str] = Field(default_factory=list)
    skipped_case_ids: List[str] = Field(default_factory=list)
    error_case_ids: List[str] = Field(default_factory=list)
    failure_details: List[str] = Field(default_factory=list)


class RegressionComparison(BaseModel):
    """Comparison of unpatched baseline test behavior against the patched project."""

    baseline_available: bool
    baseline_status: Optional[ValidationStatus] = None
    baseline_exit_code: Optional[int] = None
    baseline_total_tests: int = 0
    baseline_passed_tests: int = 0
    baseline_failed_tests: int = 0
    baseline_skipped_tests: int = 0
    tests_passed_before_and_after: List[str] = Field(default_factory=list)
    tests_fixed: List[str] = Field(default_factory=list)
    tests_regressed: List[str] = Field(default_factory=list)
    newly_introduced_failures: List[str] = Field(default_factory=list)
    regression_detected: bool = False
    summary: str


class ValidationReportResponse(BaseModel):
    """Structured, persisted report for a single patch validation run."""

    validation_id: str
    project_id: str
    patch_id: str
    finding_id: str
    file_path: str
    test_framework: TestFrameworkName
    test_command: List[str] = Field(default_factory=list)
    command_source: CommandSource = "auto_detected"
    status: ValidationStatus
    exit_code: Optional[int] = None
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    skipped_tests: int = 0
    error_tests: int = 0
    duration_ms: int = 0
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    output_truncated: bool = False
    container_available: bool = True
    execution_spec: Optional[ContainerExecutionSpec] = None
    failure_details: List[str] = Field(default_factory=list)
    regression_comparison: Optional[RegressionComparison] = None
    limitations: List[str] = Field(default_factory=list)
    validated_at: str


class ValidationHistoryListResponse(BaseModel):
    """Validation run history for a project or a specific patch."""

    project_id: str
    patch_id: Optional[str] = None
    total_runs: int
    passed_count: int
    failed_count: int
    blocked_count: int
    timed_out_count: int
    error_count: int
    validations: List[ValidationReportResponse] = Field(default_factory=list)


class ValidationStore(BaseModel):
    """On-disk persistence envelope for validation reports (newest first)."""

    validations: List[ValidationReportResponse] = Field(default_factory=list)
