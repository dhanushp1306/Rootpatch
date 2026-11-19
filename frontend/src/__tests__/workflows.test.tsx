import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { ApiError, RootPatchApiClient } from "../services/apiClient";
import type {
  AnalysisReportResponse,
  PatchApplicationHistoryResponse,
  PatchBatchResponse,
  PatchRecord,
  PatchReviewResponse,
  ProjectMetadata,
  ProjectStatusResponse,
  ScanResponse,
  StructureResponse,
  ValidationHistoryListResponse,
  ValidationReportResponse,
} from "../types/api";

const PROJECT_ID = "0123456789abcdef0123456789abcdef";

function makeProject(): ProjectMetadata {
  return {
    project_id: PROJECT_ID,
    project_name: "sample-py-app",
    original_filename: "sample-py-app.zip",
    created_at: "2026-01-01T12:00:00Z",
    status: "ready",
    archive: { files_extracted: 4, extracted_bytes: 2048, skipped_entries: 0 },
    inspection: {
      project_id: PROJECT_ID,
      project_name: "sample-py-app",
      root_directory: "source",
      total_files: 4,
      total_directories: 2,
      total_size_bytes: 2048,
      file_extensions: { ".py": 3, ".txt": 1 },
      languages: [{ name: "Python", file_count: 3, extensions: [".py"], example_files: ["app.py"] }],
      python_detected: true,
      source_directories: [{ path: "src", source_file_count: 2 }],
      configuration_files: [{ path: "pyproject.toml", name: "pyproject.toml" }],
      dependency_manifests: [
        { path: "requirements.txt", name: "requirements.txt", ecosystem: "python" },
      ],
      documentation_files: ["README.md"],
      test_directories: ["tests"],
      test_files: ["tests/test_app.py"],
      test_file_count: 1,
      top_level_entries: [
        { name: "src", type: "directory" },
        { name: "tests", type: "directory" },
      ],
      warnings: [],
    },
  };
}

function makeStructure(): StructureResponse {
  return {
    project_id: PROJECT_ID,
    root_directory: "source",
    total_nodes: 3,
    truncated: false,
    tree: {
      name: "source",
      path: ".",
      type: "directory",
      children: [
        {
          name: "src",
          path: "src",
          type: "directory",
          children: [
            { name: "app.py", path: "src/app.py", type: "file", size_bytes: 512 },
          ],
        },
        {
          name: "tests",
          path: "tests",
          type: "directory",
          children: [
            { name: "test_app.py", path: "tests/test_app.py", type: "file", size_bytes: 256 },
          ],
        },
      ],
    },
  };
}

function makeScan(): ScanResponse {
  return {
    project_id: PROJECT_ID,
    scan_id: "scan-1",
    status: "completed",
    scanned_at: "2026-01-01T12:01:00Z",
    files_scanned: 2,
    files_skipped: 0,
    skipped_files: [],
    total_findings: 1,
    severity_summary: { CRITICAL: 0, HIGH: 1, MEDIUM: 0, LOW: 0, INFO: 0 },
    tool_summary: { bandit: 1 },
    findings: [
      {
        id: "finding-1",
        file_path: "src/app.py",
        line_number: 12,
        column: 4,
        tool: "bandit",
        secondary_tools: [],
        rule_id: "B602",
        category: "security",
        severity: "HIGH",
        confidence: "HIGH",
        title: "Subprocess call with shell=True",
        description: "Avoid shell=True in subprocess.run",
        evidence: "subprocess.run(cmd, shell=True)",
        suggested_fix: "Pass argument list with shell=False",
        related_findings: [],
      },
    ],
    scanner_summary: { bandit: "completed" },
    scanner_details: {
      bandit: { status: "completed", findings_count: 1, duration_ms: 42, limitations: [] },
    },
    limitations: [],
  };
}

