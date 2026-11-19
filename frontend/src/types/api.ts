// Exact TypeScript mirrors of RootPatch FastAPI Pydantic schemas (Steps 1-7).

export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  message: string;
}

// --- Step 2: Project Upload & Inspection ---

export interface LanguageInfo {
  name: string;
  file_count: number;
  extensions: string[];
  example_files: string[];
}

export interface SourceDirectory {
  path: string;
  source_file_count: number;
}

export interface ProjectFile {
  path: string;
  name: string;
  ecosystem?: string | null;
}

export interface TopLevelEntry {
  name: string;
  type: "file" | "directory";
}

export interface InspectionReport {
  project_id: string;
  project_name: string;
  root_directory: string;
  total_files: number;
  total_directories: number;
  total_size_bytes: number;
  file_extensions: Record<string, number>;
  languages: LanguageInfo[];
  python_detected: boolean;
  source_directories: SourceDirectory[];
  configuration_files: ProjectFile[];
  dependency_manifests: ProjectFile[];
  documentation_files: string[];
  test_directories: string[];
  test_files: string[];
  test_file_count: number;
  top_level_entries: TopLevelEntry[];
  warnings: string[];
}

export interface ArchiveInfo {
  files_extracted: number;
  extracted_bytes: number;
  skipped_entries: number;
}

export interface ProjectMetadata {
  project_id: string;
  project_name: string;
  original_filename: string;
  created_at: string;
  status: string;
  archive: ArchiveInfo;
  inspection: InspectionReport;
}

export interface UploadResponse {
  project_id: string;
  project_name: string;
  status: string;
  message: string;
}

export interface StructureNode {
  name: string;
  path: string;
  type: "file" | "directory";
  size_bytes?: number | null;
  children?: StructureNode[] | null;
}

export interface StructureResponse {
  project_id: string;
  root_directory: string;
  total_nodes: number;
  truncated: boolean;
  tree: StructureNode;
}

// --- Step 3: Static Bug Detection ---

export type SeverityLevel = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
export type ConfidenceLevel = "HIGH" | "MEDIUM" | "LOW";
export type ScannerTool = "ast" | "ruff" | "bandit";
export type ScannerExecutionStatus =
  | "completed"
  | "failed"
  | "timed_out"
  | "unavailable"
  | "skipped";

export interface FindingRecord {
  id: string;
  file_path: string;
  line_number: number;
  column?: number | null;
  tool: ScannerTool;
  secondary_tools: string[];
  rule_id: string;
  category: string;
  severity: SeverityLevel;
  confidence: ConfidenceLevel;
  original_severity?: string | null;
  original_confidence?: string | null;
  title: string;
  description: string;
  evidence: string;
  suggested_fix?: string | null;
  related_findings: Record<string, unknown>[];
}

export interface ScannerToolSummary {
  status: ScannerExecutionStatus;
  findings_count: number;
  duration_ms: number;
  error?: string | null;
  limitations: string[];
}

export interface SkippedScanFile {
  file_path: string;
  reason: string;
}

export interface ScanResponse {
  project_id: string;
  scan_id: string;
  status: "completed" | "partial" | "failed";
  scanned_at: string;
  files_scanned: number;
  files_skipped: number;
  skipped_files: SkippedScanFile[];
  total_findings: number;
  severity_summary: Record<SeverityLevel, number>;
  tool_summary: Record<string, number>;
  findings: FindingRecord[];
  scanner_summary: Record<string, string>;
  scanner_details: Record<string, ScannerToolSummary>;
  limitations: string[];
}

// --- Step 4: AI Root-Cause Analysis ---

export type AnalysisItemStatus =
  | "completed"
  | "partial"
  | "insufficient_context"
  | "failed";

export interface RootCauseAnalysisItem {
  analysis_id: string;
  project_id: string;
  scan_id: string;
  finding_id: string;
  file_path: string;
  line_number: number;
  rule_id: string;
  root_cause: string;
  technical_explanation: string;
  affected_component: string;
  impact: string;
  recommended_fix: string;
  evidence: string[];
  assumptions_or_uncertainties: string[];
  related_finding_ids: string[];
  relationship_explanation?: string | null;
  confidence: ConfidenceLevel;
  confidence_reason: string;
  analysis_status: AnalysisItemStatus;
}

export interface SharedRootCauseGroup {
  group_id: string;
  shared_cause: string;
  finding_ids: string[];
  explanation: string;
}

export interface AnalysisReportResponse {
  report_id: string;
  project_id: string;
  scan_id: string;
  status: "completed" | "partial" | "empty" | "failed";
  analyzed_at: string;
  provider: string;
  model: string;
  total_findings_in_scan: number;
  analyzed_count: number;
  analyses: RootCauseAnalysisItem[];
  shared_root_cause_groups: SharedRootCauseGroup[];
  limitations: string[];
}

// --- Steps 5 & 6: Patch Generation, Review, Approval & Safe Application ---

export type PatchStatus =
  | "generated"
  | "approved"
  | "rejected"
  | "applied"
  | "application_failed"
  | "stale";
export type ApprovalStatus = "pending" | "approved" | "rejected";
export type ApplicationStatus = "not_applied" | "applied" | "failed" | "stale";
export type ApplicationResult = "applied" | "failed" | "stale";

export interface PatchGenerateRequest {
  finding_id?: string | null;
  analysis_id?: string | null;
}

export interface PatchValidationInfo {
  is_valid: boolean;
  target_file_verified: boolean;
  workspace_confined: boolean;
  hunks_count: number;
  lines_added: number;
  lines_removed: number;
  original_file_sha256: string;
  checks_passed: string[];
}

