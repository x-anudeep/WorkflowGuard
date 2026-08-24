"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Calculator, CheckCircle2, FlaskConical, Play, RefreshCw, ShieldCheck } from "lucide-react";

import { api } from "@/lib/api";

export function WorkflowAssessmentActions({
  workflowId,
  hasEvaluation,
  hasTests,
}: {
  workflowId: string;
  hasEvaluation: boolean;
  hasTests: boolean;
}) {
  const router = useRouter();
  const [localHasEvaluation, setLocalHasEvaluation] = useState(hasEvaluation);
  const [localHasTests, setLocalHasTests] = useState(hasTests);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refreshGate() {
    await api.checkQualityGate(workflowId).catch(() => null);
  }

  async function runStep(name: string, action: () => Promise<unknown>, done: string, onDone?: () => void) {
    setBusy(name);
    setError(null);
    setMessage(null);
    try {
      await action();
      onDone?.();
      await refreshGate();
      setMessage(done);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : `${name} failed`);
    } finally {
      setBusy(null);
    }
  }

  async function runFullAssessment() {
    setBusy("full");
    setError(null);
    setMessage("Running evaluation...");
    try {
      await api.evaluate(workflowId, true);
      setLocalHasEvaluation(true);
      setMessage("Generating tests...");
      await api.generateTests(workflowId, true, !localHasTests);
      setLocalHasTests(true);
      setMessage("Running tests...");
      await api.runTests(workflowId);
      setMessage("Estimating cost...");
      await api.estimateCost(workflowId, {});
      setMessage("Checking quality gate...");
      await refreshGate();
      setMessage("Assessment complete. Refreshing results...");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Assessment failed");
    } finally {
      setBusy(null);
    }
  }

  const disabled = busy !== null;
  const nextStep = !localHasEvaluation
    ? "Next: run evaluation to compare the workflow against the prompt."
    : !localHasTests
      ? "Next: generate tests, then run them to produce coverage and traces."
      : "Next: run tests, estimate cost, then check the quality gate.";

  return (
    <div className="border border-line bg-panel p-4">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <div className="text-sm font-semibold">Assessment actions</div>
          <p className="mt-1 text-sm text-slate-600">
            Structural validation only proves the graph is well formed. Run the remaining checks to prove it matches the requirement, is safe, is tested, and has a cost estimate.
          </p>
          <div className="mt-2 text-sm font-medium text-ink">{nextStep}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={runFullAssessment} disabled={disabled} className="inline-flex items-center gap-2 rounded-md bg-ink px-3 py-2 text-sm font-medium text-white disabled:opacity-60">
            <Play size={16} />
            {busy === "full" ? "Running..." : "Run full assessment"}
          </button>
          <ActionButton icon={<ShieldCheck size={16} />} label={localHasEvaluation ? "Re-evaluate" : "Evaluate"} disabled={disabled} onClick={() => runStep("evaluate", () => api.evaluate(workflowId, true), "Evaluation complete. Generate tests next.", () => setLocalHasEvaluation(true))} />
          <ActionButton icon={<FlaskConical size={16} />} label={localHasTests ? "Regenerate tests" : "Generate tests"} disabled={disabled} onClick={() => runStep("tests", () => api.generateTests(workflowId, true, false), "Tests generated. You can run them now.", () => setLocalHasTests(true))} />
          <ActionButton icon={<CheckCircle2 size={16} />} label="Run tests" disabled={disabled || !localHasTests} onClick={() => runStep("run-tests", () => api.runTests(workflowId), "Tests executed. Coverage and failures are refreshed.")} />
          <ActionButton icon={<Calculator size={16} />} label="Estimate cost" disabled={disabled} onClick={() => runStep("cost", () => api.estimateCost(workflowId, {}), "Cost estimate updated.")} />
          <ActionButton icon={<RefreshCw size={16} />} label="Check gate" disabled={disabled} onClick={() => runStep("gate", () => api.checkQualityGate(workflowId), "Quality gate checked.")} />
        </div>
      </div>
      {message && <div className="mt-3 border border-line bg-white p-3 text-sm text-slate-700">{message}</div>}
      {error && <div className="mt-3 border border-danger bg-red-50 p-3 text-sm text-danger">{error}</div>}
    </div>
  );
}

function ActionButton({
  icon,
  label,
  disabled,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} className="inline-flex items-center gap-2 rounded-md border border-line bg-white px-3 py-2 text-sm font-medium disabled:opacity-50">
      {icon}
      {label}
    </button>
  );
}