function makeAnalysis(): AnalysisReportResponse {
  return {
    report_id: "rep-1",
    project_id: PROJECT_ID,
    scan_id: "scan-1",
    status: "completed",
    analyzed_at: "2026-01-01T12:02:00Z",
    provider: "gemini",
    model: "gemini-4-hydrogen",
    total_findings_in_scan: 1,
    analyzed_count: 1,
    analyses: [
      {
        analysis_id: "ana-1",
        project_id: PROJECT_ID,
        scan_id: "scan-1",
        finding_id: "finding-1",
        file_path: "src/app.py",
        line_number: 12,
        rule_id: "B602",
        root_cause: "Untrusted command string interpolated into shell subprocess",
        technical_explanation: "Using shell=True invokes /bin/sh and enables command injection.",
        affected_component: "src/app.py:run_task",
        impact: "Arbitrary command execution",
        recommended_fix: "Use shlex.split and shell=False",
        evidence: ["Line 12 passes shell=True"],
        assumptions_or_uncertainties: [],
        related_finding_ids: [],
        confidence: "HIGH",
        confidence_reason: "Direct shell=True keyword detected",
        analysis_status: "completed",
      },
    ],
    shared_root_cause_groups: [],
    limitations: [],
  };
}

function makePatchRecord(overrides: Partial<PatchRecord> = {}): PatchRecord {
  return {
    patch_id: "patch-1",
    project_id: PROJECT_ID,
    scan_id: "scan-1",
    analysis_id: "ana-1",
    finding_id: "finding-1",
    file_path: "src/app.py",
    line_number: 12,
    rule_id: "B602",
    status: "generated",
    approval_status: "pending",
    application_status: "not_applied",
    applied: false,
    summary: "Disable shell=True in subprocess call",
    explanation: "Replaces shell=True with shell=False and list args.",
    confidence: "HIGH",
    unified_diff: "--- a/src/app.py\n+++ b/src/app.py\n@@ -11,1 +11,1 @@\n-subprocess.run(cmd, shell=True)\n+subprocess.run(args, shell=False)",
    original_snippet: "subprocess.run(cmd, shell=True)",
    proposed_snippet: "subprocess.run(args, shell=False)",
    assumptions_or_uncertainties: [],
    validation: {
      is_valid: true,
      target_file_verified: true,
      workspace_confined: true,
      hunks_count: 1,
      lines_added: 1,
      lines_removed: 1,
      original_file_sha256: "deadbeef1234567890abcdef",
      checks_passed: ["workspace_confined", "target_exists", "hunk_matches"],
    },
    generated_at: "2026-01-01T12:03:00Z",
    provider: "gemini",
    model: "gemini-4-hydrogen",
    ...overrides,
  };
}

function makePatchReview(overrides: Partial<PatchReviewResponse> = {}): PatchReviewResponse {
  return {
    ...makePatchRecord(),
    original_code: "def run(cmd):\n    subprocess.run(cmd, shell=True)\n",
    proposed_code: "def run(args):\n    subprocess.run(args, shell=False)\n",
    is_stale: false,
    can_approve: true,
    can_reject: true,
    can_apply: false,
    finding_title: "Subprocess call with shell=True",
    finding_severity: "HIGH",
    root_cause: "Untrusted command string interpolated into shell subprocess",
    ...overrides,
  };
}

interface MockOptions {
  scan?: boolean;
  analysis?: boolean;
  patches?: boolean;
  projectMissing?: boolean;
}

function notFound(detail: string, code: string): ApiError {
  return new ApiError(404, detail, code);
}

