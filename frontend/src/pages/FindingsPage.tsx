import { Bug, Loader2, Search, Sparkles, Wrench } from "lucide-react";
import { useMemo, useState } from "react";
import { EmptyState, StateBanner } from "../components/StateBanner";
import { StatusText } from "../components/StatusText";
import { ApiError, RootPatchApiClient } from "../services/apiClient";
import type {
  AnalysisReportResponse,
  FindingRecord,
  PatchBatchResponse,
  ProjectMetadata,
  RootCauseAnalysisItem,
  ScanResponse,
} from "../types/api";
import { formatTimestamp, sanitizeDisplayText, sanitizeSingleLine } from "../utils/sanitize";

interface FindingsPageProps {
  client: RootPatchApiClient;
  project: ProjectMetadata | null;
  scan: ScanResponse | null;
  analysis: AnalysisReportResponse | null;
  onScanComplete: (scan: ScanResponse) => void;
  onAnalysisComplete: (analysis: AnalysisReportResponse) => void;
  onPatchesGenerated: (batch: PatchBatchResponse) => void;
  onGoToUpload: () => void;
  onGoToPatches: () => void;
}

export function FindingsPage({
  client,
  project,
  scan,
  analysis,
  onScanComplete,
  onAnalysisComplete,
  onPatchesGenerated,
  onGoToUpload,
  onGoToPatches,
}: FindingsPageProps) {
  const [runningScan, setRunningScan] = useState(false);
  const [runningAnalysis, setRunningAnalysis] = useState(false);
  const [generatingForFindingId, setGeneratingForFindingId] = useState<string | null>(null);
  const [generatingBatch, setGeneratingBatch] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  const [severityFilter, setSeverityFilter] = useState<string>("ALL");
  const [toolFilter, setToolFilter] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null);

  const analysisByFindingId = useMemo(() => {
    const map = new Map<string, RootCauseAnalysisItem>();
    if (analysis) {
      for (const item of analysis.analyses) {
        map.set(item.finding_id, item);
      }
    }
    return map;
  }, [analysis]);

  const filteredFindings = useMemo(() => {
    if (!scan) return [];
    const q = searchQuery.trim().toLowerCase();
    return scan.findings.filter((f) => {
      if (severityFilter !== "ALL" && f.severity !== severityFilter) return false;
      if (toolFilter !== "ALL" && f.tool !== toolFilter) return false;
      if (q) {
        const hay = `${f.file_path} ${f.title} ${f.rule_id} ${f.category}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [scan, severityFilter, toolFilter, searchQuery]);

  if (!project) {
    return (
      <EmptyState
        title="No Project Selected"
        description="Upload or select a project before running static analysis or AI root-cause investigation."
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

  const activeFinding: FindingRecord | null =
    filteredFindings.find((f) => f.id === selectedFindingId) ?? filteredFindings[0] ?? null;
  const activeAnalysis = activeFinding ? analysisByFindingId.get(activeFinding.id) ?? null : null;

  const handleRunScan = async () => {
    setRunningScan(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      const result = await client.runScan(project.project_id);
      onScanComplete(result);
      setActionSuccess(
        `Static scan completed: ${result.total_findings} findings across ${result.files_scanned} files.`
      );
    } catch (err) {
      setActionError(err instanceof ApiError ? err.detail : "Static scan request failed.");
    } finally {
      setRunningScan(false);
    }
  };

  const handleRunAnalysis = async () => {
    setRunningAnalysis(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      const result = await client.runAnalysis(project.project_id);
      onAnalysisComplete(result);
      setActionSuccess(
        `Root-cause analysis ${result.status}: ${result.analyzed_count} findings analyzed via ${sanitizeSingleLine(result.provider)}.`
      );
    } catch (err) {
      setActionError(err instanceof ApiError ? err.detail : "Root-cause analysis failed.");
    } finally {
      setRunningAnalysis(false);
    }
  };

  const handleGeneratePatches = async (findingId?: string) => {
    setActionError(null);
    setActionSuccess(null);
    if (findingId) {
      setGeneratingForFindingId(findingId);
    } else {
      setGeneratingBatch(true);
    }
    try {
      const matchedAnalysis = findingId ? analysisByFindingId.get(findingId) : undefined;
      const batch = await client.generatePatches(
        project.project_id,
        findingId
          ? { finding_id: findingId, analysis_id: matchedAnalysis?.analysis_id }
          : undefined
      );
      onPatchesGenerated(batch);
      setActionSuccess(
        `Generated ${batch.generated_count} validated patch(es)${
          batch.rejected_count > 0 ? ` (${batch.rejected_count} rejected during validation)` : ""
        }.`
      );
    } catch (err) {
      setActionError(err instanceof ApiError ? err.detail : "Patch generation failed.");
    } finally {
      setGeneratingForFindingId(null);
      setGeneratingBatch(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Pipeline control header */}
      <section className="rounded-lg border border-slate-200 bg-white p-5 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div className="space-y-1">
          <h2 className="text-base font-semibold text-slate-900">
            Static Detection & AI Root-Cause Pipeline
          </h2>
          <p className="text-xs text-slate-500">
            1. Run Python AST, Ruff, and Bandit scanners · 2. Explain root causes with bounded
            workspace context · 3. Generate validated unified diffs
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <button
            type="button"
            onClick={handleRunScan}
            disabled={runningScan}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-700 px-3.5 py-2 text-xs font-semibold text-white hover:bg-blue-800 disabled:opacity-50 whitespace-nowrap shrink-0"
          >
            {runningScan ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <Bug className="w-3.5 h-3.5" aria-hidden="true" />
            )}
            <span>{scan ? "Re-run Static Scan" : "Run Static Scan"}</span>
          </button>

          <button
            type="button"
            onClick={handleRunAnalysis}
            disabled={!scan || runningAnalysis}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3.5 py-2 text-xs font-semibold text-slate-800 hover:bg-slate-50 disabled:opacity-50 whitespace-nowrap shrink-0"
          >
            {runningAnalysis ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <Sparkles className="w-3.5 h-3.5 text-blue-700" aria-hidden="true" />
            )}
            <span>{analysis ? "Re-run Root-Cause Analysis" : "Analyze Root Causes"}</span>
          </button>

          <button
            type="button"
            onClick={() => handleGeneratePatches()}
            disabled={!scan || !analysis || generatingBatch}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3.5 py-2 text-xs font-semibold text-slate-800 hover:bg-slate-50 disabled:opacity-50 whitespace-nowrap shrink-0"
          >
            {generatingBatch ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <Wrench className="w-3.5 h-3.5 text-blue-700" aria-hidden="true" />
            )}
            <span>Generate All Patches</span>
          </button>
        </div>
      </section>

      {actionError ? <StateBanner variant="error" title="Pipeline Error" message={actionError} /> : null}
      {actionSuccess ? (
        <StateBanner
          variant="success"
          title="Pipeline Updated"
          message={actionSuccess}
          action={
            <button
              type="button"
              onClick={onGoToPatches}
              className="rounded-md bg-emerald-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-800 whitespace-nowrap"
            >
              Open Patch Review
            </button>
          }
        />
      ) : null}

      {!scan ? (
        <EmptyState
          title="Static Scan Not Yet Executed"
          description="Click Run Static Scan to inspect Python files with AST, Ruff, and Bandit."
        />
      ) : (
        <>
          {/* Scanner breakdown */}
          <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {Object.entries(scan.scanner_details).map(([toolName, details]) => (
              <div
                key={toolName}
                className="rounded-lg border border-slate-200 bg-white p-4 flex items-center justify-between gap-3"
              >
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {sanitizeSingleLine(toolName)}
                  </p>
                  <p className="mt-1 text-lg font-bold text-slate-900 tabular-nums">
                    {details.findings_count} findings
                  </p>
                  <p className="text-xs text-slate-500 tabular-nums">{details.duration_ms} ms</p>
                </div>
                <StatusText label={details.status} />
              </div>
            ))}
          </section>

          {scan.limitations.length > 0 ? (
            <StateBanner
              variant="info"
              title={`Scan Completed (${formatTimestamp(scan.scanned_at)})`}
              message={scan.limitations.map((l) => sanitizeSingleLine(l)).join(" · ")}
            />
          ) : null}

          {/* Shared root cause groups if any */}
          {analysis && analysis.shared_root_cause_groups.length > 0 ? (
            <section className="rounded-lg border border-slate-200 bg-white p-5 space-y-3">
              <h3 className="text-sm font-semibold text-slate-900">Shared Root-Cause Groups</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {analysis.shared_root_cause_groups.map((group) => (
                  <div
                    key={group.group_id}
                    className="rounded-md border border-slate-200 bg-slate-50 p-3.5 text-xs space-y-1"
                  >
                    <p className="font-semibold text-slate-900">
                      {sanitizeSingleLine(group.shared_cause)}
                    </p>
                    <p className="text-slate-600">{sanitizeDisplayText(group.explanation)}</p>
                    <p className="font-mono text-slate-500">
                      Findings: {group.finding_ids.join(", ")}
                    </p>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {/* Filter bar */}
          <div className="flex flex-col sm:flex-row gap-3 items-stretch sm:items-center justify-between">
            <div className="relative flex-1 max-w-md">
              <Search
                className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2"
                aria-hidden="true"
              />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Filter by file path, rule ID, or title..."
                aria-label="Filter findings"
                className="w-full rounded-md border border-slate-300 bg-white pl-9 pr-3 py-2 text-xs text-slate-900 focus:border-blue-600 focus:outline-none"
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <select
                aria-label="Filter by severity"
                value={severityFilter}
                onChange={(e) => setSeverityFilter(e.target.value)}
                className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs text-slate-800 focus:border-blue-600 focus:outline-none"
              >
                <option value="ALL">All Severities</option>
                <option value="CRITICAL">CRITICAL</option>
                <option value="HIGH">HIGH</option>
                <option value="MEDIUM">MEDIUM</option>
                <option value="LOW">LOW</option>
                <option value="INFO">INFO</option>
              </select>
              <select
                aria-label="Filter by scanner tool"
                value={toolFilter}
                onChange={(e) => setToolFilter(e.target.value)}
                className="rounded-md border border-slate-300 bg-white px-3 py-2 text-xs text-slate-800 focus:border-blue-600 focus:outline-none"
              >
                <option value="ALL">All Tools</option>
                <option value="ast">AST</option>
                <option value="ruff">Ruff</option>
                <option value="bandit">Bandit</option>
              </select>
            </div>
          </div>

          {/* Master-detail findings + root cause inspector */}
          {filteredFindings.length === 0 ? (
            <EmptyState
              title="No Findings Match Filter"
              description="Adjust your severity, tool, or search filter, or celebrate if total findings is zero."
            />
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
              <div className="lg:col-span-5 rounded-lg border border-slate-200 bg-white divide-y divide-slate-200 overflow-hidden">
                {filteredFindings.map((finding) => {
                  const selected = activeFinding?.id === finding.id;
                  const hasAnalysis = analysisByFindingId.has(finding.id);
                  return (
                    <button
                      key={finding.id}
                      type="button"
                      onClick={() => setSelectedFindingId(finding.id)}
                      className={`w-full text-left px-4 py-3.5 transition-colors ${
                        selected ? "bg-blue-50" : "hover:bg-slate-50"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <StatusText label={finding.severity} />
                        <span className="font-mono text-[11px] text-slate-500">
                          {finding.tool} · {sanitizeSingleLine(finding.rule_id)}
                        </span>
                      </div>
                      <p className="mt-1 text-sm font-semibold text-slate-900 line-clamp-2">
                        {sanitizeSingleLine(finding.title)}
                      </p>
                      <div className="mt-1 flex items-center justify-between gap-2 text-xs text-slate-500">
                        <span className="font-mono truncate">
                          {sanitizeSingleLine(finding.file_path)}:{finding.line_number}
                        </span>
                        {hasAnalysis ? (
                          <span className="text-blue-700 font-medium whitespace-nowrap shrink-0">
                            Analyzed
                          </span>
                        ) : null}
                      </div>
                    </button>
                  );
                })}
              </div>

              <div className="lg:col-span-7 space-y-4">
                {activeFinding ? (
                  <>
                    <section className="rounded-lg border border-slate-200 bg-white p-5 space-y-4">
                      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                            <StatusText label={activeFinding.severity} />
                            <span aria-hidden="true">·</span>
                            <span>Confidence: {activeFinding.confidence}</span>
                            <span aria-hidden="true">·</span>
                            <span className="font-mono">{sanitizeSingleLine(activeFinding.rule_id)}</span>
                          </div>
                          <h3 className="mt-1.5 text-base font-semibold text-slate-900">
                            {sanitizeSingleLine(activeFinding.title)}
                          </h3>
                          <p className="mt-0.5 font-mono text-xs text-slate-600 tabular-nums">
                            {sanitizeSingleLine(activeFinding.file_path)} · Line{" "}
                            {activeFinding.line_number}
                            {activeFinding.column ? `:${activeFinding.column}` : ""}
                          </p>
                        </div>

                        <button
                          type="button"
                          onClick={() => handleGeneratePatches(activeFinding.id)}
                          disabled={!analysis || generatingForFindingId === activeFinding.id}
                          className="inline-flex items-center gap-1.5 rounded-md bg-blue-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-800 disabled:opacity-50 whitespace-nowrap shrink-0"
                        >
                          {generatingForFindingId === activeFinding.id ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
                          ) : (
                            <Wrench className="w-3.5 h-3.5" aria-hidden="true" />
                          )}
                          <span>Generate Patch</span>
                        </button>
                      </div>

                      <p className="text-sm text-slate-700">
                        {sanitizeDisplayText(activeFinding.description)}
                      </p>

                      {activeFinding.evidence ? (
                        <div>
                          <p className="text-xs font-semibold text-slate-700 mb-1">
                            Code Evidence
                          </p>
                          <pre className="rounded-md border border-slate-200 bg-slate-950 p-3 font-mono text-xs text-slate-100 overflow-x-auto whitespace-pre">
                            {sanitizeDisplayText(activeFinding.evidence)}
                          </pre>
                        </div>
                      ) : null}

                      {activeFinding.suggested_fix ? (
                        <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
                          <span className="font-semibold text-slate-900">Scanner Hint: </span>
                          {sanitizeDisplayText(activeFinding.suggested_fix)}
                        </div>
                      ) : null}
                    </section>

                    <section className="rounded-lg border border-slate-200 bg-white p-5 space-y-3">
                      <div className="flex items-center justify-between gap-2">
                        <h4 className="text-sm font-semibold text-slate-900">
                          AI Root-Cause Analysis
                        </h4>
                        {activeAnalysis ? (
                          <StatusText label={activeAnalysis.analysis_status} />
                        ) : null}
                      </div>

                      {!activeAnalysis ? (
                        <p className="text-xs text-slate-500">
                          {analysis
                            ? "No root-cause analysis record matched this finding."
                            : "Run Analyze Root Causes above to generate an evidence-based explanation."}
                        </p>
                      ) : (
                        <div className="space-y-3 text-xs">
                          <div>
                            <p className="font-semibold text-slate-700">Root Cause</p>
                            <p className="mt-0.5 text-sm font-medium text-slate-900">
                              {sanitizeDisplayText(activeAnalysis.root_cause)}
                            </p>
                          </div>
                          <div>
                            <p className="font-semibold text-slate-700">Technical Explanation</p>
                            <p className="mt-0.5 text-slate-700 leading-relaxed">
                              {sanitizeDisplayText(activeAnalysis.technical_explanation)}
                            </p>
                          </div>
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                            <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                              <p className="font-semibold text-slate-700">Affected Component</p>
                              <p className="mt-1 font-mono text-slate-900">
                                {sanitizeSingleLine(activeAnalysis.affected_component)}
                              </p>
                            </div>
                            <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                              <p className="font-semibold text-slate-700">Confidence</p>
                              <p className="mt-1 text-slate-900">
                                {activeAnalysis.confidence} —{" "}
                                {sanitizeSingleLine(activeAnalysis.confidence_reason)}
                              </p>
                            </div>
                          </div>
                          <div>
                            <p className="font-semibold text-slate-700">Impact</p>
                            <p className="mt-0.5 text-slate-700">
                              {sanitizeDisplayText(activeAnalysis.impact)}
                            </p>
                          </div>
                          <div>
                            <p className="font-semibold text-slate-700">Recommended Fix</p>
                            <p className="mt-0.5 text-slate-700">
                              {sanitizeDisplayText(activeAnalysis.recommended_fix)}
                            </p>
                          </div>
                          {activeAnalysis.evidence.length > 0 ? (
                            <div>
                              <p className="font-semibold text-slate-700">Supporting Evidence</p>
                              <ul className="mt-1 list-disc pl-4 space-y-1 text-slate-700">
                                {activeAnalysis.evidence.map((ev, i) => (
                                  <li key={i}>{sanitizeDisplayText(ev)}</li>
                                ))}
                              </ul>
                            </div>
                          ) : null}
                        </div>
                      )}
                    </section>
                  </>
                ) : null}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
