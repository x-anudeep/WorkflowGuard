import Link from "next/link";

import { CostPanel } from "@/components/CostPanel";
import { EvaluationPanel } from "@/components/EvaluationPanel";
import { RepairPanel } from "@/components/RepairPanel";
import { TestsPanel } from "@/components/TestsPanel";
import { VersionComparePanel } from "@/components/VersionComparePanel";
import { WorkflowGraph } from "@/components/WorkflowGraph";
import { api } from "@/lib/api";
import { formatDate, formatSourceFormat, scoreTone } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function WorkflowDetailPage({ params }: { params: { id: string } }) {
  const { id } = params;
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
  const attention = [
    ...(validation?.findings ?? []).filter((finding) => finding.severity === "CRITICAL" || finding.severity === "ERROR").slice(0, 3),
    ...(latestEvaluation?.findings ?? []).filter((finding) => finding.severity === "CRITICAL" || finding.severity === "ERROR").slice(0, 3),
  ].slice(0, 5);

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
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <StatusCard label="Valid" value={validation && validation.findings.every((finding) => finding.severity !== "ERROR" && finding.severity !== "CRITICAL") ? "Yes" : "Needs work"} />
            <StatusCard label="Matches requirement" value={dimensions.prompt_alignment ? `${dimensions.prompt_alignment.toFixed(0)}/100` : "Not evaluated"} />
            <StatusCard label="Secure" value={dimensions.security ? `${dimensions.security.toFixed(0)}/100` : "Not evaluated"} />
            <StatusCard label="Reliable" value={dimensions.reliability ? `${dimensions.reliability.toFixed(0)}/100` : "Not evaluated"} />
            <StatusCard label="Tests" value={`${testRuns.passed}/${testRuns.total_tests} passing`} />
            <StatusCard label="Coverage" value={`${testRuns.latest_coverage.toFixed(0)}%`} />
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
          {attention.length > 0 && (
            <div className="mt-4 border border-danger bg-red-50 p-4">
              <div className="text-sm font-semibold text-danger">Needs attention</div>
              <div className="mt-2 grid gap-2">
                {attention.map((finding) => (
                  <div key={`${finding.rule_id}-${finding.message}`} className="text-sm text-slate-800">
                    <span className="font-semibold">{finding.severity}</span> · {finding.title}
                  </div>
                ))}
              </div>
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

function StatusCard({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "neutral" | "good" | "bad" }) {
  const toneClass = tone === "good" ? "text-success" : tone === "bad" ? "text-danger" : "text-ink";
  return (
    <div className="border border-line bg-white p-4">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className={`mt-2 text-lg font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}