function createMockClient(options: MockOptions = {}) {
  const has = {
    scan: options.scan ?? false,
    analysis: options.analysis ?? false,
    patches: options.patches ?? false,
  };
  const project = makeProject();
  const structure = makeStructure();
  const scan = makeScan();
  const analysis = makeAnalysis();
  let currentPatch = makePatchRecord();
  let currentReview = makePatchReview();
  const history: PatchApplicationHistoryResponse = {
    project_id: PROJECT_ID,
    total_events: 0,
    applied_count: 0,
    failed_count: 0,
    stale_count: 0,
    history: [],
  };
  const validations: ValidationHistoryListResponse = {
    project_id: PROJECT_ID,
    total_runs: 0,
    passed_count: 0,
    failed_count: 0,
    blocked_count: 0,
    timed_out_count: 0,
    error_count: 0,
    validations: [],
  };

  const client = {
    getHealth: vi.fn().mockResolvedValue({
      status: "healthy",
      app: "RootPatch",
      version: "0.1.0",
      message: "Backend healthy",
    }),
    uploadProject: vi.fn().mockResolvedValue({
      project_id: PROJECT_ID,
      project_name: "sample-py-app",
      status: "ready",
      message: "Uploaded successfully",
    }),
    getProject: vi.fn().mockImplementation(async () => {
      if (options.projectMissing) throw notFound("Project not found.", "project_not_found");
      return project;
    }),
    getProjectStatus: vi.fn().mockImplementation(async (): Promise<ProjectStatusResponse> => {
      if (options.projectMissing) throw notFound("Project not found.", "project_not_found");
      const res = (available: boolean) => ({
        state: available ? ("available" as const) : ("missing" as const),
        available,
      });
      return {
        project_id: PROJECT_ID,
        project_name: "sample-py-app",
        project: res(true),
        structure: res(true),
        scan: res(has.scan),
        analysis: res(has.analysis),
        patches: res(has.patches),
        validations: res(validations.total_runs > 0),
        patch_counts: { total: has.patches ? 1 : 0, by_status: {} },
        can_analyze: true,
        can_generate_patches: has.analysis,
      };
    }),
    getProjectStructure: vi.fn().mockResolvedValue(structure),
    runScan: vi.fn().mockImplementation(async () => {
      has.scan = true;
      return scan;
    }),
    getScan: vi.fn().mockImplementation(async () => {
      if (!has.scan) throw notFound("No scan results found for this project.", "scan_not_found");
      return scan;
    }),
    runAnalysis: vi.fn().mockImplementation(async () => {
      has.analysis = true;
      return analysis;
    }),
    getAnalysis: vi.fn().mockImplementation(async () => {
      if (!has.analysis)
        throw notFound("No analysis results found for this project.", "analysis_not_found");
      return analysis;
    }),
    generatePatches: vi.fn().mockImplementation(async (): Promise<PatchBatchResponse> => {
      has.patches = true;
      return {
      batch_id: "batch-1",
      project_id: PROJECT_ID,
      scan_id: "scan-1",
      report_id: "rep-1",
      status: "completed",
      generated_at: "2026-01-01T12:03:00Z",
      provider: "gemini",
      model: "gemini-4-hydrogen",
      total_targets: 1,
      generated_count: 1,
      rejected_count: 0,
      patches: [currentPatch],
      rejected_patches: [],
      limitations: [],
      };
    }),
    getPatches: vi.fn().mockImplementation(async (): Promise<PatchBatchResponse> => {
      if (!has.patches) throw notFound("No generated patches found for this project.", "patches_not_found");
      return {
      batch_id: "batch-1",
      project_id: PROJECT_ID,
      scan_id: "scan-1",
      report_id: "rep-1",
      status: "completed",
      generated_at: "2026-01-01T12:03:00Z",
      provider: "gemini",
      model: "gemini-4-hydrogen",
      total_targets: 1,
      generated_count: 1,
      rejected_count: 0,
      patches: [currentPatch],
      rejected_patches: [],
      limitations: [],
      };
    }),
    getPatchReview: vi.fn().mockImplementation(async () => currentReview),
    approvePatch: vi.fn().mockImplementation(async () => {
      currentPatch = makePatchRecord({
        status: "approved",
        approval_status: "approved",
      });
      currentReview = makePatchReview({
        status: "approved",
        approval_status: "approved",
        can_approve: false,
        can_reject: true,
        can_apply: true,
      });
      return currentPatch;
    }),
    rejectPatch: vi.fn().mockImplementation(async () => {
      currentPatch = makePatchRecord({
        status: "rejected",
        approval_status: "rejected",
      });
      currentReview = makePatchReview({
        status: "rejected",
        approval_status: "rejected",
        can_approve: false,
        can_reject: false,
        can_apply: false,
      });
      return currentPatch;
    }),
    applyPatch: vi.fn().mockImplementation(async () => {
      currentPatch = makePatchRecord({
        status: "applied",
        approval_status: "approved",
        application_status: "applied",
        applied: true,
      });
      currentReview = makePatchReview({
        status: "applied",
        approval_status: "approved",
        application_status: "applied",
        applied: true,
        can_approve: false,
        can_reject: false,
        can_apply: false,
      });
      const rec = {
        history_id: "hist-1",
        patch_id: "patch-1",
        project_id: PROJECT_ID,
        finding_id: "finding-1",
        file_path: "src/app.py",
        applied_at: "2026-01-01T12:04:00Z",
        previous_file_sha256: "deadbeef1234",
        new_file_sha256: "cafebabe5678",
        result: "applied" as const,
        backup_path: "backups/src/app.py.bak",
      };
      history.total_events = 1;
      history.applied_count = 1;
      history.history = [rec];
      return {
        message: "Patch applied successfully.",
        patch: currentPatch,
        application_record: rec,
      };
    }),
    getPatchHistory: vi.fn().mockImplementation(async () => history),
    getProjectValidations: vi.fn().mockImplementation(async () => validations),
    getPatchValidations: vi.fn().mockImplementation(async () => validations),
    validatePatch: vi.fn().mockImplementation(async (): Promise<ValidationReportResponse> => {
      const report: ValidationReportResponse = {
        validation_id: "val-1",
        project_id: PROJECT_ID,
        patch_id: "patch-1",
        finding_id: "finding-1",
        file_path: "src/app.py",
        test_framework: "pytest",
        test_command: ["pytest", "-q"],
        command_source: "auto_detected",
        status: "PASSED",
        exit_code: 0,
        total_tests: 3,
        passed_tests: 3,
        failed_tests: 0,
        skipped_tests: 0,
        error_tests: 0,
        duration_ms: 340,
        stdout: "3 passed in 0.34s",
        stderr: "",
        timed_out: false,
        output_truncated: false,
        container_available: true,
        execution_spec: {
          image: "python:3.11-slim",
          command: ["pytest", "-q"],
          timeout_seconds: 60,
          memory_limit: "512m",
          cpus: "1.0",
          pids_limit: 64,
          network_disabled: true,
          read_only_root: true,
          non_root_user: "nobody",
          capabilities_dropped: ["ALL"],
          no_new_privileges: true,
        },
        failure_details: [],
        regression_comparison: {
          baseline_available: true,
          baseline_status: "FAILED",
          baseline_exit_code: 1,
          baseline_total_tests: 3,
          baseline_passed_tests: 2,
          baseline_failed_tests: 1,
          baseline_skipped_tests: 0,
          tests_passed_before_and_after: ["test_one", "test_two"],
          tests_fixed: ["test_shell_safety"],
          tests_regressed: [],
          newly_introduced_failures: [],
          regression_detected: false,
          summary: "1 failing baseline test fixed; 0 regressions.",
        },
        limitations: [],
        validated_at: "2026-01-01T12:05:00Z",
      };
      validations.total_runs = 1;
      validations.passed_count = 1;
      validations.validations = [report];
      return report;
    }),
  } as unknown as RootPatchApiClient;

  return { client };
}

