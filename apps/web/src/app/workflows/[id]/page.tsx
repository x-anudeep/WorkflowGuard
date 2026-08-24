import Link from "next/link";
import { notFound } from "next/navigation";

import { CostPanel } from "@/components/CostPanel";
import { EvaluationPanel } from "@/components/EvaluationPanel";
import { RepairPanel } from "@/components/RepairPanel";
import { TestsPanel } from "@/components/TestsPanel";
import { VersionComparePanel } from "@/components/VersionComparePanel";
import { WorkflowAssessmentActions } from "@/components/WorkflowAssessmentActions";
import { WorkflowGraph } from "@/components/WorkflowGraph";
import { api } from "@/lib/api";
import { formatDate, formatSourceFormat, scoreTone } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function WorkflowDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) {
    notFound();
  }
  const [workflow, validation, evaluations, tests, testRuns, cost, comparison, repairs, qualityGate, history, versions] = await Promise.all([
    api.workflow(id),
    api.validation(id),
    api.evaluations(id),
    api.tests(id),
    api.testRuns(id),
    api.cost(id),
    api.compareVersions(id),
    api.repairs(id),
    api.qualityGate(id).catch(() => null),
    api.history(id).catch(() => []),
    api.versions(id).catch(() => []),
  ]);
  const latestEvaluation = evaluations[0];
  const dimensions = Object.fromEntries((latestEvaluation?.dimension_scores ?? []).map((score) => [score.dimension, score.score]));
  const securityFindings = latestEvaluation?.findings.filter((finding) => finding.dimension === "security") ?? [];
  const reliabilityFindings = latestEvaluation?.findings.filter((finding) => finding.dimension === "reliability") ?? [];
  const evaluationAttention = (latestEvaluation?.findings ?? [])
    .filter((finding) => finding.severity === "CRITICAL" || finding.severity === "ERROR")
    .slice(0, 4);
  const validationAttention = (validation?.findings ?? [])
    .filter((finding) => finding.severity === "CRITICAL" || finding.severity === "ERROR")
    .slice(0, 3);
  const missingEvidence = buildMissingEvidence({
    hasEvaluation: Boolean(latestEvaluation),
    hasTests: tests.length > 0,
    hasTestRuns: testRuns.runs.length > 0,
    hasUsefulCost: cost.line_items.length > 0,
    promptAlignment: dimensions.prompt_alignment,
    qualityGateStatus: qualityGate?.status,
  });

  return (
    <section className="px-5 py-7 lg:px-8">
      <Link href="/workflows" className="text-sm text-slate-600 hover:text-accent">Back to workflows</Link>
      <div className="mt-4 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{workflow.name}</h1>
          <p className="mt-1 text-sm text-slate-600">
            {formatSourceFormat(workflow.source_format)} · {workflow.source_type.replace("_", " ")} · {formatDate(workflow.created_at)}
          </p>
        </div>
        <div className={`text-3xl font-semibold ${scoreTone(workflow.structural_quality_score)}`}>
          {workflow.structural_quality_score ?? "Pending"}
          <span className="ml-2 text-sm font-medium text-slate-500">Structural Quality Score</span>
        </div>
      </div>

      <div className="mt-7 grid gap-8">
        <Panel title="Overview">
          <WorkflowAssessmentActions workflowId={workflow.id} hasEvaluation={Boolean(latestEvaluation)} hasTests={tests.length > 0} />
          <div className="mt-4 border border-line bg-white p-4">
            <div className="text-sm font-semibold">What the data means</div>
            <div className="mt-3 grid gap-3 text-sm text-slate-700 lg:grid-cols-2">
              <Explanation
                title="Why Structural Quality is 100"
                body="The workflow graph itself is valid: node IDs are unique, edges point to real nodes, there is a start path and terminal path, and the graph is connected. This does not prove the workflow satisfies the prompt."
              />
              <Explanation
                title="Why the Quality Gate fails"
                body={qualityGate?.status === "PASS" ? "The latest stored checks meet the configured thresholds." : "The gate requires semantic evaluation, security/reliability scores, tests, coverage, and critical-test results. Missing evidence counts as failure because an untested or unevaluated workflow should not be trusted."}
              />
              {missingEvidence.map((item) => (
                <Explanation key={item.title} title={item.title} body={item.body} />
              ))}
              {latestEvaluation && latestEvaluation.findings.length === 0 && (
                <Explanation title="No semantic findings" body="The latest semantic evaluation did not find prompt-alignment, security, reliability, or maintainability issues. Re-run tests and gates after every workflow version change." />
              )}
            </div>
          </div>
          <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <StatusCard label="Valid" value={validation && validation.findings.every((finding) => finding.severity !== "ERROR" && finding.severity !== "CRITICAL") ? "Yes" : "Needs work"} tone={validationAttention.length ? "bad" : "good"} />
            <StatusCard label="Matches requirement" value={scoreValue(dimensions.prompt_alignment)} tone={scoreCardTone(dimensions.prompt_alignment)} />
            <StatusCard label="Secure" value={scoreValue(dimensions.security)} tone={scoreCardTone(dimensions.security)} />
            <StatusCard label="Reliable" value={scoreValue(dimensions.reliability)} tone={scoreCardTone(dimensions.reliability)} />
            <StatusCard label="Tests" value={`${testRuns.passed}/${testRuns.total_tests} passing`} tone={testRuns.total_tests === 0 || testRuns.failed + testRuns.error > 0 ? "bad" : "good"} />
            <StatusCard label="Coverage" value={`${testRuns.latest_coverage.toFixed(0)}%`} tone={testRuns.latest_coverage >= 85 ? "good" : "bad"} />
            <StatusCard label="Cost" value={`$${cost.monthly_cost.toFixed(2)}/mo`} />
            <StatusCard label="Quality gate" value={qualityGate?.status ?? "Not checked"} tone={qualityGate?.status === "PASS" ? "good" : "bad"} />
          </div>
          <div className="mt-4 grid gap-4 md:grid-cols-3">
            <Stat label="Nodes" value={workflow.canonical.nodes.length.toString()} />
            <Stat label="Edges" value={workflow.canonical.edges.length.toString()} />
            <Stat label="Current version" value={workflow.current_version_id ?? "Unknown"} />
          </div>
          {workflow.source_prompt && (
            <div className="mt-4 border border-line bg-panel p-4 text-sm text-slate-700">{workflow.source_prompt}</div>
          )}
          {(validationAttention.length > 0 || evaluationAttention.length > 0) && (
            <div className="mt-4 border border-danger bg-red-50 p-4">
              <div className="text-sm font-semibold text-danger">Needs attention</div>
              <div className="mt-3 grid gap-3">
                {validationAttention.map((finding) => (
                  <ValidationAttentionCard key={`${finding.rule_id}-${finding.message}`} finding={finding} />
                ))}
                {evaluationAttention.map((finding) => (
                  <EvaluationAttentionCard key={`${finding.rule_id}-${finding.message}`} finding={finding} />
                ))}
              </div>
            </div>
          )}
          {latestEvaluation && (securityFindings.length > 0 || reliabilityFindings.length > 0) && (
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {reliabilityFindings.slice(0, 3).map((finding) => (
                <FindingSummary key={`${finding.rule_id}-${finding.message}`} title={finding.title} severity={finding.severity} message={finding.message} />
              ))}
              {securityFindings.slice(0, 3).map((finding) => (
                <FindingSummary key={`${finding.rule_id}-${finding.message}`} title={finding.title} severity={finding.severity} message={finding.message} />
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Graph">
          <WorkflowGraph workflow={workflow} />
        </Panel>

        <Panel title="Validation">
          <div className="grid gap-3">
            {(validation?.findings ?? []).map((finding) => (
              <div key={`${finding.rule_id}-${finding.node_id}-${finding.edge_id}-${finding.message}`} className="border border-line p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-sm bg-panel px-2 py-1 text-xs font-semibold">{finding.severity}</span>
                  <span className="text-sm font-semibold">{finding.rule_id}</span>
                  <span className="text-sm">{finding.title}</span>
                </div>
                <p className="mt-2 text-sm text-slate-700">{finding.message}</p>
                {finding.remediation && <p className="mt-2 text-sm text-slate-500">{finding.remediation}</p>}
              </div>
            ))}
            {validation && validation.findings.length === 0 && (
              <div className="border border-line bg-panel p-4 text-sm text-slate-700">No structural findings detected.</div>
            )}
          </div>
        </Panel>

        <Panel title="AI Evaluation">
          <EvaluationPanel workflowId={workflow.id} initialEvaluations={evaluations} />
        </Panel>

        <Panel title="Security">
          <div className="grid gap-3">
            {securityFindings.map((finding) => (
              <div key={`${finding.rule_id}-${finding.message}`} className="border border-line p-4">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="rounded-sm bg-panel px-2 py-1 text-xs font-semibold">{finding.severity}</span>
                  <span className="font-semibold">{finding.title}</span>
                  {finding.node_id && <span className="text-slate-500">Node {finding.node_id}</span>}
                </div>
                <p className="mt-2 text-sm text-slate-700">{finding.message}</p>
                {finding.remediation && <p className="mt-2 text-sm text-slate-500">{finding.remediation}</p>}
              </div>
            ))}
            {securityFindings.length === 0 && (
              <div className="border border-line bg-panel p-4 text-sm text-slate-700">No security findings recorded in the latest evaluation.</div>
            )}
          </div>
        </Panel>

        <Panel title="Tests">
          <TestsPanel workflowId={workflow.id} initialTests={tests} initialRuns={testRuns} />
        </Panel>

        <Panel title="Cost">
          <CostPanel workflowId={workflow.id} initialEstimate={cost} />
        </Panel>

        <Panel title="Versions / Compare">
          <VersionComparePanel workflow={workflow} comparison={comparison} />
        </Panel>

        <Panel title="Repair">
          <RepairPanel workflowId={workflow.id} initialRepairs={repairs} />
        </Panel>

        <Panel title="Quality Gate">
          {qualityGate ? (
            <div className="border border-line bg-white p-4">
              <div className={`text-lg font-semibold ${qualityGate.status === "PASS" ? "text-success" : "text-danger"}`}>
                {qualityGate.status} · {qualityGate.score.toFixed(1)}
              </div>
              <div className="mt-4 grid gap-2">
                {qualityGate.reasons.map((reason) => (
                  <div key={reason.rule_id} className="flex flex-col gap-1 border-t border-line pt-3 text-sm md:flex-row md:items-center md:justify-between">
                    <span>{reason.passed ? "PASS" : "FAIL"} · {reason.title}</span>
                    <span className="text-slate-600">{reason.actual} expected {reason.expected}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="border border-line bg-panel p-4 text-sm text-slate-700">Quality gate has not been checked yet.</div>
          )}
        </Panel>

        <Panel title="Source">
          <pre className="max-h-[520px] overflow-auto border border-line bg-panel p-4 text-xs">
            {JSON.stringify(workflow.canonical, null, 2)}
          </pre>
        </Panel>

        <Panel title="Versions">
          <div className="grid gap-2">
            {versions.map((version) => (
              <div key={version.id} className="flex flex-col gap-1 border border-line bg-white p-3 text-sm md:flex-row md:items-center md:justify-between">
                <span className="font-medium">Version {version.version_number}</span>
                <span className="break-all text-slate-600">{version.id}</span>
                <span className="text-slate-500">{formatDate(version.created_at)}</span>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Reports">
          <div className="flex flex-wrap gap-3">
            <a href={`${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api"}/workflows/${workflow.id}/report?format=json`} className="rounded-md border border-line px-3 py-2 text-sm font-medium hover:border-slate-400">JSON report</a>
            <a href={`${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api"}/workflows/${workflow.id}/report?format=markdown`} className="rounded-md border border-line px-3 py-2 text-sm font-medium hover:border-slate-400">Markdown report</a>
            <a href={`${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api"}/workflows/${workflow.id}/report?format=html`} className="rounded-md border border-line px-3 py-2 text-sm font-medium hover:border-slate-400">HTML report</a>
          </div>
        </Panel>

        <Panel title="History">
          <div className="grid gap-2">
            {history.map((event) => (
              <div key={event.id} className="border border-line bg-white p-3 text-sm">
                <div className="flex flex-col gap-1 md:flex-row md:items-center md:justify-between">
                  <span className="font-medium">{event.event_type.replaceAll("_", " ")}</span>
                  <span className="text-slate-500">{formatDate(event.created_at)}</span>
                </div>
                <p className="mt-1 text-slate-700">{event.message}</p>
              </div>
            ))}
            {history.length === 0 && (
              <div className="border border-line bg-panel p-4 text-sm text-slate-700">No audit events recorded yet.</div>
            )}
          </div>
        </Panel>
      </div>
    </section>
  );
}

function isUuid(value: string | undefined): value is string {
  return Boolean(value && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value));
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-3 text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-line bg-white p-4">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className="mt-2 break-all text-lg font-semibold">{value}</div>
    </div>
  );
}

function StatusCard({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "neutral" | "good" | "bad" | "warn" }) {
  const toneClass = tone === "good" ? "text-success" : tone === "bad" ? "text-danger" : tone === "warn" ? "text-warn" : "text-ink";
  return (
    <div className="border border-line bg-white p-4">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className={`mt-2 text-lg font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}

function scoreValue(score: unknown): string {
  return typeof score === "number" ? `${score.toFixed(0)}/100` : "Not evaluated";
}

function scoreCardTone(score: unknown): "neutral" | "good" | "warn" | "bad" {
  if (typeof score !== "number") return "bad";
  if (score >= 85) return "good";
  if (score >= 65) return "warn";
  return "bad";
}

function Explanation({ title, body }: { title: string; body: string }) {
  return (
    <div className="border border-line bg-panel p-3">
      <div className="font-semibold text-ink">{title}</div>
      <p className="mt-1 leading-6">{body}</p>
    </div>
  );
}

function FindingSummary({ title, severity, message }: { title: string; severity: string; message: string }) {
  return (
    <div className="border border-line bg-white p-4">
      <div className="flex items-center gap-2 text-sm">
        <span className="rounded-sm bg-panel px-2 py-1 text-xs font-semibold">{severity}</span>
        <span className="font-semibold">{title}</span>
      </div>
      <p className="mt-2 text-sm text-slate-700">{message}</p>
    </div>
  );
}

function ValidationAttentionCard({ finding }: { finding: { severity: string; rule_id: string; title: string; message: string; remediation?: string | null; node_id?: string | null; edge_id?: string | null } }) {
  return (
    <div className="border border-danger bg-white p-4 text-sm">
      <div className="font-semibold text-danger">{finding.severity} · {finding.rule_id} · {finding.title}</div>
      <p className="mt-2 text-slate-700">{finding.message}</p>
      {(finding.node_id || finding.edge_id) && <p className="mt-2 text-slate-600">Location: {finding.node_id ?? finding.edge_id}</p>}
      {finding.remediation && <p className="mt-2 text-slate-700">Fix: {finding.remediation}</p>}
    </div>
  );
}

function EvaluationAttentionCard({
  finding,
}: {
  finding: {
    severity: string;
    rule_id: string;
    dimension: string;
    title: string;
    message: string;
    expected: string;
    found: string;
    why_it_matters: string;
    remediation?: string | null;
    node_id?: string | null;
    path?: string[];
  };
}) {
  return (
    <details className="border border-danger bg-white p-4 text-sm" open>
      <summary className="cursor-pointer font-semibold text-danger">
        {finding.severity} · {finding.rule_id} · {finding.title}
      </summary>
      <div className="mt-3 grid gap-2 text-slate-700 md:grid-cols-2">
        <InfoField label="Problem" value={finding.message} />
        <InfoField label="Expected" value={finding.expected} />
        <InfoField label="Found" value={finding.found} />
        <InfoField label="Why it matters" value={finding.why_it_matters} />
        {finding.node_id && <InfoField label="Node" value={finding.node_id} />}
        {finding.path && finding.path.length > 0 && <InfoField label="Path" value={finding.path.join(" -> ")} />}
        {finding.remediation && <InfoField label="Fix" value={finding.remediation} />}
      </div>
    </details>
  );
}

function InfoField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 leading-6">{value}</div>
    </div>
  );
}

function buildMissingEvidence({
  hasEvaluation,
  hasTests,
  hasTestRuns,
  hasUsefulCost,
  promptAlignment,
  qualityGateStatus,
}: {
  hasEvaluation: boolean;
  hasTests: boolean;
  hasTestRuns: boolean;
  hasUsefulCost: boolean;
  promptAlignment: unknown;
  qualityGateStatus?: string;
}) {
  const items: Array<{ title: string; body: string }> = [];
  if (!hasEvaluation) {
    items.push({
      title: "Prompt match is unknown",
      body: "No evaluation has checked whether the workflow actually does what the original requirement asked. A valid graph can still omit required systems, approvals, ordering, or business rules.",
    });
  }
  if (!hasTests) {
    items.push({
      title: "No workflow tests exist",
      body: "There are no generated or manual tests yet. WorkflowGuard cannot prove branch behavior, failure handling, edge cases, or requirement coverage until tests are generated.",
    });
  } else if (!hasTestRuns) {
    items.push({
      title: "Tests have not run",
      body: "Tests exist but have no execution trace yet, so pass rate and coverage are not meaningful. Run tests to see branch decisions and assertion failures.",
    });
  }
  if (!hasUsefulCost) {
    items.push({
      title: "Cost is only a baseline",
      body: "A $0.00 monthly estimate usually means this workflow has no detected billable LLM/API/storage/email cost drivers or only tiny rounded costs. Add provider/model/API metadata or run a scenario for a more useful estimate.",
    });
  }
  if (typeof promptAlignment === "number" && promptAlignment < 90) {
    items.push({
      title: "Prompt alignment is below the gate",
      body: `The latest evaluation scored prompt alignment at ${promptAlignment.toFixed(0)}/100. Open the attention cards or AI Evaluation section to see which requested behaviors are missing or mismatched.`,
    });
  }
  if (qualityGateStatus === "FAIL") {
    items.push({
      title: "This workflow should not be trusted yet",
      body: "The gate is deliberately strict: if required semantic checks, tests, coverage, or critical findings are missing or failing, WorkflowGuard blocks trust even when the graph is structurally clean.",
    });
  }
  return items;
}
