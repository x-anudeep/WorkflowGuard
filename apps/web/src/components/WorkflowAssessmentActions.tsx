"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Calculator, CheckCircle2, FlaskConical, Play, RefreshCw, ShieldCheck } from "lucide-react";

import { api } from "@/lib/api";

export function WorkflowAssessmentActions({
  workflowId,
  hasEvaluation,
  hasTests,
  hasTestRuns,
  hasUsefulCost,
  gateStatus,
}: {
  workflowId: string;
  hasEvaluation: boolean;
  hasTests: boolean;
  hasTestRuns: boolean;
  hasUsefulCost: boolean;
  gateStatus?: string | null;
}) {
  const router = useRouter();
  const [localHasEvaluation, setLocalHasEvaluation] = useState(hasEvaluation);
  const [localHasTests, setLocalHasTests] = useState(hasTests);
  const [localHasTestRuns, setLocalHasTestRuns] = useState(hasTestRuns);
  const [localHasUsefulCost, setLocalHasUsefulCost] = useState(hasUsefulCost);
  const [localGateStatus, setLocalGateStatus] = useState(gateStatus ?? null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refreshGate() {
    const gate = await api.checkQualityGate(workflowId).catch(() => null);
    if (gate) setLocalGateStatus(gate.status);
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
      setLocalHasTestRuns(true);
      setMessage("Estimating cost...");
      await api.estimateCost(workflowId, {});
      setLocalHasUsefulCost(true);
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

  async function runNext() {
    if (!localHasEvaluation) {
      await runStep("next", () => api.evaluate(workflowId, true), "Evaluation complete. Generate tests next.", () => setLocalHasEvaluation(true));
      return;
    }
    if (!localHasTests) {
      await runStep("next", () => api.generateTests(workflowId, true, false), "Tests generated. Run tests next.", () => setLocalHasTests(true));
      return;
    }
    if (!localHasTestRuns) {
      await runStep("next", () => api.runTests(workflowId), "Tests executed. Estimate cost next.", () => setLocalHasTestRuns(true));
      return;
    }
    if (!localHasUsefulCost) {
      await runStep("next", () => api.estimateCost(workflowId, {}), "Cost estimate updated. Check the gate next.", () => setLocalHasUsefulCost(true));
      return;
    }
    await runStep("next", () => api.checkQualityGate(workflowId), "Quality gate checked.");
  }

  const disabled = busy !== null;
  const nextStep = nextStepCopy(localHasEvaluation, localHasTests, localHasTestRuns, localHasUsefulCost, localGateStatus);
  const nextLabel = nextButtonLabel(localHasEvaluation, localHasTests, localHasTestRuns, localHasUsefulCost);

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
          <button type="button" onClick={runNext} disabled={disabled} className="inline-flex items-center gap-2 rounded-md bg-ink px-3 py-2 text-sm font-medium text-white disabled:opacity-60">
            <Play size={16} />
            {busy === "next" ? "Running..." : nextLabel}
          </button>
          <ActionButton icon={<Play size={16} />} label={busy === "full" ? "Running all..." : "Run full assessment"} disabled={disabled} onClick={runFullAssessment} />
          <ActionButton icon={<ShieldCheck size={16} />} label={localHasEvaluation ? "Re-evaluate" : "Evaluate"} disabled={disabled} onClick={() => runStep("evaluate", () => api.evaluate(workflowId, true), "Evaluation complete. Generate tests next.", () => setLocalHasEvaluation(true))} />
          <ActionButton icon={<FlaskConical size={16} />} label={localHasTests ? "Regenerate tests" : "Generate tests"} disabled={disabled} onClick={() => runStep("tests", () => api.generateTests(workflowId, true, false), "Tests generated. You can run them now.", () => setLocalHasTests(true))} />
          <ActionButton icon={<CheckCircle2 size={16} />} label="Run tests" disabled={disabled || !localHasTests} onClick={() => runStep("run-tests", () => api.runTests(workflowId), "Tests executed. Coverage and failures are refreshed.", () => setLocalHasTestRuns(true))} />
          <ActionButton icon={<Calculator size={16} />} label="Estimate cost" disabled={disabled} onClick={() => runStep("cost", () => api.estimateCost(workflowId, {}), "Cost estimate updated.", () => setLocalHasUsefulCost(true))} />
          <ActionButton icon={<RefreshCw size={16} />} label="Check gate" disabled={disabled} onClick={() => runStep("gate", () => api.checkQualityGate(workflowId), "Quality gate checked.")} />
        </div>
      </div>
      {message && <div className="mt-3 border border-line bg-white p-3 text-sm text-slate-700">{message}</div>}
      {error && <div className="mt-3 border border-danger bg-red-50 p-3 text-sm text-danger">{error}</div>}
    </div>
  );
}

function nextStepCopy(hasEvaluation: boolean, hasTests: boolean, hasTestRuns: boolean, hasUsefulCost: boolean, gateStatus: string | null): string {
  if (!hasEvaluation) return "Next: run evaluation to compare the workflow against the prompt.";
  if (!hasTests) return "Next: generate tests so WorkflowGuard can check paths, failures, and edge cases.";
  if (!hasTestRuns) return "Next: run the generated tests. Existing tests are not evidence until they execute.";
  if (!hasUsefulCost) return "Next: run a cost scenario so the estimate is based on detected cost drivers.";
  if (gateStatus !== "PASS") return "Next: check the quality gate after the latest evaluation, tests, and cost estimate.";
  return "All core checks have run. Review findings, reports, and repair proposals before trusting the workflow.";
}

function nextButtonLabel(hasEvaluation: boolean, hasTests: boolean, hasTestRuns: boolean, hasUsefulCost: boolean): string {
  if (!hasEvaluation) return "Run evaluation";
  if (!hasTests) return "Generate tests";
  if (!hasTestRuns) return "Run tests";
  if (!hasUsefulCost) return "Estimate cost";
  return "Check gate";
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