describe("RootPatch Step 8 Frontend Workflows", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("handles zip archive upload and renders inspection report", async () => {
    const user = userEvent.setup();
    const { client } = createMockClient();

    render(<App client={client} initialSection="upload" />);

    const fileInput = screen.getByLabelText(/project archive file/i);
    const zipFile = new File(["PK\x03\x04"], "sample-py-app.zip", { type: "application/zip" });
    await user.upload(fileInput, zipFile);

    await user.click(screen.getByRole("button", { name: /upload & inspect/i }));

    await waitFor(() => {
      expect(screen.getByText(/inspection report/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/requirements\.txt/i)).toBeInTheDocument();
    expect(client.uploadProject).toHaveBeenCalledTimes(1);
  });

  it("explores structure tree, runs static scan & root-cause analysis, and approves/applies patch", async () => {
    const user = userEvent.setup();
    const { client } = createMockClient();
    window.localStorage.setItem(
      "rootpatch.known_projects.v1",
      JSON.stringify([{ project_id: PROJECT_ID, project_name: "sample-py-app", added_at: "2026-01-01T12:00:00Z" }])
    );
    window.localStorage.setItem("rootpatch.active_project_id.v1", PROJECT_ID);

    render(<App client={client} initialSection="structure" />);

    // Structure explorer
    await waitFor(() => {
      expect(screen.getByText("app.py")).toBeInTheDocument();
    });
    await user.click(screen.getByText("app.py"));
    expect(screen.getByText("src/app.py")).toBeInTheDocument();

    // Navigate to Bugs & Root Cause
    await user.click(screen.getByRole("button", { name: /bugs & root cause/i }));
    await user.click(screen.getByRole("button", { name: /run static scan/i }));

    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /subprocess call with shell=true/i })
      ).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /analyze root causes/i }));
    await waitFor(() => {
      expect(
        screen.getByText(/untrusted command string interpolated into shell subprocess/i)
      ).toBeInTheDocument();
    });

    // Generate patch and review
    await user.click(screen.getByRole("button", { name: /generate all patches/i }));
    await user.click(screen.getByRole("button", { name: /open patch review/i }));

    await waitFor(() => {
      expect(screen.getByText(/before \/ after comparison/i)).toBeInTheDocument();
    });

    const approveBtn = screen.getByRole("button", { name: /approve patch/i });
    const applyBtn = screen.getByRole("button", { name: /apply patch/i });

    expect(approveBtn).toBeEnabled();
    expect(applyBtn).toBeDisabled();

    await user.click(approveBtn);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /apply patch/i })).toBeEnabled();
    });

    await user.click(screen.getByRole("button", { name: /apply patch/i }));

    await waitFor(() => {
      expect(screen.getByText(/patch applied safely/i)).toBeInTheDocument();
    });

    // Validate applied patch
    await user.click(screen.getByRole("button", { name: /validate applied patch/i }));
    await user.click(screen.getByRole("button", { name: /run isolated validation/i }));

    await waitFor(() => {
      expect(screen.getByText(/1 failing baseline test fixed; 0 regressions\./i)).toBeInTheDocument();
    });
    expect(screen.getByText(/3 passed in 0\.34s/i)).toBeInTheDocument();

    // Check History view
    await user.click(screen.getByRole("button", { name: /^history$/i }));
    await waitFor(() => {
      expect(screen.getByText(/backups\/src\/app\.py\.bak/i)).toBeInTheDocument();
    });
  });

  it("strips ANSI escape sequences and disables apply/validate on stale or unapplied patches", async () => {
    const user = userEvent.setup();
    const { client } = createMockClient({ scan: true, analysis: true, patches: true });

    vi.spyOn(client, "getPatchReview").mockResolvedValue(
      makePatchReview({
        is_stale: true,
        stale_reason: "Target file modified outside patch workflow.",
        can_approve: false,
        can_reject: false,
        can_apply: false,
        unified_diff:
          "--- a/src/app.py\n+++ b/src/app.py\n@@ -1,1 +1,1 @@\n-\x1b[31mbad()\x1b[0m\n+good()",
      })
    );

    window.localStorage.setItem(
      "rootpatch.known_projects.v1",
      JSON.stringify([
        { project_id: PROJECT_ID, project_name: "sample-py-app", added_at: "2026-01-01T12:00:00Z" },
      ])
    );
    window.localStorage.setItem("rootpatch.active_project_id.v1", PROJECT_ID);

    render(<App client={client} initialSection="patches" />);

    await waitFor(() => {
      expect(screen.getByText(/target file changed \(stale patch\)/i)).toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: /approve patch/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /reject patch/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /apply patch/i })).toBeDisabled();
    expect(screen.getByText(/-bad\(\)/i)).toBeInTheDocument();
    expect(screen.queryByText(/\x1b\[31m/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^validation$/i }));
    await waitFor(() => {
      expect(screen.getByText(/patch must be applied before validation/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /run isolated validation/i })).toBeDisabled();
  });

  it("displays explicit BLOCKED warning when Docker is unavailable during validation", async () => {
    const user = userEvent.setup();
    const { client } = createMockClient({ scan: true, analysis: true, patches: true });

    const appliedPatch = makePatchRecord({
      status: "applied",
      approval_status: "approved",
      application_status: "applied",
      applied: true,
    });

    vi.spyOn(client, "getPatches").mockResolvedValue({
      batch_id: "b1",
      project_id: PROJECT_ID,
      scan_id: "scan-1",
      report_id: "rep-1",
      status: "completed",
      generated_at: "2026-01-01T12:03:00Z",
      provider: "gemini",
      model: "gemini-4-hydrogen",
      total_targets: 1,
      generated_count: 1,
      rejected_count: 0,
      patches: [appliedPatch],
      rejected_patches: [],
      limitations: [],
    });

    vi.spyOn(client, "validatePatch").mockResolvedValue({
      validation_id: "val-blocked",
      project_id: PROJECT_ID,
      patch_id: "patch-1",
      finding_id: "finding-1",
      file_path: "src/app.py",
      test_framework: "pytest",
      test_command: ["pytest"],
      command_source: "auto_detected",
      status: "BLOCKED",
      exit_code: null,
      total_tests: 0,
      passed_tests: 0,
      failed_tests: 0,
      skipped_tests: 0,
      error_tests: 0,
      duration_ms: 5,
      stdout: "",
      stderr: "Docker daemon is not running.",
      timed_out: false,
      output_truncated: false,
      container_available: false,
      execution_spec: null,
      failure_details: ["Docker daemon unavailable; host execution refused."],
      regression_comparison: null,
      limitations: ["Container isolation unavailable"],
      validated_at: "2026-01-01T12:05:00Z",
    });

    window.localStorage.setItem(
      "rootpatch.known_projects.v1",
      JSON.stringify([{ project_id: PROJECT_ID, project_name: "sample-py-app", added_at: "2026-01-01T12:00:00Z" }])
    );
    window.localStorage.setItem("rootpatch.active_project_id.v1", PROJECT_ID);

    render(<App client={client} initialSection="validation" />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /run isolated validation/i })).toBeEnabled();
    });

    await user.click(screen.getByRole("button", { name: /run isolated validation/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/validation blocked: docker container runtime unavailable/i)
      ).toBeInTheDocument();
    });
  });
});


