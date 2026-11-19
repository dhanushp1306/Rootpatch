import { Check, CheckCircle2, FlaskConical, Loader2, Play, X } from "lucide-react";
import { useEffect, useState } from "react";
import { CodeComparisonView, UnifiedDiffView } from "../components/DiffViewer";
import { EmptyState, LoadingState, StateBanner } from "../components/StateBanner";
import { StatusText } from "../components/StatusText";
import { ApiError, RootPatchApiClient } from "../services/apiClient";
import type {
  AnalysisReportResponse,
  PatchBatchResponse,
  PatchRecord,
  PatchReviewResponse,
  ProjectMetadata,
} from "../types/api";
import { formatTimestamp, sanitizeDisplayText, sanitizeSingleLine } from "../utils/sanitize";

interface PatchReviewPageProps {
  client: RootPatchApiClient;
  project: ProjectMetadata | null;
  patches: PatchBatchResponse | null;
  analysis?: AnalysisReportResponse | null;
  onPatchesGenerated?: (batch: PatchBatchResponse) => void;
  onPatchesUpdated: () => Promise<void> | void;
  onValidatePatch: (patchId: string) => void;
  onGoToFindings: () => void;
  onGoToUpload: () => void;
}

export function PatchReviewPage({
  client,
  project,
  patches,
  analysis = null,
  onPatchesGenerated,
  onPatchesUpdated,
  onValidatePatch,
  onGoToFindings,
  onGoToUpload,
}: PatchReviewPageProps) {
  const [selectedPatchId, setSelectedPatchId] = useState<string | null>(null);
  const [review, setReview] = useState<PatchReviewResponse | null>(null);
  const [loadingReview, setLoadingReview] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const [actionBusy, setActionBusy] = useState<"approve" | "reject" | "apply" | null>(null);
  const [actionBanner, setActionBanner] = useState<{
    variant: "success" | "error";
    title: string;
    message: string;
  } | null>(null);

  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  const patchList: PatchRecord[] = patches?.patches ?? [];
  const effectivePatchId =
    patchList.find((p) => p.patch_id === selectedPatchId)?.patch_id ??
    patchList[0]?.patch_id ??
    null;

  const projectKey = project?.project_id ?? null;

  useEffect(() => {
    setActionBanner(null);
    setGenerateError(null);
    setReviewNote("");
    setSelectedPatchId(null);
  }, [projectKey]);

  useEffect(() => {
    if (!projectKey || !effectivePatchId) {
      setReview(null);
      return;
    }

    let cancelled = false;
    setLoadingReview(true);
    setReviewError(null);
    client
      .getPatchReview(projectKey, effectivePatchId)
      .then((res) => {
        if (!cancelled) {
          setReview(res);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setReviewError(
            err instanceof ApiError ? err.detail : "Failed to load patch review details."
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingReview(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [client, projectKey, effectivePatchId]);

  if (!project) {
    return (
      <EmptyState
        title="No Project Selected"
        description="Upload or load a project workspace first to inspect and approve patches."
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

  if (!patches || patchList.length === 0) {
    const handleGenerate = async () => {
      setGenerating(true);
      setGenerateError(null);
      try {
        const batch = await client.generatePatches(project.project_id);
        if (onPatchesGenerated) {
          onPatchesGenerated(batch);
        } else {
          await onPatchesUpdated();
        }
      } catch (err) {
        setGenerateError(err instanceof ApiError ? err.detail : "Patch generation failed.");
      } finally {
        setGenerating(false);
      }
    };

    return (
      <div className="space-y-4">
        {generateError ? (
          <StateBanner variant="error" title="Patch Generation Failed" message={generateError} />
        ) : null}
        {generating ? <LoadingState label="Generating validated patches..." /> : null}
        {analysis && analysis.analyses.length === 0 ? (
          <EmptyState
            title="No Findings to Patch"
            description="Static scanning and root-cause analysis found zero issues in this project. Patches cannot be generated because there are no diagnosed findings to fix."
            action={
              <button
                type="button"
                onClick={onGoToFindings}
                className="rounded-md bg-blue-700 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-800 whitespace-nowrap"
              >
                Open Bugs & Root Cause
              </button>
            }
          />
        ) : (
          <EmptyState
            title="No Patches Generated Yet"
            description={
              analysis && analysis.analyses.length > 0
                ? "Root-cause analysis is available for this project. Generate patches to review them here."
                : "Run static bug detection, generate AI root-cause analyses, and generate patches before reviewing changes here."
            }
            action={
              analysis && analysis.analyses.length > 0 ? (
                <button
                  type="button"
                  onClick={() => {
                    void handleGenerate();
                  }}
                  disabled={generating}
                  className="rounded-md bg-blue-700 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-800 disabled:opacity-50 whitespace-nowrap"
                >
                  {generating ? "Generating..." : "Generate Patches"}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={onGoToFindings}
                  className="rounded-md bg-blue-700 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-800 whitespace-nowrap"
                >
                  Open Bugs & Root Cause
                </button>
              )
            }
          />
        )}
      </div>
    );
  }

  const reloadReview = async (patchId: string) => {
    const updated = await client.getPatchReview(project.project_id, patchId);
    setReview(updated);
    await onPatchesUpdated();
  };

  const handleApprove = async () => {
    if (!review) return;
    setActionBusy("approve");
    setActionBanner(null);
    try {
      await client.approvePatch(
        project.project_id,
        review.patch_id,
        reviewNote.trim() ? { comment: reviewNote.trim() } : undefined
      );
      await reloadReview(review.patch_id);
      setActionBanner({
        variant: "success",
        title: "Patch Approved",
        message: "Patch is marked approved. Click Apply Patch when ready to write changes to workspace.",
      });
    } catch (err) {
      setActionBanner({
        variant: "error",
        title: "Approval Failed",
        message: err instanceof ApiError ? err.detail : "Unable to approve patch.",
      });
    } finally {
      setActionBusy(null);
    }
  };

  const handleReject = async () => {
    if (!review) return;
    setActionBusy("reject");
    setActionBanner(null);
    try {
      await client.rejectPatch(
        project.project_id,
        review.patch_id,
        reviewNote.trim() ? { comment: reviewNote.trim() } : undefined
      );
      await reloadReview(review.patch_id);
      setActionBanner({
        variant: "success",
        title: "Patch Rejected",
        message: "Patch has been rejected and will remain unapplied.",
      });
    } catch (err) {
      setActionBanner({
        variant: "error",
        title: "Rejection Failed",
        message: err instanceof ApiError ? err.detail : "Unable to reject patch.",
      });
    } finally {
      setActionBusy(null);
    }
  };

  const handleApply = async () => {
    if (!review) return;
    setActionBusy("apply");
    setActionBanner(null);
    try {
      const applied = await client.applyPatch(project.project_id, review.patch_id);
      await reloadReview(review.patch_id);
      setActionBanner({
        variant: "success",
        title: "Patch Applied Safely",
        message: `${sanitizeSingleLine(applied.message)} Backup saved at ${sanitizeSingleLine(
          applied.application_record.backup_path || "workspace backups/"
        )}.`,
      });
    } catch (err) {
      setActionBanner({
        variant: "error",
        title: "Patch Application Failed",
        message: err instanceof ApiError ? err.detail : "Unable to apply patch.",
      });
    } finally {
      setActionBusy(null);
    }
  };

  return (
    <div className="space-y-6">
      {patches.rejected_patches.length > 0 ? (
        <StateBanner
          variant="warning"
          title={`${patches.rejected_patches.length} Generated Diff(s) Rejected by Diff Validator`}
          message={patches.rejected_patches
            .map((r) => `${sanitizeSingleLine(r.file_path)}: ${sanitizeSingleLine(r.reason)}`)
            .join(" · ")}
        />
      ) : null}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Patch queue */}
        <div className="lg:col-span-4 rounded-lg border border-slate-200 bg-white divide-y divide-slate-200 overflow-hidden">
          <div className="px-4 py-3 bg-slate-50 border-b border-slate-200">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-600">
              Patch Queue ({patchList.length})
            </h2>
          </div>
          {patchList.map((patch) => {
            const active = patch.patch_id === effectivePatchId;
            return (
              <button
                key={patch.patch_id}
                type="button"
                onClick={() => {
                  setSelectedPatchId(patch.patch_id);
                  setActionBanner(null);
                }}
                className={`w-full text-left px-4 py-3.5 transition-colors ${
                  active ? "bg-blue-50" : "hover:bg-slate-50"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <StatusText label={patch.status} />
                  <span className="font-mono text-[11px] text-slate-500">
                    +{patch.validation.lines_added} / -{patch.validation.lines_removed}
                  </span>
                </div>
                <p className="mt-1 text-sm font-semibold text-slate-900 truncate">
                  {sanitizeSingleLine(patch.summary)}
                </p>
                <p className="mt-0.5 font-mono text-xs text-slate-500 truncate">
                  {sanitizeSingleLine(patch.file_path)}:{patch.line_number}
                </p>
              </button>
            );
          })}
        </div>

        {/* Selected Patch Review Detail */}
        <div className="lg:col-span-8 space-y-4">
          {loadingReview && !review ? <LoadingState label="Loading live patch review..." /> : null}
          {reviewError ? (
            <StateBanner variant="error" title="Review Load Error" message={reviewError} />
          ) : null}
          {actionBanner ? (
            <StateBanner
              variant={actionBanner.variant}
              title={actionBanner.title}
              message={actionBanner.message}
            />
          ) : null}

          {review ? (
            <>
              {review.is_stale ? (
                <StateBanner
                  variant="warning"
                  title="Target File Changed (Stale Patch)"
                  message={
                    sanitizeSingleLine(review.stale_reason) ||
                    "The workspace file no longer matches the original SHA-256 hash."
                  }
                />
              ) : null}

              <section className="rounded-lg border border-slate-200 bg-white p-5 space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <StatusText label={review.status} />
                      <span aria-hidden="true">·</span>
                      <span>Approval: {review.approval_status}</span>
                      <span aria-hidden="true">·</span>
                      <span>Application: {review.application_status}</span>
                    </div>
                    <h3 className="text-base font-semibold text-slate-900">
                      {sanitizeSingleLine(review.summary)}
                    </h3>
                    <p className="font-mono text-xs text-slate-600">
                      {sanitizeSingleLine(review.file_path)} · Line {review.line_number} ·{" "}
                      {sanitizeSingleLine(review.rule_id)}
                    </p>
                  </div>

                  {review.applied ? (
                    <button
                      type="button"
                      onClick={() => onValidatePatch(review.patch_id)}
                      className="inline-flex items-center gap-1.5 rounded-md bg-emerald-700 px-3.5 py-2 text-xs font-semibold text-white hover:bg-emerald-800 whitespace-nowrap shrink-0"
                    >
                      <FlaskConical className="w-3.5 h-3.5" aria-hidden="true" />
                      <span>Validate Applied Patch</span>
                    </button>
                  ) : null}
                </div>

                {review.finding_title || review.root_cause ? (
                  <div className="rounded-md border border-slate-200 bg-slate-50 p-3.5 text-xs space-y-1">
                    {review.finding_title ? (
                      <p className="font-semibold text-slate-900">
                        Finding: {sanitizeSingleLine(review.finding_title)}
                        {review.finding_severity ? ` (${review.finding_severity})` : ""}
                      </p>
                    ) : null}
                    {review.root_cause ? (
                      <p className="text-slate-700">
                        <span className="font-semibold">Root Cause: </span>
                        {sanitizeDisplayText(review.root_cause)}
                      </p>
                    ) : null}
                  </div>
                ) : null}

                <p className="text-sm text-slate-700 leading-relaxed">
                  {sanitizeDisplayText(review.explanation)}
                </p>

                <div className="text-xs text-slate-500 space-y-1">
                  <p>
                    <span className="font-semibold text-slate-700">Diff Validation Checks: </span>
                    {review.validation.checks_passed.join(", ") || "None"}
                  </p>
                  <p className="font-mono">
                    Original SHA-256: {review.validation.original_file_sha256.slice(0, 16)}...
                    {review.reviewed_at ? ` · Reviewed ${formatTimestamp(review.reviewed_at)}` : ""}
                    {review.applied_at ? ` · Applied ${formatTimestamp(review.applied_at)}` : ""}
                  </p>
                  {review.review_note ? (
                    <p>
                      <span className="font-semibold text-slate-700">Review Note: </span>
                      {sanitizeDisplayText(review.review_note)}
                    </p>
                  ) : null}
                  {review.application_error ? (
                    <p className="text-red-700">
                      Application Error: {sanitizeDisplayText(review.application_error)}
                    </p>
                  ) : null}
                </div>

                {/* Backend-controlled review actions */}
                <div className="border-t border-slate-200 pt-4 space-y-3">
                  <div>
                    <label
                      htmlFor="patch-review-note"
                      className="block text-xs font-medium text-slate-700"
                    >
                      Optional Review Comment
                    </label>
                    <input
                      id="patch-review-note"
                      type="text"
                      value={reviewNote}
                      onChange={(e) => setReviewNote(e.target.value)}
                      placeholder="Add rationale for approval or rejection..."
                      className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-900 focus:border-blue-600 focus:outline-none"
                    />
                  </div>

                  <div className="flex flex-wrap items-center gap-2.5">
                    <button
                      type="button"
                      onClick={handleApprove}
                      disabled={!review.can_approve || actionBusy !== null}
                      className="inline-flex items-center gap-1.5 rounded-md bg-blue-700 px-3.5 py-2 text-xs font-semibold text-white hover:bg-blue-800 disabled:opacity-45 whitespace-nowrap shrink-0"
                    >
                      {actionBusy === "approve" ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
                      ) : (
                        <Check className="w-3.5 h-3.5" aria-hidden="true" />
                      )}
                      <span>Approve Patch</span>
                    </button>

                    <button
                      type="button"
                      onClick={handleReject}
                      disabled={!review.can_reject || actionBusy !== null}
                      className="inline-flex items-center gap-1.5 rounded-md border border-red-300 bg-white px-3.5 py-2 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:opacity-45 whitespace-nowrap shrink-0"
                    >
                      {actionBusy === "reject" ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
                      ) : (
                        <X className="w-3.5 h-3.5" aria-hidden="true" />
                      )}
                      <span>Reject Patch</span>
                    </button>

                    <button
                      type="button"
                      onClick={handleApply}
                      disabled={!review.can_apply || actionBusy !== null}
                      className="inline-flex items-center gap-1.5 rounded-md bg-emerald-700 px-3.5 py-2 text-xs font-semibold text-white hover:bg-emerald-800 disabled:opacity-45 whitespace-nowrap shrink-0"
                    >
                      {actionBusy === "apply" ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
                      ) : (
                        <Play className="w-3.5 h-3.5" aria-hidden="true" />
                      )}
                      <span>Apply Patch</span>
                    </button>

                    {review.applied ? (
                      <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700">
                        <CheckCircle2 className="w-4 h-4" aria-hidden="true" />
                        <span>Applied to workspace</span>
                      </span>
                    ) : null}
                  </div>
                </div>
              </section>

              <section className="space-y-2">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                  Unified Diff
                </h4>
                <UnifiedDiffView diff={review.unified_diff} />
              </section>

              <section className="space-y-2">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                  Before / After Comparison
                </h4>
                <CodeComparisonView
                  originalCode={review.original_code ?? review.original_snippet}
                  proposedCode={review.proposed_code ?? review.proposed_snippet}
                />
              </section>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
