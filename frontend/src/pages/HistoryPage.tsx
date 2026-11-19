import { useState } from "react";
import { EmptyState, LoadingState } from "../components/StateBanner";
import { StatusText } from "../components/StatusText";
import type {
  PatchApplicationHistoryResponse,
  ProjectMetadata,
  ValidationHistoryListResponse,
  ValidationReportResponse,
} from "../types/api";
import { formatTimestamp, sanitizeDisplayText, sanitizeSingleLine } from "../utils/sanitize";

interface HistoryPageProps {
  project: ProjectMetadata | null;
  patchHistory: PatchApplicationHistoryResponse | null;
  validations: ValidationHistoryListResponse | null;
  loading: boolean;
  onGoToUpload: () => void;
}

export function HistoryPage({
  project,
  patchHistory,
  validations,
  loading,
  onGoToUpload,
}: HistoryPageProps) {
  const [selectedValidation, setSelectedValidation] = useState<ValidationReportResponse | null>(
    null
  );

  if (!project) {
    return (
      <EmptyState
        title="No Project Selected"
        description="Upload or open a project workspace to inspect patch application and validation history."
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

  if (loading && !patchHistory && !validations) {
    return <LoadingState label="Loading application and validation audit logs..." />;
  }

  const historyEntries = patchHistory?.history ?? [];
  const validationRuns = validations?.validations ?? [];

  return (
    <div className="space-y-6">
      {/* Patch Application Audit Log */}
      <section className="rounded-lg border border-slate-200 bg-white overflow-hidden">
        <div className="border-b border-slate-200 px-5 py-3.5 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Patch Application History</h2>
            <p className="text-xs text-slate-500 tabular-nums">
              {patchHistory
                ? `${patchHistory.total_events} total · ${patchHistory.applied_count} applied · ${patchHistory.failed_count} failed · ${patchHistory.stale_count} stale`
                : "No patch application events recorded"}
            </p>
          </div>
        </div>

        {historyEntries.length === 0 ? (
          <div className="px-5 py-6 text-xs text-slate-500">
            No patches have been applied to this project yet.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-slate-200 bg-slate-50 text-slate-600">
                <tr>
                  <th className="px-4 py-2.5 font-semibold">Result</th>
                  <th className="px-4 py-2.5 font-semibold">Target File</th>
                  <th className="px-4 py-2.5 font-semibold">Patch ID</th>
                  <th className="px-4 py-2.5 font-semibold">SHA-256 Before / After</th>
                  <th className="px-4 py-2.5 font-semibold">Applied At</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {historyEntries.map((entry) => (
                  <tr key={entry.history_id} className="align-top">
                    <td className="px-4 py-3 whitespace-nowrap">
                      <StatusText label={entry.result.toUpperCase()} />
                    </td>
                    <td className="px-4 py-3 font-mono text-slate-900">
                      <div>{sanitizeSingleLine(entry.file_path)}</div>
                      {entry.backup_path ? (
                        <div className="text-[11px] text-slate-500">
                          Backup: {sanitizeSingleLine(entry.backup_path)}
                        </div>
                      ) : null}
                      {entry.error_message ? (
                        <div className="text-[11px] text-red-700">
                          {sanitizeDisplayText(entry.error_message)}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 font-mono text-slate-600">
                      {entry.patch_id.slice(0, 12)}
                    </td>
                    <td className="px-4 py-3 font-mono text-slate-600">
                      <div>{entry.previous_file_sha256.slice(0, 12)}</div>
                      <div>{entry.new_file_sha256 ? entry.new_file_sha256.slice(0, 12) : "—"}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-600 whitespace-nowrap">
                      {formatTimestamp(entry.applied_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Validation History */}
      <section className="rounded-lg border border-slate-200 bg-white overflow-hidden">
        <div className="border-b border-slate-200 px-5 py-3.5">
          <h2 className="text-sm font-semibold text-slate-900">Container Validation History</h2>
          <p className="text-xs text-slate-500 tabular-nums">
            {validations
              ? `${validations.total_runs} runs · ${validations.passed_count} passed · ${validations.failed_count} failed · ${validations.blocked_count} blocked`
              : "No validation runs recorded"}
          </p>
        </div>

        {validationRuns.length === 0 ? (
          <div className="px-5 py-6 text-xs text-slate-500">
            No isolated validation runs have been recorded for this project yet.
          </div>
        ) : (
          <div className="divide-y divide-slate-200">
            {validationRuns.map((run) => {
              const expanded = selectedValidation?.validation_id === run.validation_id;
              return (
                <div key={run.validation_id} className="px-5 py-3.5 space-y-3">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs">
                    <div className="flex flex-wrap items-center gap-2.5 min-w-0">
                      <StatusText label={run.status} />
                      <span className="font-mono font-semibold text-slate-900 truncate">
                        {sanitizeSingleLine(run.file_path)}
                      </span>
                      <span className="text-slate-500 tabular-nums">
                        {run.passed_tests}/{run.total_tests} passed · {run.duration_ms} ms
                      </span>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <span className="text-slate-500">{formatTimestamp(run.validated_at)}</span>
                      <button
                        type="button"
                        onClick={() => setSelectedValidation(expanded ? null : run)}
                        className="font-semibold text-blue-700 hover:text-blue-800 whitespace-nowrap"
                      >
                        {expanded ? "Hide Logs" : "Inspect Logs"}
                      </button>
                    </div>
                  </div>

                  {expanded ? (
                    <div className="space-y-3 border-t border-slate-100 pt-3 text-xs">
                      <p className="font-mono text-slate-600">
                        Command: {run.test_command.join(" ") || "None"} · Framework:{" "}
                        {run.test_framework}
                      </p>
                      {run.regression_comparison ? (
                        <p className="text-slate-700">
                          <span className="font-semibold">Regression Summary: </span>
                          {sanitizeDisplayText(run.regression_comparison.summary)}
                        </p>
                      ) : null}
                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                        <pre className="max-h-48 overflow-auto rounded-md border border-slate-200 bg-slate-950 p-3 font-mono text-xs text-slate-100 whitespace-pre-wrap">
                          {sanitizeDisplayText(run.stdout, "(no stdout)")}
                        </pre>
                        <pre className="max-h-48 overflow-auto rounded-md border border-slate-200 bg-slate-950 p-3 font-mono text-xs text-slate-100 whitespace-pre-wrap">
                          {sanitizeDisplayText(run.stderr, "(no stderr)")}
                        </pre>
                      </div>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