function seedActiveProject() {
  window.localStorage.setItem(
    "rootpatch.known_projects.v1",
    JSON.stringify([
      { project_id: PROJECT_ID, project_name: "sample-py-app", added_at: "2026-01-01T12:00:00Z" },
    ])
  );
  window.localStorage.setItem("rootpatch.active_project_id.v1", PROJECT_ID);
}

describe("API integration: status-gated optional resources", () => {
  beforeEach(() => {
    window.localStorage.clear();
    seedActiveProject();
  });

  it("new project: loads details + structure without requesting analysis/patches/scan (StrictMode)", async () => {
    const { client } = createMockClient();
    render(
      <StrictMode>
        <App client={client} initialSection="structure" />
      </StrictMode>
    );

    await waitFor(() => expect(screen.getByText("app.py")).toBeInTheDocument());

    expect(client.getProject).toHaveBeenCalledTimes(1);
    expect(client.getProjectStatus).toHaveBeenCalledTimes(1);
    expect(client.getProjectStructure).toHaveBeenCalledTimes(1);
    expect(client.getScan).not.toHaveBeenCalled();
    expect(client.getAnalysis).not.toHaveBeenCalled();
    expect(client.getPatches).not.toHaveBeenCalled();
    expect(client.getPatchHistory).not.toHaveBeenCalled();
    expect(client.getProjectValidations).not.toHaveBeenCalled();
  });

  it("shows empty states for missing scan and patches instead of failing", async () => {
    const user = userEvent.setup();
    const { client } = createMockClient();
    render(<App client={client} initialSection="findings" />);

    await waitFor(() =>
      expect(screen.getByText(/static scan not yet executed/i)).toBeInTheDocument()
    );
    expect(screen.getByRole("button", { name: /scan and analyze/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^patch review/i }));
    expect(await screen.findByText(/no patches generated yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /open bugs & root cause/i })).toBeInTheDocument();
    expect(client.getAnalysis).not.toHaveBeenCalled();
    expect(client.getPatches).not.toHaveBeenCalled();
  });

  it("analyze runs a real scan first, refreshes analysis state, then offers Generate Patches", async () => {
    const user = userEvent.setup();
    const { client } = createMockClient();
    render(<App client={client} initialSection="findings" />);

    await user.click(await screen.findByRole("button", { name: /analyze root causes/i }));

    await waitFor(() =>
      expect(
        screen.getByText(/untrusted command string interpolated into shell subprocess/i)
      ).toBeInTheDocument()
    );
    expect(client.runScan).toHaveBeenCalledTimes(1);
    expect(client.runAnalysis).toHaveBeenCalledTimes(1);

    // status refreshed after analysis, patches still missing -> Generate Patches action
    const generate = await screen.findByRole("button", { name: /^generate patches$/i });
    expect(vi.mocked(client.getProjectStatus).mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(client.getPatches).not.toHaveBeenCalled();

    await user.click(generate);
    await waitFor(() => expect(client.generatePatches).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /^generate patches$/i })).not.toBeInTheDocument()
    );
  });

  it("patch page offers Generate Patches when analysis exists but patches do not", async () => {
    const user = userEvent.setup();
    const { client } = createMockClient({ scan: true, analysis: true });
    render(<App client={client} initialSection="patches" />);

    const button = await screen.findByRole("button", { name: /^generate patches$/i });
    expect(client.getPatches).not.toHaveBeenCalled();
    await user.click(button);

    await waitFor(() =>
      expect(screen.getByText(/before \/ after comparison/i)).toBeInTheDocument()
    );
    expect(client.generatePatches).toHaveBeenCalledTimes(1);
  });

  it("shows a proper error for a genuinely missing project", async () => {
    const { client } = createMockClient({ projectMissing: true });
    render(<App client={client} initialSection="dashboard" />);

    expect(await screen.findByText(/project not found/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /remove from recent projects/i })).toBeInTheDocument();
    expect(client.getAnalysis).not.toHaveBeenCalled();
    expect(client.getPatches).not.toHaveBeenCalled();
  });

  it("existing project with completed results loads each resource exactly once and survives reload", async () => {
    const { client } = createMockClient({ scan: true, analysis: true, patches: true });
    const first = render(
      <StrictMode>
        <App client={client} initialSection="patches" />
      </StrictMode>
    );

    await waitFor(() =>
      expect(screen.getByText(/before \/ after comparison/i)).toBeInTheDocument()
    );
    expect(client.getScan).toHaveBeenCalledTimes(1);
    expect(client.getAnalysis).toHaveBeenCalledTimes(1);
    expect(client.getPatches).toHaveBeenCalledTimes(1);
    expect(client.getPatchHistory).toHaveBeenCalledTimes(1);

    // simulate a browser refresh: remount; results are still available
    first.unmount();
    render(<App client={client} initialSection="patches" />);
    await waitFor(() =>
      expect(screen.getByText(/before \/ after comparison/i)).toBeInTheDocument()
    );
  });

  it("surfaces a genuine backend failure of a stored resource", async () => {
    const { client } = createMockClient({ scan: true, analysis: true });
    vi.spyOn(client, "getAnalysis").mockRejectedValue(
      new ApiError(500, "Stored analysis results are corrupted or unreadable.", "analysis_error")
    );
    render(<App client={client} initialSection="findings" />);
    expect(await screen.findByText(/could not load analysis/i)).toBeInTheDocument();
    expect(screen.getByText(/corrupted or unreadable/i)).toBeInTheDocument();
  });
});
