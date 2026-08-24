export function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export function scoreTone(score: number | null): string {
  if (score === null) return "text-slate-500";
  if (score >= 85) return "text-ok";
  if (score >= 65) return "text-warn";
  return "text-danger";
}

export function formatSourceFormat(value: string): string {
  return value.replace("_", " ").toUpperCase();
}

export function formatDimension(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function statusTone(status?: string | null): string {
  if (status === "PASSED") return "text-good";
  if (status === "FAILED" || status === "ERROR") return "text-danger";
  if (status === "SKIPPED") return "text-slate-500";
  return "text-slate-600";
}
