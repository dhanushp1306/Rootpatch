import { ArrowRight, Bug, FileCheck2, FlaskConical, FolderGit2, Sparkles, Upload, Zap } from "lucide-react";
import type { NavSection } from "../components/AppShell";
import { EmptyState, StateBanner } from "../components/StateBanner";
import { StatusText } from "../components/StatusText";
import type { KnownProjectSummary } from "../hooks/useProjectRegistry";
import type { WorkspaceState } from "../hooks/useProjectWorkspace";
import { formatBytes, formatTimestamp, sanitizeSingleLine } from "../utils/sanitize";

interface DashboardPageProps {
  workspace: WorkspaceState;
  knownProjects: KnownProjectSummary[];
  onSelectProject: (projectId: string) => void;
  onNavigate: (section: NavSection) => void;
}

const TECH_STACK = [
  { name: "React", color: "bg-[#CDECF0] text-cyan-700 border-cyan-200", icon: "⚛" },
  { name: "TypeScript", color: "bg-[#D9E8F8] text-[#6545D5] border-blue-200", icon: "TS" },
  { name: "Vite", color: "bg-[#CFC5F0] text-violet-700 border-violet-200", icon: "⚡" },
  { name: "Tailwind CSS", color: "bg-[#CDEBE1] text-teal-700 border-teal-200", icon: "🎨" },
  { name: "Python", color: "bg-[#F5E4D4] text-amber-700 border-amber-200", icon: "🐍" },
  { name: "FastAPI", color: "bg-[#CDEBE1] text-emerald-700 border-emerald-200", icon: "🚀" },
  { name: "Uvicorn", color: "bg-indigo-100 text-[#6545D5] border-[#C7C0F0]", icon: "⚡", isUvicorn: true },
  { name: "PostgreSQL", color: "bg-[#D9E8F8] text-sky-700 border-sky-200", icon: "🐘" },
  { name: "Supabase", color: "bg-[#CDEBE1] text-green-700 border-green-200", icon: "⚡" },
  { name: "Docker", color: "bg-[#D9E8F8] text-[#6545D5] border-blue-200", icon: "🐳" },
];

