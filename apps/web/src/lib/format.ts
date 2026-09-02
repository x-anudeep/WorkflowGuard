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

export function money(value: number): string {
  return new Intl.NumberFormat("en", { style: "currency", currency: "USD", maximumFractionDigits: 4 }).format(value);
}

export function isUuid(value: string | undefined): value is string {
  return Boolean(value && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value));
}
