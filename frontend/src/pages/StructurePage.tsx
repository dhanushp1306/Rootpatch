import { useState } from "react";
import { FileTree } from "../components/FileTree";
import { EmptyState, LoadingState, StateBanner } from "../components/StateBanner";
import type { ProjectMetadata, StructureNode, StructureResponse } from "../types/api";
import { formatBytes, sanitizeSingleLine } from "../utils/sanitize";

interface StructurePageProps {
  project: ProjectMetadata | null;
  structure: StructureResponse | null;
  loading: boolean;
  onGoToUpload: () => void;
}

export function StructurePage({
  project,
  structure,
  loading,
  onGoToUpload,
}: StructurePageProps) {
  const [selectedNode, setSelectedNode] = useState<StructureNode | null>(null);

  if (!project) {
    return (
      <EmptyState
        title="No Project Selected"
        description="Upload or open a project workspace first to inspect its directory tree."
        action={
          <button
            type="button"
            onClick={onGoToUpload}
            className="rounded-lg bg-[#6545D5] px-4 py-2 text-sm font-semibold text-white hover:bg-[#5535C5] whitespace-nowrap"
          >
            Go to Upload
          </button>
        }
      />
    );
  }

  if (loading && !structure) {
    return <LoadingState label="Loading project file tree..." />;
  }

  if (!structure) {
    return (
      <StateBanner
        variant="info"
        title="Project Structure Unavailable"
        message="Refresh the workspace to retrieve the extracted file tree."
      />
    );
  }

  const inspection = project.inspection;

  return (
    <div className="space-y-6">
      {structure.truncated ? (
        <StateBanner
          variant="warning"
          title="Structure Tree Truncated"
          message={`Showing ${structure.total_nodes} nodes up to the backend inspection cap.`}
        />
      ) : null}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
        <div className="lg:col-span-2 space-y-3">
          <div className="flex items-center justify-between text-xs text-[#625D78]">
            <span className="font-mono">
              root: {sanitizeSingleLine(structure.root_directory)}
            </span>
            <span className="tabular-nums">{structure.total_nodes} nodes</span>
          </div>
          <FileTree
            tree={structure.tree}
            selectedPath={selectedNode?.path ?? null}
            onSelect={setSelectedNode}
            testFiles={inspection.test_files}
          />
        </div>

        <aside className="space-y-4">
          <section className="rounded-xl border border-[#D4CFF5] bg-[#DCD7F2] p-5 space-y-3">
            <h2 className="text-sm font-semibold text-[#25213B]">Selected Entry</h2>
            {selectedNode ? (
              <dl className="space-y-2 text-xs">
                <div>
                  <dt className="text-[#625D78]">Name</dt>
                  <dd className="font-mono font-semibold text-[#25213B] break-all">
                    {sanitizeSingleLine(selectedNode.name)}
                  </dd>
                </div>
                <div>
                  <dt className="text-[#625D78]">Relative Path</dt>
                  <dd className="font-mono text-[#25213B] break-all">
                    {sanitizeSingleLine(selectedNode.path)}
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-[#625D78]">Type</dt>
                  <dd className="font-medium text-[#25213B]">{selectedNode.type}</dd>
                </div>
                {selectedNode.size_bytes != null ? (
                  <div className="flex justify-between gap-2">
                    <dt className="text-[#625D78]">Size</dt>
                    <dd className="font-mono text-[#25213B] tabular-nums">
                      {formatBytes(selectedNode.size_bytes)}
                    </dd>
                  </div>
                ) : null}
                {selectedNode.children ? (
                  <div className="flex justify-between gap-2">
                    <dt className="text-[#625D78]">Direct Children</dt>
                    <dd className="font-mono text-[#25213B] tabular-nums">
                      {selectedNode.children.length}
                    </dd>
                  </div>
                ) : null}
              </dl>
            ) : (
              <p className="text-xs text-[#625D78]">
                Select a file or directory in the tree to view metadata.
              </p>
            )}
          </section>

          <section className="rounded-xl border border-[#D4CFF5] bg-[#DCD7F2] p-5 space-y-3 text-xs">
            <h2 className="text-sm font-semibold text-[#25213B]">Source & Test Layout</h2>
            <div>
              <p className="font-medium text-[#25213B] mb-1">Source Directories</p>
              {inspection.source_directories.length === 0 ? (
                <p className="text-[#625D78]">None detected</p>
              ) : (
                <ul className="space-y-1 font-mono text-[#25213B]">
                  {inspection.source_directories.map((dir) => (
                    <li key={dir.path} className="flex justify-between gap-2">
                      <span className="truncate">{sanitizeSingleLine(dir.path)}</span>
                      <span className="text-[#625D78] tabular-nums shrink-0">
                        {dir.source_file_count}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="border-t border-[#D4CFF5] pt-3">
              <p className="font-medium text-[#25213B] mb-1">
                Test Files ({inspection.test_file_count})
              </p>
              {inspection.test_files.length === 0 ? (
                <p className="text-[#625D78]">No test files detected</p>
              ) : (
                <ul className="space-y-1 font-mono text-[#25213B] max-h-48 overflow-y-auto">
                  {inspection.test_files.map((tf) => (
                    <li key={tf} className="truncate">
                      {sanitizeSingleLine(tf)}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
