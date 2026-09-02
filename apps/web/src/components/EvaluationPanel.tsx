"use client";

import { useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";

import { api } from "@/lib/api";
import { formatDate, formatDimension, scoreTone } from "@/lib/format";
import type { EvaluationFinding, EvaluationRun } from "@/types/workflow";

export function EvaluationPanel({ workflowId, initialEvaluations }: { workflowId: string; initialEvaluations: EvaluationRun[] }) {
  const [evaluations, setEvaluations] = useState(initialEvaluations);
  const [selectedId, setSelectedId] = useState(initialEvaluations[0]?.id ?? "");
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selected = evaluations.find((evaluation) => evaluation.id === selectedId) ?? evaluations[0] ?? null;

  async function runEvaluation() {
    setIsRunning(true);
    setError(null);
    try {
      const evaluation = await api.evaluate(workflowId, true);
      setEvaluations((current) => [evaluation, ...current]);
      setSelectedId(evaluation.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Evaluation failed");
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="text-sm text-slate-600">
          Deterministic validation is separate from AI-assisted semantic evaluation.
        </div>
        <div className="flex items-center gap-2">
          {evaluations.length > 1 && (
            <select
              value={selected?.id ?? ""}
              onChange={(event) => setSelectedId(event.target.value)}
              className="border border-line bg-white px-3 py-2 text-sm"
            >
              {evaluations.map((evaluation) => (
                <option key={evaluation.id} value={evaluation.id}>
                  {formatDate(evaluation.created_at)}
                </option>
              ))}
            </select>
          )}
          <button
            type="button"
            onClick={runEvaluation}
            disabled={isRunning}
            className="inline-flex items-center gap-2 rounded-md bg-ink px-3 py-2 text-sm font-medium text-white disabled:opacity-60"
          >
            <RefreshCw size={16} />
            {isRunning ? "Evaluating..." : "Run evaluation"}
          </button>
        </div>
      </div>
      {error && <div className="border border-danger bg-red-50 p-3 text-sm text-danger">{error}</div>}
      {!selected ? (
        <div className="border border-line bg-panel p-4 text-sm text-slate-700">
          No semantic evaluation has been run for this workflow yet.
        </div>
      ) : (
        <EvaluationResultView evaluation={selected} />
      )}
    </div>
  );
}

function EvaluationResultView({ evaluation }: { evaluation: EvaluationRun }) {
  const grouped = useMemo(() => groupFindings(evaluation.findings), [evaluation.findings]);
  return (
    <div className="grid gap-5">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
        <Score label="Overall" score={evaluation.overall_score} />
        {evaluation.dimension_scores.map((score) => (
          <Score key={score.dimension} label={formatDimension(score.dimension)} score={score.score} />
        ))}
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="border border-line bg-panel p-4 text-sm text-slate-700">
          <div className="font-semibold text-ink">Evaluator</div>
          <div className="mt-2">Version: {evaluation.evaluator_version}</div>
          <div>AI: {evaluation.ai_provider ? `${evaluation.ai_provider} / ${evaluation.ai_model}` : "deterministic fallback"}</div>
          <div>Status: {String(evaluation.ai_metadata.ai_status ?? evaluation.status)}</div>
        </div>
        <div className="border border-line bg-panel p-4 text-sm text-slate-700">
          <div className="font-semibold text-ink">Limitations</div>
          <ul className="mt-2 list-inside list-disc">
            {evaluation.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
          </ul>
        </div>
      </div>

      <section>
        <h3 className="mb-3 text-sm font-semibold">Requirement vs Implementation</h3>
        <div className="overflow-hidden border border-line">
          <table className="w-full min-w-[720px] border-collapse text-left text-sm">
            <thead className="bg-panel text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Requirement</th>
                <th className="px-4 py-3">Judged by</th>
                <th className="px-4 py-3">Workflow</th>
                <th className="px-4 py-3">Evidence</th>
              </tr>
            </thead>
            <tbody>
              {evaluation.requirement_matches.map((match) => (
                <tr key={match.requirement_id} className="border-t border-line">
                  <td className="px-4 py-3">{match.requirement_text}</td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {!match.match_method || match.match_method === "deterministic" ? "Keyword match" : match.match_method.replace("ai:", "AI: ")}
                  </td>
                  <td className="px-4 py-3 font-semibold">{match.status === "matched" ? "Yes" : "No"} - {match.status}</td>
                  <td className="px-4 py-3 text-slate-600">{match.evidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {(["CRITICAL", "ERROR", "WARNING", "INFO"] as const).map((severity) => (
        grouped[severity]?.length ? (
          <section key={severity}>
            <h3 className="mb-3 text-sm font-semibold">{severity}</h3>
            <div className="grid gap-3">
              {grouped[severity].map((finding) => <FindingCard key={finding.id ?? `${finding.rule_id}-${finding.message}`} finding={finding} />)}
            </div>
          </section>
        ) : null
      ))}
    </div>
  );
}

function Score({ label, score }: { label: string; score: number }) {
  return (
    <div className="border border-line bg-white p-4">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className={`mt-2 text-2xl font-semibold ${scoreTone(score)}`}>{score}</div>
    </div>
  );
}

function FindingCard({ finding }: { finding: EvaluationFinding }) {
  return (
    <details className="border border-line p-4" open={finding.severity === "CRITICAL"}>
      <summary className="cursor-pointer text-sm font-semibold">
        {finding.rule_id} - {formatDimension(finding.dimension)} - {finding.title}
      </summary>
      <div className="mt-3 grid gap-2 text-sm text-slate-700">
        <p>{finding.message}</p>
        <Field label="Expected" value={finding.expected} />
        <Field label="Found" value={finding.found} />
        <Field label="Why" value={finding.why_it_matters} />
        {finding.node_id && <Field label="Node" value={finding.node_id} />}
        {finding.path.length > 0 && <Field label="Path" value={finding.path.join(" -> ")} />}
        {finding.remediation && <Field label="Correction" value={finding.remediation} />}
        <Field label="Confidence" value={finding.confidence} />
      </div>
    </details>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="font-medium text-ink">{label}: </span>
      <span>{value}</span>
    </div>
  );
}

function groupFindings(findings: EvaluationFinding[]) {
  return findings.reduce<Record<string, EvaluationFinding[]>>((groups, finding) => {
    groups[finding.severity] = groups[finding.severity] ?? [];
    groups[finding.severity].push(finding);
    return groups;
  }, {});
}
