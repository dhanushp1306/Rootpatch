import {
  Bug,
  FileCheck2,
  FlaskConical,
  FolderTree,
  History,
  LayoutDashboard,
  Menu,
  RefreshCw,
  Upload,
  X,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import type { KnownProjectSummary } from "../hooks/useProjectRegistry";
import type { HealthResponse, ProjectMetadata } from "../types/api";
import { isValidProjectIdFormat, sanitizeSingleLine } from "../utils/sanitize";
import { StatusText } from "./StatusText";

export type NavSection =
  | "dashboard"
  | "upload"
  | "structure"
  | "findings"
  | "patches"
  | "validation"
  | "history";

interface AppShellProps {
  activeSection: NavSection;
  onNavigate: (section: NavSection) => void;
  knownProjects: KnownProjectSummary[];
  activeProjectId: string | null;
  onSelectProject: (projectId: string) => void;
  project: ProjectMetadata | null;
  health: HealthResponse | null;
  healthError: string | null;
  onRefresh: () => void;
  refreshing: boolean;
  counts: {
    findings: number;
    patches: number;
    validations: number;
  };
  children: ReactNode;
}

const NAV_ITEMS: { id: NavSection; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "upload", label: "Upload Project", icon: Upload },
  { id: "structure", label: "Project Structure", icon: FolderTree },
  { id: "findings", label: "Bugs & Root Cause", icon: Bug },
  { id: "patches", label: "Patch Review", icon: FileCheck2 },
  { id: "validation", label: "Validation", icon: FlaskConical },
  { id: "history", label: "History", icon: History },
];

