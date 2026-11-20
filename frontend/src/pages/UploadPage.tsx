import { ArrowRight, CheckCircle2, FileArchive, Loader2, UploadCloud } from "lucide-react";
import { useRef, useState } from "react";
import { StateBanner } from "../components/StateBanner";
import { ApiError, RootPatchApiClient } from "../services/apiClient";
import type { ProjectMetadata } from "../types/api";
import {
  formatBytes,
  isValidProjectIdFormat,
  sanitizeSingleLine,
} from "../utils/sanitize";

interface UploadPageProps {
  client: RootPatchApiClient;
  activeProject: ProjectMetadata | null;
  onProjectReady: (project: ProjectMetadata) => void;
  onContinueToStructure: () => void;
  onContinueToScan: () => void;
}

export function UploadPage({
  client,
  activeProject,
  onProjectReady,
  onContinueToStructure,
  onContinueToScan,
}: UploadPageProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadNotice, setUploadNotice] = useState<string | null>(null);

  const [lookupId, setLookupId] = useState("");
  const [loadingExisting, setLoadingExisting] = useState(false);
  const [lookupError, setLookupError] = useState<string | null>(null);

  const handleFileSelected = (file: File | null) => {
    setUploadError(null);
    setUploadNotice(null);
    setProgress(0);
    setSelectedFile(file);
  };

  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) {
      setUploadError("Select a .zip archive file before uploading.");
      return;
    }

    setUploading(true);
    setUploadError(null);
    setUploadNotice(null);
    setProgress(0);

    try {
      const uploaded = await client.uploadProject(selectedFile, (pct) => setProgress(pct));
      setProgress(100);
      const metadata = await client.getProject(uploaded.project_id);
      onProjectReady(metadata);
      setUploadNotice(
        `${sanitizeSingleLine(uploaded.message)} Project ID: ${uploaded.project_id}`
      );
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? `${err.detail}${err.status ? ` (HTTP ${err.status})` : ""}`
          : err instanceof Error
            ? err.message
            : "Archive upload failed.";
      setUploadError(msg);
    } finally {
      setUploading(false);
    }
  };

  const handleLoadProject = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleaned = lookupId.trim().toLowerCase();
    if (!isValidProjectIdFormat(cleaned)) {
      setLookupError("Enter a valid 32-character hexadecimal project ID.");
      return;
    }
    setLoadingExisting(true);
    setLookupError(null);
    try {
      const metadata = await client.getProject(cleaned);
      onProjectReady(metadata);
      setLookupId("");
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? `${err.detail}${err.status ? ` (HTTP ${err.status})` : ""}`
          : "Failed to load project metadata.";
      setLookupError(msg);
    } finally {
      setLoadingExisting(false);
    }
  };

  const inspection = activeProject?.inspection;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <form
          onSubmit={handleUploadSubmit}
          className="lg:col-span-2 rounded-xl border border-[#D4CFF5] bg-[#DCD7F2] p-6 space-y-5"
        >
          <div>
            <h2 className="text-base font-semibold text-[#25213B]">Upload Project Archive</h2>
            <p className="mt-1 text-xs text-[#625D78]">
              Upload a <code className="font-mono">.zip</code> source archive. RootPatch extracts it
              into an isolated workspace and inspects files without executing code on the host.
            </p>
          </div>

          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              const dropped = e.dataTransfer.files?.[0] ?? null;
              handleFileSelected(dropped);
            }}
            className={`rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors ${
              dragging
                ? "border-indigo-500 bg-[#CFC5F0]"
                : "border-[#C7C0F0] bg-[#E2DFF1] hover:border-slate-400"
            }`}
          >
            <UploadCloud className="mx-auto w-8 h-8 text-[#625D78]" aria-hidden="true" />
            <p className="mt-2 text-sm font-medium text-[#25213B]">
              Drag and drop a <span className="font-mono">.zip</span> archive here
            </p>
            <p className="mt-1 text-xs text-[#625D78]">
              or browse your local filesystem (max 50 MB default backend limit)
            </p>
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip,application/zip"
              aria-label="Project archive file"
              onChange={(e) => handleFileSelected(e.target.files?.[0] ?? null)}
              className="sr-only"
            />
            <div className="mt-4">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="rounded-lg border border-[#C7C0F0] bg-[#DCD7F2] px-3.5 py-2 text-xs font-semibold text-[#25213B] hover:bg-[#E2DFF1] whitespace-nowrap"
              >
                Choose .zip File
              </button>
            </div>
          </div>

          {selectedFile ? (
            <div className="flex items-center justify-between gap-3 rounded-lg border border-[#D4CFF5] bg-[#E2DFF1] px-4 py-3 text-xs">
              <div className="flex items-center gap-2.5 min-w-0">
                <FileArchive className="w-4 h-4 text-[#6545D5] shrink-0" aria-hidden="true" />
                <span className="font-mono font-medium text-[#25213B] truncate">
                  {sanitizeSingleLine(selectedFile.name)}
                </span>
              </div>
              <span className="font-mono text-[#625D78] tabular-nums shrink-0">
                {formatBytes(selectedFile.size)}
              </span>
            </div>
          ) : null}

          {uploading || progress > 0 ? (
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs text-[#625D78]">
                <span>{uploading ? "Uploading and inspecting archive..." : "Upload complete"}</span>
                <span className="font-mono tabular-nums">{progress}%</span>
              </div>
              <div className="h-2 w-full rounded-full bg-indigo-100 overflow-hidden">
                <div
                  className="h-full bg-[#6545D5] transition-all"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          ) : null}

          {uploadError ? (
            <StateBanner variant="error" title="Upload Failed" message={uploadError} />
          ) : null}
          {uploadNotice ? (
            <StateBanner variant="success" title="Project Ready" message={uploadNotice} />
          ) : null}

          <div className="flex items-center justify-end gap-3">
            <button
              type="submit"
              disabled={!selectedFile || uploading}
              className="inline-flex items-center gap-2 rounded-lg bg-[#6545D5] px-4 py-2 text-sm font-semibold text-white hover:bg-[#5535C5] disabled:opacity-50 whitespace-nowrap shrink-0"
            >
              {uploading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
                  <span>Uploading...</span>
                </>
              ) : (
                <span>Upload & Inspect</span>
              )}
            </button>
          </div>
        </form>

        <form
          onSubmit={handleLoadProject}
          className="rounded-xl border border-[#D4CFF5] bg-[#DCD7F2] p-6 space-y-4"
        >
          <div>
            <h2 className="text-base font-semibold text-[#25213B]">Load Existing Project</h2>
            <p className="mt-1 text-xs text-[#625D78]">
              Open a previously uploaded workspace by its 32-character hexadecimal{" "}
              <code className="font-mono">project_id</code>.
            </p>
          </div>

          <div>
            <label htmlFor="load-project-id" className="block text-xs font-medium text-[#25213B]">
              Project ID
            </label>
            <input
              id="load-project-id"
              type="text"
              value={lookupId}
              onChange={(e) => setLookupId(e.target.value)}
              placeholder="e.g. 9f3c1e7b42..."
              className="mt-1.5 w-full rounded-lg border border-[#C7C0F0] px-3 py-2 font-mono text-xs text-[#25213B] focus:border-indigo-500 focus:outline-none"
            />
          </div>

          {lookupError ? (
            <StateBanner variant="error" title="Lookup Failed" message={lookupError} />
          ) : null}

          <button
            type="submit"
            disabled={loadingExisting}
            className="w-full rounded-lg border border-[#C7C0F0] bg-[#DCD7F2] px-4 py-2 text-xs font-semibold text-[#25213B] hover:bg-[#E2DFF1] disabled:opacity-50 whitespace-nowrap"
          >
            {loadingExisting ? "Loading Project..." : "Load Project Workspace"}
          </button>
        </form>
      </div>

      {/* Inspection Report */}
      {activeProject && inspection ? (
        <section className="rounded-xl border border-[#D4CFF5] bg-[#DCD7F2] p-6 space-y-5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#D4CFF5] pb-4">
            <div>
              <div className="flex items-center gap-2 text-emerald-700 text-xs font-semibold">
                <CheckCircle2 className="w-4 h-4" aria-hidden="true" />
                <span>Inspection Report</span>
              </div>
              <h3 className="mt-1 text-base font-semibold text-[#25213B]">
                {sanitizeSingleLine(activeProject.project_name)}
              </h3>
              <p className="text-xs text-[#625D78] font-mono">
                {activeProject.project_id} · {activeProject.archive.files_extracted} extracted files ·{" "}
                {formatBytes(activeProject.archive.extracted_bytes)}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={onContinueToStructure}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[#C7C0F0] bg-[#DCD7F2] px-3 py-1.5 text-xs font-semibold text-[#25213B] hover:bg-[#E2DFF1] whitespace-nowrap shrink-0"
              >
                <span>Browse Structure</span>
                <ArrowRight className="w-3.5 h-3.5" aria-hidden="true" />
              </button>
              <button
                type="button"
                onClick={onContinueToScan}
                className="inline-flex items-center gap-1.5 rounded-lg bg-[#6545D5] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#5535C5] whitespace-nowrap shrink-0"
              >
                <span>Run Static Scan</span>
                <ArrowRight className="w-3.5 h-3.5" aria-hidden="true" />
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
            <div className="rounded-lg border border-[#D4CFF5] bg-[#E2DFF1] p-3.5">
              <span className="text-[#625D78]">Total Files</span>
              <p className="mt-1 text-lg font-bold text-[#25213B] tabular-nums">
                {inspection.total_files}
              </p>
            </div>
            <div className="rounded-lg border border-[#D4CFF5] bg-[#E2DFF1] p-3.5">
              <span className="text-[#625D78]">Directories</span>
              <p className="mt-1 text-lg font-bold text-[#25213B] tabular-nums">
                {inspection.total_directories}
              </p>
            </div>
            <div className="rounded-lg border border-[#D4CFF5] bg-[#E2DFF1] p-3.5">
              <span className="text-[#625D78]">Python Detected</span>
              <p className="mt-1 text-lg font-bold text-[#25213B]">
                {inspection.python_detected ? "Yes" : "No"}
              </p>
            </div>
            <div className="rounded-lg border border-[#D4CFF5] bg-[#E2DFF1] p-3.5">
              <span className="text-[#625D78]">Test Files</span>
              <p className="mt-1 text-lg font-bold text-[#25213B] tabular-nums">
                {inspection.test_file_count}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-5 text-xs">
            <div>
              <h4 className="font-semibold text-[#25213B] mb-2">Detected Languages</h4>
              {inspection.languages.length === 0 ? (
                <p className="text-[#625D78]">No recognized source languages.</p>
              ) : (
                <ul className="space-y-1.5 text-[#25213B]">
                  {inspection.languages.map((lang) => (
                    <li key={lang.name} className="flex justify-between gap-2">
                      <span>{sanitizeSingleLine(lang.name)}</span>
                      <span className="font-mono text-[#625D78] tabular-nums">
                        {lang.file_count} files
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div>
              <h4 className="font-semibold text-[#25213B] mb-2">Dependency Manifests</h4>
              {inspection.dependency_manifests.length === 0 ? (
                <p className="text-[#625D78]">No manifests detected.</p>
              ) : (
                <ul className="space-y-1.5 font-mono text-[#25213B]">
                  {inspection.dependency_manifests.map((m) => (
                    <li key={m.path} className="truncate">
                      {sanitizeSingleLine(m.path)}
                      {m.ecosystem ? (
                        <span className="ml-1.5 font-sans text-[#625D78]">
                          ({sanitizeSingleLine(m.ecosystem)})
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div>
              <h4 className="font-semibold text-[#25213B] mb-2">Configuration Files</h4>
              {inspection.configuration_files.length === 0 ? (
                <p className="text-[#625D78]">No config files detected.</p>
              ) : (
                <ul className="space-y-1.5 font-mono text-[#25213B]">
                  {inspection.configuration_files.slice(0, 10).map((cfg) => (
                    <li key={cfg.path} className="truncate">
                      {sanitizeSingleLine(cfg.path)}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          {inspection.warnings.length > 0 ? (
            <StateBanner
              variant="warning"
              title="Inspection Warnings"
              message={inspection.warnings.map((w) => sanitizeSingleLine(w)).join(" · ")}
            />
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