export interface PatchRecord {
  patch_id: string;
  project_id: string;
  scan_id: string;
  analysis_id: string;
  finding_id: string;
  file_path: string;
  line_number: number;
  rule_id: string;
  status: PatchStatus;
  approval_status: ApprovalStatus;
  application_status: ApplicationStatus;
  applied: boolean;
  summary: string;
  explanation: string;
  confidence: ConfidenceLevel;
  unified_diff: string;
  original_snippet: string;
  proposed_snippet: string;
  assumptions_or_uncertainties: string[];
  validation: PatchValidationInfo;
  generated_at: string;
  provider: string;
  model: string;
  reviewed_at?: string | null;
  review_note?: string | null;
  applied_at?: string | null;
  applied_file_sha256?: string | null;
  backup_path?: string | null;
  application_error?: string | null;
}

export interface RejectedPatchDetail {
  finding_id: string;
  analysis_id: string;
  file_path: string;
  reason: string;
}

export interface PatchBatchResponse {
  batch_id: string;
  project_id: string;
  scan_id: string;
  report_id: string;
  status: "completed" | "partial" | "empty";
  generated_at: string;
  provider: string;
  model: string;
  total_targets: number;
  generated_count: number;
  rejected_count: number;
  patches: PatchRecord[];
  rejected_patches: RejectedPatchDetail[];
  limitations: string[];
}

export interface PatchReviewDecisionRequest {
  comment?: string | null;
}

export interface PatchReviewResponse {
  patch_id: string;
  project_id: string;
  scan_id: string;
  analysis_id: string;
  finding_id: string;
  file_path: string;
  line_number: number;
  rule_id: string;
  status: PatchStatus;
  approval_status: ApprovalStatus;
  application_status: ApplicationStatus;
  applied: boolean;
  summary: string;
  explanation: string;
  confidence: ConfidenceLevel;
  unified_diff: string;
  original_snippet: string;
  proposed_snippet: string;
  original_code?: string | null;
  proposed_code?: string | null;
  is_stale: boolean;
  stale_reason?: string | null;
  can_approve: boolean;
  can_reject: boolean;
  can_apply: boolean;
  validation: PatchValidationInfo;
  generated_at: string;
  reviewed_at?: string | null;
  review_note?: string | null;
  applied_at?: string | null;
  applied_file_sha256?: string | null;
  application_error?: string | null;
  finding_title?: string | null;
  finding_severity?: string | null;
  root_cause?: string | null;
}

export interface PatchApplicationHistoryEntry {
  history_id: string;
  patch_id: string;
  project_id: string;
  finding_id: string;
  file_path: string;
  applied_at: string;
  previous_file_sha256: string;
  new_file_sha256?: string | null;
  result: ApplicationResult;
  backup_path?: string | null;
  error_message?: string | null;
}

export interface PatchApplicationHistoryResponse {
  project_id: string;
  total_events: number;
  applied_count: number;
  failed_count: number;
  stale_count: number;
  history: PatchApplicationHistoryEntry[];
}

export interface PatchApplyResponse {
  message: string;
  patch: PatchRecord;
  application_record: PatchApplicationHistoryEntry;
}

// --- Step 7: Testing & Patch Validation ---

export type ValidationStatus =
  | "PENDING"
  | "RUNNING"
  | "PASSED"
  | "FAILED"
  | "TIMED_OUT"
  | "BLOCKED"
  | "ERROR";

export type TestFrameworkName =
  | "pytest"
  | "unittest"
  | "npm"
  | "vitest"
  | "jest"
  | "node_test"
  | "unsupported"
  | "none";

export interface ValidationRunRequest {
  test_command?: string | string[] | null;
  run_regression?: boolean;
  target_tests_only?: boolean;
}

export interface ContainerExecutionSpec {
  image: string;
  command: string[];
  timeout_seconds: number;
  memory_limit: string;
  cpus: string;
  pids_limit: number;
  network_disabled: boolean;
  read_only_root: boolean;
  non_root_user: string;
  capabilities_dropped: string[];
  no_new_privileges: boolean;
}

export interface RegressionComparison {
  baseline_available: boolean;
  baseline_status?: ValidationStatus | null;
  baseline_exit_code?: number | null;
  baseline_total_tests: number;
  baseline_passed_tests: number;
  baseline_failed_tests: number;
  baseline_skipped_tests: number;
  tests_passed_before_and_after: string[];
  tests_fixed: string[];
  tests_regressed: string[];
  newly_introduced_failures: string[];
  regression_detected: boolean;
  summary: string;
}

export interface ValidationReportResponse {
  validation_id: string;
  project_id: string;
  patch_id: string;
  finding_id: string;
  file_path: string;
  test_framework: TestFrameworkName;
  test_command: string[];
  command_source: "auto_detected" | "override" | "none";
  status: ValidationStatus;
  exit_code?: number | null;
  total_tests: number;
  passed_tests: number;
  failed_tests: number;
  skipped_tests: number;
  error_tests: number;
  duration_ms: number;
  stdout: string;
  stderr: string;
  timed_out: boolean;
  output_truncated: boolean;
  container_available: boolean;
  execution_spec?: ContainerExecutionSpec | null;
  failure_details: string[];
  regression_comparison?: RegressionComparison | null;
  limitations: string[];
  validated_at: string;
}

export interface ValidationHistoryListResponse {
  project_id: string;
  patch_id?: string | null;
  total_runs: number;
  passed_count: number;
  failed_count: number;
  blocked_count: number;
  timed_out_count: number;
  error_count: number;
  validations: ValidationReportResponse[];
}