export function AppShell({
  activeSection,
  onNavigate,
  knownProjects,
  activeProjectId,
  onSelectProject,
  project,
  health,
  healthError,
  onRefresh,
  refreshing,
  counts,
  children,
}: AppShellProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [lookupId, setLookupId] = useState("");
  const [lookupError, setLookupError] = useState<string | null>(null);

  const handleOpenById = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = lookupId.trim().toLowerCase();
    if (!isValidProjectIdFormat(trimmed)) {
      setLookupError("Enter a valid 32-character hex project ID.");
      return;
    }
    setLookupError(null);
    onSelectProject(trimmed);
    setLookupId("");
    setMobileOpen(false);
  };

  const sidebarContent = (
    <div className="flex h-full flex-col bg-slate-900 text-slate-100">
      <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4">
        <span className="text-lg font-bold tracking-tight text-white whitespace-nowrap shrink-0">
          RootPatch
        </span>
        <button
          type="button"
          onClick={() => setMobileOpen(false)}
          className="lg:hidden rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white"
          aria-label="Close navigation"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      <div className="border-b border-slate-800 px-4 py-3.5 space-y-2.5">
        <label
          htmlFor="active-project-select"
          className="block text-xs font-medium text-slate-400"
        >
          Active Workspace Project
        </label>
        <select
          id="active-project-select"
          value={activeProjectId ?? ""}
          onChange={(e) => {
            if (e.target.value) {
              onSelectProject(e.target.value);
              setMobileOpen(false);
            }
          }}
          className="w-full rounded-md border border-slate-700 bg-slate-800 px-2.5 py-2 text-xs text-slate-100 focus:border-blue-500 focus:outline-none"
        >
          <option value="">
            {knownProjects.length ? "Select a project..." : "No project loaded"}
          </option>
          {knownProjects.map((p) => (
            <option key={p.project_id} value={p.project_id}>
              {sanitizeSingleLine(p.project_name)} ({p.project_id.slice(0, 8)})
            </option>
          ))}
        </select>

        <form onSubmit={handleOpenById} className="flex gap-1.5">
          <input
            type="text"
            value={lookupId}
            onChange={(e) => setLookupId(e.target.value)}
            placeholder="Open project ID..."
            aria-label="Open project by ID"
            className="min-w-0 flex-1 rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-200 placeholder:text-slate-500 focus:border-blue-500 focus:outline-none"
          />
          <button
            type="submit"
            className="rounded-md bg-slate-800 px-2.5 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700 whitespace-nowrap shrink-0"
          >
            Load
          </button>
        </form>
        {lookupError ? (
          <p className="text-xs text-red-400">{lookupError}</p>
        ) : null}
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-1" aria-label="Workspace sections">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = activeSection === item.id;
          let count: number | null = null;
          if (item.id === "findings" && counts.findings > 0) count = counts.findings;
          if (item.id === "patches" && counts.patches > 0) count = counts.patches;
          if (item.id === "validation" && counts.validations > 0) count = counts.validations;

          return (
            <button
              key={item.id}
              type="button"
              onClick={() => {
                onNavigate(item.id);
                setMobileOpen(false);
              }}
              className={`flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                active
                  ? "bg-blue-700 text-white"
                  : "text-slate-300 hover:bg-slate-800 hover:text-white"
              }`}
            >
              <span className="flex items-center gap-2.5 min-w-0">
                <Icon className="w-4 h-4 shrink-0" aria-hidden="true" />
                <span className="truncate">{item.label}</span>
              </span>
              {count !== null ? (
                <span className="font-mono text-xs tabular-nums opacity-85 shrink-0">
                  {count}
                </span>
              ) : null}
            </button>
          );
        })}
      </nav>

      <div className="border-t border-slate-800 px-4 py-3 text-xs text-slate-400">
        {health ? (
          <div className="flex items-center justify-between gap-2">
            <span>Backend API</span>
            <span className="font-medium text-emerald-400">{health.status}</span>
          </div>
        ) : (
          <div className="text-amber-400 truncate" title={healthError ?? undefined}>
            {healthError || "Backend status unknown"}
          </div>
        )}
      </div>
    </div>
  );

  const activeTitle =
    NAV_ITEMS.find((item) => item.id === activeSection)?.label ?? "RootPatch";

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex">
      {/* Desktop sidebar */}
      <aside className="hidden lg:block w-64 shrink-0 border-r border-slate-200">
        <div className="sticky top-0 h-screen">{sidebarContent}</div>
      </aside>

      {/* Mobile drawer */}
      {mobileOpen ? (
        <div className="fixed inset-0 z-50 flex lg:hidden">
          <div
            className="fixed inset-0 bg-slate-950/50"
            onClick={() => setMobileOpen(false)}
            aria-hidden="true"
          />
          <div className="relative z-10 w-72 max-w-[85vw] h-full">{sidebarContent}</div>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-4 border-b border-slate-200 bg-white px-4 sm:px-6 py-3.5">
          <div className="flex items-center gap-3 min-w-0">
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              className="lg:hidden rounded-md border border-slate-200 p-2 text-slate-700 hover:bg-slate-100"
              aria-label="Open navigation"
            >
              <Menu className="w-4 h-4" />
            </button>
            <div className="min-w-0">
              <h1 className="text-base sm:text-lg font-semibold text-slate-900 truncate">
                {activeTitle}
              </h1>
              {project ? (
                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span className="font-medium text-slate-700 truncate max-w-[180px] sm:max-w-xs">
                    {sanitizeSingleLine(project.project_name)}
                  </span>
                  <span aria-hidden="true">·</span>
                  <span className="font-mono">{project.project_id.slice(0, 12)}</span>
                  <span aria-hidden="true">·</span>
                  <StatusText label={project.status} />
                </div>
              ) : (
                <p className="text-xs text-slate-500">
                  Upload a project archive or load an existing project ID to begin.
                </p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            <button
              type="button"
              onClick={onRefresh}
              disabled={refreshing}
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 whitespace-nowrap shrink-0"
            >
              <RefreshCw
                className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`}
                aria-hidden="true"
              />
              <span>Refresh</span>
            </button>
          </div>
        </header>

        <main className="flex-1 px-4 sm:px-6 py-6 max-w-7xl w-full mx-auto">
          {children}
        </main>
      </div>
    </div>
  );
}
