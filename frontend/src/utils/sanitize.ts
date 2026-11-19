/**
 * Security & formatting utilities for untrusted repository text displayed in React.
 * React escapes rendered text nodes automatically; these helpers additionally strip
 * terminal/ANSI escape sequences and ASCII control characters before rendering.
 */

const ANSI_ESCAPE_RE = /\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])/g;
const CONTROL_CHARS_RE = /[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g;

export function sanitizeDisplayText(value: string | null | undefined, fallback = ""): string {
  if (!value) {
    return fallback;
  }
  return value.replace(ANSI_ESCAPE_RE, "").replace(CONTROL_CHARS_RE, "");
}

export function sanitizeSingleLine(value: string | null | undefined, fallback = ""): string {
  return sanitizeDisplayText(value, fallback).replace(/[\r\n]+/g, " ").trim();
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) {
    return "0 B";
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const units = ["KB", "MB", "GB"];
  let val = bytes / 1024;
  let idx = 0;
  while (val >= 1024 && idx < units.length - 1) {
    val /= 1024;
    idx += 1;
  }
  return `${val.toFixed(1)} ${units[idx]}`;
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) {
    return "—";
  }
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return sanitizeSingleLine(iso, "—");
  }
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function isValidProjectIdFormat(value: string): boolean {
  return /^[0-9a-f]{32}$/.test(value.trim());
}
