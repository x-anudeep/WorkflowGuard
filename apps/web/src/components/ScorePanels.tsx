import type { EvaluationFinding, ValidationFinding } from "@/types/workflow";

export function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="border border-line bg-panel p-4 text-sm text-slate-600">{children}</div>;
}

/** One dimension score. The number is the point of the card, so it leads. */
export function ScoreCard({
  label,
  score,
  note,
}: {
  label: string;
  score: number | null | undefined;
  note?: string;
}) {
  const value = typeof score === "number" ? Math.round(score) : null;
  return (
    <div className="border border-line bg-white p-4">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-3xl font-semibold ${toneFor(value)}`}>
        {value === null ? "—" : value}
        {value !== null && <span className="ml-1 text-base font-normal text-slate-400">/100</span>}
      </div>
      {note && <div className="mt-1 text-xs text-slate-500">{note}</div>}
    </div>
  );
}

export function FindingCard({ finding }: { finding: ValidationFinding | EvaluationFinding }) {
  return (
    <div className="border border-line bg-white p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-sm px-2 py-0.5 text-xs font-semibold ${severityTone(finding.severity)}`}>
          {finding.severity}
        </span>
        <span className="text-sm font-medium">{finding.title}</span>
        <span className="text-xs text-slate-400">{finding.rule_id}</span>
      </div>
      <p className="mt-2 text-sm text-slate-700">{finding.message}</p>
      {finding.remediation && <p className="mt-1.5 text-sm text-slate-500">{finding.remediation}</p>}
    </div>
  );
}

function toneFor(score: number | null): string {
  if (score === null) return "text-slate-400";
  if (score >= 85) return "text-success";
  if (score >= 70) return "text-ink";
  return "text-danger";
}

function severityTone(severity: string): string {
  if (severity === "CRITICAL" || severity === "ERROR") return "bg-red-50 text-danger";
  if (severity === "WARNING") return "bg-amber-50 text-amber-700";
  return "bg-panel text-slate-600";
}
