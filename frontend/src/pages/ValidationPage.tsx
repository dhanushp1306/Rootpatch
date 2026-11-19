import { FlaskConical, Loader2, Shield } from "lucide-react";
import { useEffect, useState } from "react";
import { EmptyState, StateBanner } from "../components/StateBanner";
import { StatusText } from "../components/StatusText";
import { ApiError, RootPatchApiClient } from "../services/apiClient";
import type {
  PatchBatchResponse,
  ProjectMetadata,
  ValidationReportResponse,
} from "../types/api";
import { formatTimestamp, sanitizeDisplayText, sanitizeSingleLine } from "../utils/sanitize";

interface ValidationPageProps {
  client: RootPatchApiClient;
  project: ProjectMetadata | null;
  patches: PatchBatchResponse | null;
  preferredPatchId: string | null;
  onValidationComplete: () => Promise<void> | void;
  onGoToPatches: () => void;
  onGoToUpload: () => void;
}

export function ValidationPage({
  client,
  project,
  patches,
  preferredPatchId,
  onValidationComplete,
  onGoToPatches,
  onGoToUpload,
}: ValidationPageProps) {
  const patchList = patches?.patches ?? [];
  const [selectedPatchId, setSelectedPatchId] = useState<string>("");
  const [testCommand, setTestCommand] = useState("");
  const [runRegression, setRunRegression] = useState(true);
  const [targetTestsOnly, setTargetTestsOnly] = useState(false);

  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [latestReport, setLatestReport] = useState<ValidationReportResponse | null>(null);
  const [patchHistory, setPatchHistory] = useState<ValidationReportResponse[]>([]);

  const effectivePatch =
    patchList.find((p) => p.patch_id === (selectedPatchId || preferredPatchId)) ??
    patchList.find((p) => p.applied) ??
    patchList[0] ??
    null;

  useEffect(() => {
    if (preferredPatchId) {
      setSelectedPatchId(preferredPatchId);
    }
  }, [preferredPatchId]);

  useEffect(() => {
    if (!project || !effectivePatch) {
      setPatchHistory([]);
      return;
    }

    let cancelled = false;
    client
      .getPatchValidations(project.project_id, effectivePatch.patch_id)
      .then((res) => {
        if (!cancelled) {
          setPatchHistory(res.validations);
          setLatestReport((prev) =>
            prev && prev.patch_id === effectivePatch.patch_id
              ? prev
              : res.validations[0] ?? null
          );
        }
      })
      .catch(() => {
        if (!cancelled) {
          setPatchHistory([]);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [client, project, effectivePatch?.patch_id]);

  if (!project) {
    return (
      <EmptyState
        title="No Project Selected"
        description="Upload or open a project workspace before validating patches."
        action={
          <button
            type="button"
            onClick={onGoToUpload}
            className="rounded-md bg-blue-700 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-800 whitespace-nowrap"
          >
            Go to Upload
          </button>
        }
      />
    );
  }

  if (patchList.length === 0) {
    return (
      <EmptyState
        title="No Patches Available for Validation"
        description="Generate, approve, and apply a patch before running container-isolated validation."
        action={
          <button
            type="button"
            onClick={onGoToPatches}
            className="rounded-md bg-blue-700 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-800 whitespace-nowrap"
          >
            Open Patch Review
          </button>
        }
      />
    );
  }

  const handleRunValidation = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!effectivePatch) return;
    setRunning(true);
    setError(null);
    try {
      const report = await client.validatePatch(project.project_id, effectivePatch.patch_id, {
        test_command: testCommand.trim() || undefined,
        run_regression: runRegression,
        target_tests_only: targetTestsOnly,
      });
      setLatestReport(report);
      const historyRes = await client.getPatchValidations(
        project.project_id,
        effectivePatch.patch_id
      );
      setPatchHistory(historyRes.validations);
      await onValidationComplete();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Patch validation request failed.");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-6">
      <form
        onSubmit={handleRunValidation}
        className="rounded-lg border border-slate-200 bg-white p-5 space-y-4"
      >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-slate-900">
              Isolated Container Patch Validation
            </h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Runs project tests inside a network-disabled, read-only rootfs Docker container. Never
              executes untrusted code on the host.
            </p>
          </div>
          {effectivePatch ? <StatusText label={effectivePatch.status} /> : null}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label htmlFor="validation-patch-select" className="block text-xs font-medium text-slate-700">
              Target Patch
            </label>
            <select
              id="validation-patch-select"
              value={effectivePatch?.patch_id ?? ""}
              onChange={(e) => {
                setSelectedPatchId(e.target.value);
                setLatestReport(null);
                setError(null);
              }}
              className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-xs text-slate-900 focus:border-blue-600 focus:outline-none"
            >
              {patchList.map((p) => (
                <option key={p.patch_id} value={p.patch_id}>
                  {sanitizeSingleLine(p.file_path)} — {sanitizeSingleLine(p.summary)} [{p.status}]
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="validation-cmd-override" className="block text-xs font-medium text-slate-700">
              Optional Test Command Override (allowlisted)
            </label>
            <input
              id="validation-cmd-override"
              type="text"
              value={testCommand}
              onChange={(e) => setTestCommand(e.target.value)}
              placeholder="Auto-detected if left blank (e.g. pytest -q)"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-xs text-slate-900 focus:border-blue-600 focus:outline-none"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-6 text-xs text-slate-700">
          <label className="inline-flex items-center gap-2">
            <input
              type="checkbox"
              checked={runRegression}
              onChange={(e) => setRunRegression(e.target.checked)}
              className="rounded border-slate-300 text-blue-700"
            />
            <span>Run baseline vs patched regression comparison</span>
          </label>
          <label className="inline-flex items-center gap-2">
            <input
              type="checkbox"
              checked={targetTestsOnly}
              onChange={(e) => setTargetTestsOnly(e.target.checked)}
              className="rounded border-slate-300 text-blue-700"
            />
            <span>Target related test files only</span>
          </label>
        </div>

        {effectivePatch && !effectivePatch.applied ? (
          <StateBanner
            variant="warning"
            title="Patch Must Be Applied Before Validation"
            message="The backend enforces strict state control and returns HTTP 409 for unapplied patches. Approve and apply this patch in Patch Review first."
            action={
              <button
                type="button"
                onClick={onGoToPatches}
                className="rounded-md border border-amber-400 bg-white px-3 py-1.5 text-xs font-semibold text-amber-900 hover:bg-amber-100 whitespace-nowrap"
              >
                Open Patch Review
              </button>
            }
          />
        ) : null}

        {error ? <StateBanner variant="error" title="Validation Error" message={error} /> : null}

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={!effectivePatch || !effectivePatch.applied || running}
            className="inline-flex items-center gap-2 rounded-md bg-blue-700 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-800 disabled:opacity-50 whitespace-nowrap shrink-0"
          >
            {running ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
                <span>Running Container Tests...</span>
              </>
            ) : (
              <>
                <FlaskConical className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Run Isolated Validation</span>
              </>
            )}
          </button>
        </div>
      </form>

      {/* Active Validation Report */}
      {latestReport ? (
        <section className="space-y-4">
          {latestReport.status === "BLOCKED" && !latestReport.container_available ? (
            <StateBanner
              variant="warning"
              title="Validation Blocked: Docker Container Runtime Unavailable"
              message="Docker is not accessible on the backend host. In accordance with RootPatch security policy, tests were not executed on the host machine."
            />
          ) : null}

          <div className="rounded-lg border border-slate-200 bg-white p-5 space-y-5">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-200 pb-4">
              <div>
                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <StatusText label={latestReport.status} />
                  <span aria-hidden="true">·</span>
                  <span className="font-mono">{latestReport.test_framework}</span>
                  <span aria-hidden="true">·</span>
                  <span>{formatTimestamp(latestReport.validated_at)}</span>
                </div>
                <p className="mt-1 font-mono text-xs text-slate-700">
                  Command: {latestReport.test_command.join(" ") || "None"} (source:{" "}
                  {latestReport.command_source})
                </p>
              </div>
              <div className="font-mono text-xs text-slate-600 tabular-nums">
                Exit: {latestReport.exit_code ?? "—"} · {latestReport.duration_ms} ms
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-xs">
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <span className="text-slate-500">Total</span>
                <p className="mt-1 text-lg font-bold text-slate-900 tabular-nums">
                  {latestReport.total_tests}
                </p>
              </div>
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <span className="text-slate-500">Passed</span>
                <p className="mt-1 text-lg font-bold text-emerald-700 tabular-nums">
                  {latestReport.passed_tests}
                </p>
              </div>
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <span className="text-slate-500">Failed</span>
                <p className="mt-1 text-lg font-bold text-red-700 tabular-nums">
                  {latestReport.failed_tests}
                </p>
              </div>
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <span className="text-slate-500">Skipped</span>
                <p className="mt-1 text-lg font-bold text-slate-700 tabular-nums">
                  {latestReport.skipped_tests}
                </p>
              </div>
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <span className="text-slate-500">Errors</span>
                <p className="mt-1 text-lg font-bold text-red-700 tabular-nums">
                  {latestReport.error_tests}
                </p>
              </div>
            </div>

            {latestReport.regression_comparison ? (
              <div className="rounded-md border border-slate-200 bg-slate-50 p-4 space-y-2 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-slate-900">Regression Comparison</span>
                  <StatusText
                    label={
                      latestReport.regression_comparison.regression_detected
                        ? "FAILED"
                        : latestReport.regression_comparison.baseline_available
                          ? "PASSED"
                          : "PARTIAL"
                    }
                  />
                </div>
                <p className="text-slate-700">
                  {sanitizeDisplayText(latestReport.regression_comparison.summary)}
                </p>
                {latestReport.regression_comparison.tests_fixed.length > 0 ? (
                  <p className="text-emerald-700 font-mono">
                    Fixed: {latestReport.regression_comparison.tests_fixed.join(", ")}
                  </p>
                ) : null}
                {latestReport.regression_comparison.tests_regressed.length > 0 ? (
                  <p className="text-red-700 font-mono">
                    Regressed: {latestReport.regression_comparison.tests_regressed.join(", ")}
                  </p>
                ) : null}
              </div>
            ) : null}

            {latestReport.execution_spec ? (
              <div className="rounded-md border border-slate-200 bg-white p-4 text-xs space-y-1.5">
                <div className="flex items-center gap-1.5 font-semibold text-slate-900">
                  <Shield className="w-3.5 h-3.5 text-blue-700" aria-hidden="true" />
                  <span>Container Hardening Spec</span>
                </div>
                <p className="font-mono text-slate-600">
                  Image: {sanitizeSingleLine(latestReport.execution_spec.image)} · Network disabled:{" "}
                  {String(latestReport.execution_spec.network_disabled)} · Read-only root:{" "}
                  {String(latestReport.execution_spec.read_only_root)} · Mem:{" "}
                  {latestReport.execution_spec.memory_limit} · CPUs: {latestReport.execution_spec.cpus}{" "}
                  · PIDs: {latestReport.execution_spec.pids_limit}
                </p>
              </div>
            ) : null}

            {latestReport.failure_details.length > 0 ? (
              <div className="space-y-1">
                <p className="text-xs font-semibold text-red-700">Failure Details</p>
                <ul className="list-disc pl-4 text-xs text-red-800 space-y-1">
                  {latestReport.failure_details.map((item, idx) => (
                    <li key={idx}>{sanitizeDisplayText(item)}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {latestReport.limitations.length > 0 ? (
              <div className="space-y-1">
                <p className="text-xs font-semibold text-slate-700">Limitations</p>
                <ul className="list-disc pl-4 text-xs text-slate-600 space-y-1">
                  {latestReport.limitations.map((item, idx) => (
                    <li key={idx}>{sanitizeDisplayText(item)}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div>
                <p className="text-xs font-semibold text-slate-700 mb-1.5">Container stdout</p>
                <pre className="max-h-64 overflow-auto rounded-md border border-slate-200 bg-slate-950 p-3 font-mono text-xs text-slate-100 whitespace-pre-wrap">
                  {sanitizeDisplayText(latestReport.stdout, "(no stdout)")}
                </pre>
              </div>
              <div>
                <p className="text-xs font-semibold text-slate-700 mb-1.5">Container stderr</p>
                <pre className="max-h-64 overflow-auto rounded-md border border-slate-200 bg-slate-950 p-3 font-mono text-xs text-slate-100 whitespace-pre-wrap">
                  {sanitizeDisplayText(latestReport.stderr, "(no stderr)")}
                </pre>
              </div>
            </div>
          </div>
        </section>
      ) : null}

      {patchHistory.length > 0 ? (
        <section className="rounded-lg border border-slate-200 bg-white overflow-hidden">
          <div className="border-b border-slate-200 px-5 py-3">
            <h3 className="text-sm font-semibold text-slate-900">
              Validation Runs for Selected Patch ({patchHistory.length})
            </h3>
          </div>
          <div className="divide-y divide-slate-200">
            {patchHistory.map((item) => (
              <button
                key={item.validation_id}
                type="button"
                onClick={() => setLatestReport(item)}
                className="flex w-full items-center justify-between gap-4 px-5 py-3 text-left text-xs hover:bg-slate-50"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <StatusText label={item.status} />
                  <span className="font-mono text-slate-600">
                    {item.passed_tests}/{item.total_tests} passed
                  </span>
                </div>
                <span className="text-slate-500 shrink-0">
                  {formatTimestamp(item.validated_at)}
                </span>
              </button>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
