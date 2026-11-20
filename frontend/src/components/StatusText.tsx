import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Info,
  ShieldAlert,
  XCircle,
} from "lucide-react";

type Tone = "neutral" | "success" | "warning" | "danger" | "info";

function resolveTone(value: string): Tone {
  const upper = value.toUpperCase();
  if (
    upper === "PASSED" ||
    upper === "APPLIED" ||
    upper === "APPROVED" ||
    upper === "COMPLETED" ||
    upper === "HEALTHY" ||
    upper === "READY"
  ) {
    return "success";
  }
  if (
    upper === "CRITICAL" ||
    upper === "HIGH" ||
    upper === "FAILED" ||
    upper === "REJECTED" ||
    upper === "APPLICATION_FAILED" ||
    upper === "TIMED_OUT" ||
    upper === "ERROR"
  ) {
    return "danger";
  }
  if (
    upper === "MEDIUM" ||
    upper === "BLOCKED" ||
    upper === "STALE" ||
    upper === "PARTIAL" ||
    upper === "INSUFFICIENT_CONTEXT"
  ) {
    return "warning";
  }
  if (upper === "GENERATED" || upper === "PENDING" || upper === "RUNNING") {
    return "info";
  }
  return "neutral";
}

const TONE_CLASSES: Record<Tone, string> = {
  success: "text-emerald-700",
  danger: "text-red-700",
  warning: "text-amber-700",
  info: "text-[#6545D5]",
  neutral: "text-[#625D78]",
};

function renderToneIcon(tone: Tone, value: string) {
  const upper = value.toUpperCase();
  const cls = "w-3.5 h-3.5 shrink-0";
  if (tone === "success") {
    return <CheckCircle2 className={cls} aria-hidden="true" />;
  }
  if (upper === "TIMED_OUT" || upper === "PENDING" || upper === "RUNNING") {
    return <Clock className={cls} aria-hidden="true" />;
  }
  if (upper === "BLOCKED" || upper === "STALE") {
    return <ShieldAlert className={cls} aria-hidden="true" />;
  }
  if (tone === "danger") {
    return upper === "CRITICAL" ? (
      <AlertOctagon className={cls} aria-hidden="true" />
    ) : (
      <XCircle className={cls} aria-hidden="true" />
    );
  }
  if (tone === "warning") {
    return <AlertTriangle className={cls} aria-hidden="true" />;
  }
  return <Info className={cls} aria-hidden="true" />;
}

export function StatusText({
  label,
  tone,
}: {
  label: string;
  tone?: Tone;
}) {
  const resolved = tone ?? resolveTone(label);
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-xs font-semibold whitespace-nowrap ${TONE_CLASSES[resolved]}`}
    >
      {renderToneIcon(resolved, label)}
      <span>{label}</span>
    </span>
  );
}
