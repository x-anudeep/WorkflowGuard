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
