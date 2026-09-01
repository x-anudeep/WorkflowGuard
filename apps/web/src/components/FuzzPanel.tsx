"use client";

import { useMemo, useState } from "react";
import { Bug, Lightbulb, ShieldAlert, Zap } from "lucide-react";

import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { ErrorHandlingVerdict, FuzzCase, FuzzRun } from "@/types/workflow";

const VERDICT_LABEL: Record<ErrorHandlingVerdict, string> = {
  handled: "Handled",
  unhandled_crash: "Crashed",
  silent_success: "Silently swallowed",
  hung: "Never terminated",
  not_triggered: "Not triggered",
};

const VERDICT_TONE: Record<ErrorHandlingVerdict, string> = {
  handled: "bg-green-50 text-good border-good",
  unhandled_crash: "bg-red-50 text-danger border-danger",
  silent_success: "bg-red-50 text-danger border-danger",
  hung: "bg-amber-50 text-amber-700 border-amber-500",
  not_triggered: "bg-slate-50 text-slate-500 border-line",
};

/** Unhandled outcomes first: those are the ones worth a developer's attention. */
const VERDICT_ORDER: ErrorHandlingVerdict[] = [
  "unhandled_crash",
  "silent_success",
  "hung",
  "handled",
  "not_triggered",
];

export function FuzzPanel({
  workflowId,
  initialRun,
}: {
  workflowId: string;
  initialRun: FuzzRun | null;
}) {
  const [run, setRun] = useState<FuzzRun | null>(initialRun);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const cases = useMemo(() => {
    if (!run) return [];
    const ranked = [...run.cases].sort(
      (a, b) => VERDICT_ORDER.indexOf(a.verdict) - VERDICT_ORDER.indexOf(b.verdict)
    );
    return showAll ? ranked : ranked.filter((item) => item.verdict !== "not_triggered");
  }, [run, showAll]);

  async function runCampaign() {
    setBusy(true);
    setError(null);
    try {
      setRun(await api.runFuzz(workflowId, true));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fuzz campaign failed");
    } finally {
      setBusy(false);
    }
  }

  const unmeasured = run !== null && run.exercised_cases === 0;

  return (
    <div className="grid gap-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <Stat
            label="Robustness"
            value={run && !unmeasured ? `${run.robustness_score}%` : "—"}
            tone={
              run && !unmeasured
                ? run.robustness_score >= 70
                  ? "text-good"
                  : "text-danger"
                : "text-slate-500"
            }
          />
          <Stat label="Cases Run" value={run ? run.total_cases.toString() : "0"} />
          <Stat label="Exercised" value={run ? run.exercised_cases.toString() : "0"} />
          <Stat
            label="Unhandled"
            value={run ? (run.unhandled_crash + run.silent_success + run.hung).toString() : "0"}
            tone={run && run.unhandled_crash + run.silent_success + run.hung ? "text-danger" : "text-good"}
          />
          <Stat label="Last Run" value={run ? formatDate(run.created_at) : "Never"} />
        </div>
        <button
          type="button"
          onClick={runCampaign}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-md bg-ink px-3 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          <Zap size={16} />
          {busy ? "Fuzzing..." : "Run Fuzz Campaign"}
        </button>
      </div>

      {error && <div className="border border-danger bg-red-50 p-3 text-sm text-danger">{error}</div>}

      {!run && (
        <p className="border border-line bg-panel p-4 text-sm text-slate-600">
          No fuzz campaign has run yet. Reliability currently reflects declared error handling only.
          A campaign injects dependency failures and malformed input, then records what the workflow
          actually did with each one.
        </p>
      )}

      {unmeasured && (
        <div className="flex gap-2 border border-amber-500 bg-amber-50 p-3 text-sm text-amber-800">
          <ShieldAlert size={16} className="mt-0.5 shrink-0" />
          <span>
            Nothing was exercised, so robustness is <strong>unmeasured rather than proven</strong>.
            This usually means the graph is disconnected or has no external dependencies to fail.
            The score is not blended into reliability.
          </span>
        </div>
      )}

      {run && !unmeasured && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {VERDICT_ORDER.map((verdict) => (
              <span key={verdict} className={`border px-2 py-1 ${VERDICT_TONE[verdict]}`}>
                {VERDICT_LABEL[verdict]}: {countFor(run, verdict)}
              </span>
            ))}
            <span className="text-slate-500">
              seed {run.seed} · {run.ai_metadata?.ai_status === "used" ? `${run.ai_provider}/${run.ai_model}` : "deterministic"}
            </span>
          </div>

          <div className="overflow-x-auto border border-line">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="bg-panel text-xs uppercase text-slate-500">
                <tr>
                  <th className="p-3">Case</th>
                  <th className="p-3">Strategy</th>
                  <th className="p-3">Verdict</th>
                  <th className="p-3">What happened</th>
                </tr>
              </thead>
              <tbody>
                {cases.map((item) => (
                  <CaseRow key={item.id} item={item} />
                ))}
              </tbody>
            </table>
          </div>

          <button
            type="button"
            onClick={() => setShowAll((current) => !current)}
            className="justify-self-start text-sm text-slate-600 underline"
          >
            {showAll ? "Hide cases that never fired" : `Show all ${run.total_cases} cases`}
          </button>
        </>
      )}

      {run && run.suggestions.length > 0 && (
        <div className="grid gap-2 border border-amber-500 bg-amber-50 p-4 text-sm text-amber-900">
          <div className="flex items-center gap-2 font-medium">
            <Lightbulb size={16} /> Suggested fix for this workflow
          </div>
          {run.suggestions.map((suggestion) => (
            <p key={suggestion}>{suggestion}</p>
          ))}
          <p className="text-xs text-amber-700">
            Advice only - this does not change any score.
          </p>
        </div>
      )}

      {run && run.limitations.length > 0 && (
        <ul className="grid gap-1 border border-line bg-panel p-4 text-xs text-slate-600">
          {run.limitations.map((limitation) => (
            <li key={limitation}>• {limitation}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CaseRow({ item }: { item: FuzzCase }) {
  return (
    <tr className="border-t border-line align-top">
      <td className="p-3">
        <div className="font-medium text-ink">{item.name}</div>
        {item.generated_by === "AI" && (
          <span className="mt-1 inline-flex items-center gap-1 text-xs text-slate-500">
            <Bug size={12} /> AI-generated
          </span>
        )}
      </td>
      <td className="p-3 text-xs uppercase text-slate-500">{item.strategy.replace(/_/g, " ")}</td>
      <td className="p-3">
        <span className={`border px-2 py-1 text-xs ${VERDICT_TONE[item.verdict]}`}>
          {VERDICT_LABEL[item.verdict]}
        </span>
      </td>
      <td className="p-3 text-slate-600">
        <div>{item.observed}</div>
        {item.evidence.length > 0 && (
          <div className="mt-1 text-xs text-slate-500">{item.evidence[item.evidence.length - 1]}</div>
        )}
      </td>
    </tr>
  );
}

function countFor(run: FuzzRun, verdict: ErrorHandlingVerdict): number {
  switch (verdict) {
    case "handled":
      return run.handled;
    case "unhandled_crash":
      return run.unhandled_crash;
    case "silent_success":
      return run.silent_success;
    case "hung":
      return run.hung;
    default:
      return run.not_triggered;
  }
}

function Stat({ label, value, tone = "text-ink" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="border border-line bg-white p-3">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${tone}`}>{value}</div>
    </div>
  );
}
