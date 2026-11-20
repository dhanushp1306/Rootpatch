import { AlertCircle, AlertTriangle, CheckCircle2, Info, Loader2 } from "lucide-react";
import type { ReactNode } from "react";

type BannerVariant = "error" | "warning" | "success" | "info";

const STYLES: Record<BannerVariant, string> = {
  error: "border-red-200 bg-red-50 text-red-900",
  warning: "border-amber-200 bg-[#F5E4D4] text-amber-900",
  success: "border-emerald-200 bg-[#E1FAF5] text-emerald-900",
  info: "border-[#D4CFF5] bg-[#DCD7F2] text-[#25213B]",
};

export function StateBanner({
  variant,
  title,
  message,
  action,
}: {
  variant: BannerVariant;
  title: string;
  message?: string;
  action?: ReactNode;
}) {
  const Icon =
    variant === "error"
      ? AlertCircle
      : variant === "warning"
        ? AlertTriangle
        : variant === "success"
          ? CheckCircle2
          : Info;

  return (
    <div
      role={variant === "error" ? "alert" : "status"}
      className={`flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border px-4 py-3 text-sm ${STYLES[variant]}`}
    >
      <div className="flex items-start gap-2.5 min-w-0">
        <Icon className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
        <div className="min-w-0">
          <p className="font-semibold">{title}</p>
          {message ? <p className="mt-0.5 text-xs opacity-90 break-words">{message}</p> : null}
        </div>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function LoadingState({ label = "Loading workspace data..." }: { label?: string }) {
  return (
    <div
      role="status"
      className="flex items-center gap-3 rounded-xl border border-[#D4CFF5] bg-[#DCD7F2] px-5 py-6 text-sm text-[#625D78]"
    >
      <Loader2 className="w-4 h-4 animate-spin text-[#6545D5] shrink-0" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-[#D4CFF5] bg-[#DCD7F2] px-6 py-10 text-center">
      <h3 className="text-base font-semibold text-[#25213B]">{title}</h3>
      <p className="mx-auto mt-1.5 max-w-md text-sm text-[#625D78]">{description}</p>
      {action ? <div className="mt-5 flex justify-center">{action}</div> : null}
    </div>
  );
}
