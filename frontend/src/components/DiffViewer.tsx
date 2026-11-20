import { sanitizeDisplayText } from "../utils/sanitize";

function lineStyle(line: string): string {
  if (line.startsWith("+++") || line.startsWith("---")) {
    return "text-[#625D78] font-semibold";
  }
  if (line.startsWith("@@")) {
    return "bg-blue-950/60 text-blue-300";
  }
  if (line.startsWith("+")) {
    return "bg-emerald-950/50 text-emerald-300";
  }
  if (line.startsWith("-")) {
    return "bg-red-950/50 text-red-300";
  }
  return "text-slate-200";
}

export function UnifiedDiffView({ diff }: { diff: string }) {
  const safeLines = sanitizeDisplayText(diff).split(/\r?\n/);

  return (
    <div className="rounded-xl border border-[#D4CFF5] bg-slate-950 overflow-x-auto">
      <pre className="py-3 text-xs leading-relaxed font-mono">
        {safeLines.map((line, index) => (
          <div key={index} className={`px-4 whitespace-pre ${lineStyle(line)}`}>
            <span className="inline-block w-8 select-none text-[#625D78] tabular-nums">
              {index + 1}
            </span>
            <span>{line || " "}</span>
          </div>
        ))}
      </pre>
    </div>
  );
}

export function CodeComparisonView({
  originalCode,
  proposedCode,
}: {
  originalCode?: string | null;
  proposedCode?: string | null;
}) {
  const safeOriginal = sanitizeDisplayText(originalCode, "Original code unavailable.");
  const safeProposed = sanitizeDisplayText(proposedCode, "Proposed code unavailable.");

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div className="rounded-xl border border-[#D4CFF5] bg-[#DCD7F2] overflow-hidden">
        <div className="border-b border-[#D4CFF5] bg-[#E2DFF1] px-4 py-2 text-xs font-semibold text-[#25213B]">
          Original Code
        </div>
        <pre className="max-h-96 overflow-auto p-4 text-xs leading-relaxed font-mono text-[#25213B] whitespace-pre">
          {safeOriginal}
        </pre>
      </div>
      <div className="rounded-xl border border-[#D4CFF5] bg-[#DCD7F2] overflow-hidden">
        <div className="border-b border-[#D4CFF5] bg-[#E2DFF1] px-4 py-2 text-xs font-semibold text-[#25213B]">
          Proposed Code
        </div>
        <pre className="max-h-96 overflow-auto p-4 text-xs leading-relaxed font-mono text-[#25213B] whitespace-pre">
          {safeProposed}
        </pre>
      </div>
    </div>
  );
}
