import { ChevronDown, ChevronRight, FileCode2, Folder, FolderOpen } from "lucide-react";
import { useState } from "react";
import type { StructureNode } from "../types/api";
import { formatBytes, sanitizeSingleLine } from "../utils/sanitize";

interface TreeNodeProps {
  node: StructureNode;
  depth: number;
  selectedPath: string | null;
  onSelect: (node: StructureNode) => void;
  testFileSet: Set<string>;
}

function TreeNodeRow({
  node,
  depth,
  selectedPath,
  onSelect,
  testFileSet,
}: TreeNodeProps) {
  const [expanded, setExpanded] = useState(depth < 2);
  const isDir = node.type === "directory";
  const isSelected = selectedPath === node.path;
  const isTest = !isDir && testFileSet.has(node.path);

  return (
    <div>
      <button
        type="button"
        onClick={() => {
          if (isDir) {
            setExpanded((prev) => !prev);
          }
          onSelect(node);
        }}
        style={{ paddingLeft: `${depth * 16 + 12}px` }}
        className={`flex w-full items-center justify-between gap-3 py-1.5 pr-3 text-left text-sm transition-colors ${
          isSelected
            ? "bg-blue-50 text-blue-900 font-medium"
            : "text-slate-700 hover:bg-slate-100"
        }`}
      >
        <span className="flex items-center gap-2 min-w-0">
          {isDir ? (
            <>
              {expanded ? (
                <ChevronDown className="w-3.5 h-3.5 text-slate-400 shrink-0" aria-hidden="true" />
              ) : (
                <ChevronRight className="w-3.5 h-3.5 text-slate-400 shrink-0" aria-hidden="true" />
              )}
              {expanded ? (
                <FolderOpen className="w-4 h-4 text-blue-700 shrink-0" aria-hidden="true" />
              ) : (
                <Folder className="w-4 h-4 text-slate-500 shrink-0" aria-hidden="true" />
              )}
            </>
          ) : (
            <>
              <span className="w-3.5 shrink-0" aria-hidden="true" />
              <FileCode2 className="w-4 h-4 text-slate-500 shrink-0" aria-hidden="true" />
            </>
          )}
          <span className="truncate font-mono text-xs">{sanitizeSingleLine(node.name)}</span>
          {isTest ? (
            <span className="text-[11px] font-medium text-emerald-700 whitespace-nowrap shrink-0">
              test
            </span>
          ) : null}
        </span>
        {!isDir && node.size_bytes != null ? (
          <span className="font-mono text-xs text-slate-500 tabular-nums shrink-0">
            {formatBytes(node.size_bytes)}
          </span>
        ) : null}
      </button>

      {isDir && expanded && node.children ? (
        <div>
          {node.children.map((child) => (
            <TreeNodeRow
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              onSelect={onSelect}
              testFileSet={testFileSet}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function FileTree({
  tree,
  selectedPath,
  onSelect,
  testFiles = [],
}: {
  tree: StructureNode;
  selectedPath: string | null;
  onSelect: (node: StructureNode) => void;
  testFiles?: string[];
}) {
  const testFileSet = new Set(testFiles);

  return (
    <div className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white overflow-hidden">
      <div className="py-1">
        <TreeNodeRow
          node={tree}
          depth={0}
          selectedPath={selectedPath}
          onSelect={onSelect}
          testFileSet={testFileSet}
        />
      </div>
    </div>
  );
}