export function DashboardPage({
  workspace,
  knownProjects,
  onSelectProject,
  onNavigate,
}: DashboardPageProps) {
  const { project, scan, analysis, patches, patchHistory, validations, health, healthError } =
    workspace;

  if (!project) {
    return (
      <div className="space-y-6">
        {healthError ? (
          <StateBanner
            variant="warning"
            title="Backend API Unreachable"
            message={`${healthError} Start the FastAPI server on port 8000 or set VITE_API_BASE_URL.`}
          />
        ) : null}

        <EmptyState
          title="No Active Project Selected"
          description="Upload a Python or Node.js repository archive (.zip) to inspect structure, detect static bugs, analyze root causes, review patches, and run container-isolated validation."
          action={
            <button
              type="button"
              onClick={() => onNavigate("upload")}
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-[#6545D5] to-[#8B5CF6] px-5 py-2.5 text-sm font-semibold text-white hover:from-[#7555E5] hover:to-[#9B6CF6] shadow-lg shadow-[#6545D5]/25 whitespace-nowrap shrink-0 transition-all"
            >
              <Upload className="w-4 h-4" aria-hidden="true" />
              <span>Upload Project Archive</span>
            </button>
          }
        />

        {knownProjects.length > 0 ? (
          <section className="rounded-xl border border-[#D4CFF5] bg-[#DCD7F2] overflow-hidden shadow-sm">
            <div className="border-b border-[#D4CFF5] px-5 py-3.5 bg-gradient-to-r from-[#EAE7FF] to-[#D9E8F8]">
              <h2 className="text-sm font-semibold text-[#25213B]">Recently Opened Projects</h2>
            </div>
            <div className="divide-y divide-indigo-50">
              {knownProjects.map((item) => (
                <div
                  key={item.project_id}
                  className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-5 py-3.5 hover:bg-[#CFC5F0]/50 transition-colors"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-[#25213B] truncate">
                      {sanitizeSingleLine(item.project_name)}
                    </p>
                    <p className="text-xs text-[#625D78] font-mono">
                      {item.project_id} · Opened {formatTimestamp(item.added_at)}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => onSelectProject(item.project_id)}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-[#C7C0F0] bg-[#DCD7F2] px-3 py-1.5 text-xs font-semibold text-[#6545D5] hover:bg-[#CFC5F0] whitespace-nowrap shrink-0 transition-colors"
                  >
                    <span>Open Workspace</span>
                    <ArrowRight className="w-3.5 h-3.5" aria-hidden="true" />
                  </button>
                </div>
              ))}
            </div>
          </section>
        ) : null}
      </div>
    );
  }

  const inspection = project.inspection;
  const generatedCount = patches?.patches.length ?? 0;
  const approvedCount =
    patches?.patches.filter((p) => p.approval_status === "approved").length ?? 0;
  const appliedCount = patches?.patches.filter((p) => p.applied).length ?? 0;

  const recentActivities: {
    id: string;
    kind: string;
    title: string;
    detail: string;
    status: string;
    timestamp: string;
    targetSection: NavSection;
  }[] = [];

  if (patchHistory) {
    for (const entry of patchHistory.history) {
      recentActivities.push({
        id: `history-${entry.history_id}`,
        kind: "Patch Application",
        title: sanitizeSingleLine(entry.file_path),
        detail: `Patch ${entry.patch_id.slice(0, 8)} · Finding ${entry.finding_id.slice(0, 8)}`,
        status: entry.result.toUpperCase(),
        timestamp: entry.applied_at,
        targetSection: "history",
      });
    }
  }

  if (validations) {
    for (const run of validations.validations) {
      recentActivities.push({
        id: `validation-${run.validation_id}`,
        kind: "Container Validation",
        title: `${sanitizeSingleLine(run.file_path)} (${run.test_framework})`,
        detail: `${run.passed_tests}/${run.total_tests} passed · ${run.duration_ms} ms`,
        status: run.status,
        timestamp: run.validated_at,
        targetSection: "validation",
      });
    }
  }

  recentActivities.sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  );

  return (
    <div className="space-y-6">
      {health ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#D4CFF5] bg-gradient-to-r from-[#EAE7FF] to-[#D9E8F8] px-5 py-3 text-xs text-[#625D78] shadow-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-[#25213B]">{health.app}</span>
            <span aria-hidden="true" className="text-indigo-300">•</span>
            <span className="font-mono text-[#625D78]">v{health.version}</span>
            <span aria-hidden="true" className="text-indigo-300">•</span>
            <span>{sanitizeSingleLine(health.message)}</span>
          </div>
          <StatusText label={health.status} />
        </div>
      ) : healthError ? (
        <StateBanner variant="warning" title="Backend Health Unavailable" message={healthError} />
      ) : null}

      {scan && scan.files_scanned === 0 ? (
        <StateBanner
          variant="warning"
          title="Static Scanner Limitation"
          message={
            scan.limitations.length > 0
              ? scan.limitations.map((l) => sanitizeSingleLine(l)).join(" · ")
              : "No scannable Python source files found. RootPatch static scanners currently analyze Python (.py) files only."
          }
        />
      ) : null}

      {/* Top metric cards */}
      <section className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <div className="rounded-xl border border-[#D4CFF5] bg-[#DCD7F2] p-5 shadow-sm hover:shadow-md transition-shadow">
          <div className="flex items-center justify-between text-xs font-medium text-[#625D78]">
            <span>Inspected Files</span>
            <div className="flex h-7 w-7 items-center justify-center rounded-xl bg-indigo-100">
              <FolderGit2 className="w-4 h-4 text-[#6545D5]" aria-hidden="true" />
            </div>
          </div>
          <p className="mt-2 text-2xl font-bold text-[#25213B] tabular-nums">
            {inspection.total_files}
          </p>
          <p className="mt-1 text-xs text-[#625D78] tabular-nums">
            {inspection.test_file_count} tests · {formatBytes(inspection.total_size_bytes)}
          </p>
        </div>

        <div className="rounded-xl border border-amber-100 bg-[#DCD7F2] p-5 shadow-sm hover:shadow-md transition-shadow">
          <div className="flex items-center justify-between text-xs font-medium text-[#625D78]">
            <span>Static Findings</span>
            <div className="flex h-7 w-7 items-center justify-center rounded-xl bg-[#F5E4D4]">
              <Bug className="w-4 h-4 text-[#C47A20]" aria-hidden="true" />
            </div>
          </div>
          <p className="mt-2 text-2xl font-bold text-[#25213B] tabular-nums">
            {scan ? scan.total_findings : "—"}
          </p>
          <p className="mt-1 text-xs text-[#625D78] tabular-nums">
            {scan
              ? scan.files_scanned === 0
                ? "0 files scanned (No Python files)"
                : scan.total_findings === 0
                ? `Clean (${scan.files_scanned} files scanned)`
                : `${scan.severity_summary.CRITICAL ?? 0} critical · ${scan.severity_summary.HIGH ?? 0} high · ${scan.severity_summary.MEDIUM ?? 0} medium`
              : "Scan not yet run"}
          </p>
        </div>

        <div className="rounded-xl border border-violet-100 bg-[#DCD7F2] p-5 shadow-sm hover:shadow-md transition-shadow">
          <div className="flex items-center justify-between text-xs font-medium text-[#625D78]">
            <span>Root-Cause Analyses</span>
            <div className="flex h-7 w-7 items-center justify-center rounded-xl bg-[#CFC5F0]">
              <Sparkles className="w-4 h-4 text-[#6545D5]" aria-hidden="true" />
            </div>
          </div>
          <p className="mt-2 text-2xl font-bold text-[#25213B] tabular-nums">
            {analysis ? analysis.analyzed_count : "—"}
          </p>
          <p className="mt-1 text-xs text-[#625D78]">
            {analysis
              ? `${sanitizeSingleLine(analysis.provider)} · ${sanitizeSingleLine(analysis.model)}`
              : "Analysis not yet run"}
          </p>
        </div>

        <div className="rounded-xl border border-emerald-100 bg-[#DCD7F2] p-5 shadow-sm hover:shadow-md transition-shadow">
          <div className="flex items-center justify-between text-xs font-medium text-[#625D78]">
            <span>Patches & Validation</span>
            <div className="flex h-7 w-7 items-center justify-center rounded-xl bg-[#CDEBE1]">
              <FileCheck2 className="w-4 h-4 text-[#138A67]" aria-hidden="true" />
            </div>
          </div>
          <p className="mt-2 text-2xl font-bold text-[#25213B] tabular-nums">
            {generatedCount}
          </p>
          <p className="mt-1 text-xs text-[#625D78] tabular-nums">
            {approvedCount} approved · {appliedCount} applied · {validations?.total_runs ?? 0}{" "}
            validated
          </p>
        </div>
      </section>

      {/* Pipeline actions & metadata */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <section className="lg:col-span-2 rounded-xl border border-[#D4CFF5] bg-[#DCD7F2] overflow-hidden shadow-sm">
          <div className="border-b border-[#D4CFF5] px-5 py-3.5 flex items-center justify-between bg-gradient-to-r from-[#EAE7FF]/50 to-[#D9E8F8]/50">
            <h2 className="text-sm font-semibold text-[#25213B]">Recent Pipeline Activity</h2>
            <button
              type="button"
              onClick={() => onNavigate("history")}
              className="text-xs font-semibold text-[#6545D5] hover:text-indigo-800 whitespace-nowrap shrink-0"
            >
              View Full History
            </button>
          </div>
          {recentActivities.length === 0 ? (
            <div className="px-5 py-8 text-sm text-[#625D78]">
              No patch applications or container validations recorded for this project yet. Run a
              static scan, analyze findings, and review patches to begin.
            </div>
          ) : (
            <div className="divide-y divide-indigo-50">
              {recentActivities.slice(0, 8).map((activity) => (
                <div
                  key={activity.id}
                  className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 px-5 py-3.5 hover:bg-[#E2DFF1] transition-colors"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-[#625D78]">
                      <span className="font-semibold text-[#6545D5]">{activity.kind}</span>
                      <span aria-hidden="true" className="text-indigo-300">·</span>
                      <span>{formatTimestamp(activity.timestamp)}</span>
                    </div>
                    <p className="mt-0.5 text-sm font-medium text-[#25213B] truncate font-mono">
                      {activity.title}
                    </p>
                    <p className="text-xs text-[#625D78]">{activity.detail}</p>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <StatusText label={activity.status} />
                    <button
                      type="button"
                      onClick={() => onNavigate(activity.targetSection)}
                      className="text-xs font-semibold text-[#6545D5] hover:text-indigo-800 whitespace-nowrap"
                    >
                      Inspect
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="rounded-xl border border-[#D4CFF5] bg-[#DCD7F2] p-5 space-y-4 shadow-sm">
          <h2 className="text-sm font-semibold text-[#25213B]">Project Summary</h2>
          <dl className="space-y-2.5 text-xs">
            <div className="flex justify-between gap-3">
              <dt className="text-[#625D78]">Archive</dt>
              <dd className="font-mono text-[#25213B] truncate">
                {sanitizeSingleLine(project.original_filename)}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-[#625D78]">Created</dt>
              <dd className="text-[#25213B]">{formatTimestamp(project.created_at)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-[#625D78]">Languages</dt>
              <dd className="text-[#25213B] text-right">
                {inspection.languages.length
                  ? inspection.languages
                      .slice(0, 4)
                      .map((l) => `${sanitizeSingleLine(l.name)} (${l.file_count})`)
                      .join(", ")
                  : "None detected"}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-[#625D78]">Test Directories</dt>
              <dd className="font-mono text-[#25213B] text-right">
                {inspection.test_directories.length
                  ? inspection.test_directories.join(", ")
                  : "None"}
              </dd>
            </div>
          </dl>

          <div className="border-t border-[#D4CFF5] pt-4 space-y-2">
            <p className="text-xs font-semibold text-[#6545D5]">Quick Actions</p>
            <div className="grid grid-cols-1 gap-2">
              <button
                type="button"
                onClick={() => onNavigate("findings")}
                className="flex items-center justify-between rounded-xl border border-[#D4CFF5] px-3 py-2 text-xs font-semibold text-[#25213B] hover:bg-[#CFC5F0] transition-colors"
              >
                <span className="flex items-center gap-2">
                  <Bug className="w-3.5 h-3.5 text-[#C47A20]" aria-hidden="true" />
                  <span>Static Scan & Root Cause</span>
                </span>
                <ArrowRight className="w-3.5 h-3.5 text-[#625D78]" aria-hidden="true" />
              </button>
              <button
                type="button"
                onClick={() => onNavigate("patches")}
                className="flex items-center justify-between rounded-xl border border-[#D4CFF5] px-3 py-2 text-xs font-semibold text-[#25213B] hover:bg-[#CFC5F0] transition-colors"
              >
                <span className="flex items-center gap-2">
                  <FileCheck2 className="w-3.5 h-3.5 text-[#6545D5]" aria-hidden="true" />
                  <span>Review & Apply Patches</span>
                </span>
                <ArrowRight className="w-3.5 h-3.5 text-[#625D78]" aria-hidden="true" />
              </button>
              <button
                type="button"
                onClick={() => onNavigate("validation")}
                className="flex items-center justify-between rounded-xl border border-[#D4CFF5] px-3 py-2 text-xs font-semibold text-[#25213B] hover:bg-[#CFC5F0] transition-colors"
              >
                <span className="flex items-center gap-2">
                  <FlaskConical className="w-3.5 h-3.5 text-[#138A67]" aria-hidden="true" />
                  <span>Isolated Container Tests</span>
                </span>
                <ArrowRight className="w-3.5 h-3.5 text-[#625D78]" aria-hidden="true" />
              </button>
            </div>
          </div>
        </section>
      </div>

      {/* Technology Stack Section */}
      <section className="rounded-xl border border-[#D4CFF5] bg-[#DCD7F2] p-6 shadow-sm">
        <h2 className="text-sm font-semibold text-[#25213B] mb-4">Technology Stack</h2>
        <div className="flex flex-wrap gap-2.5">
          {TECH_STACK.map((tech) => (
            <span
              key={tech.name}
              className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-semibold ${tech.color}`}
            >
              {tech.isUvicorn ? (
                <Zap className="w-3.5 h-3.5" aria-hidden="true" />
              ) : (
                <span className="text-sm leading-none" aria-hidden="true">{tech.icon}</span>
              )}
              <span>{tech.name}</span>
            </span>
          ))}
        </div>
        <p className="mt-3 text-xs text-[#625D78]">
          RootPatch combines a React/TypeScript frontend with a Python/FastAPI backend,
          PostgreSQL and Supabase Storage for remote validation job metadata and snapshots,
          and Docker for isolated test execution.
        </p>
      </section>
    </div>
  );
}
