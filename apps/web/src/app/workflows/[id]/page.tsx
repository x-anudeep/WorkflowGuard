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
  const [workflow, validation, evaluations, tests, testRuns, cost, comparison, repairs] = await Promise.all([
    api.workflow(id),
    api.validation(id),
    api.evaluations(id),
    api.tests(id),
    api.testRuns(id),
    api.cost(id),
    api.compareVersions(id),
    api.repairs(id),
  ]);

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
          <div className="grid gap-4 md:grid-cols-3">
            <Stat label="Nodes" value={workflow.canonical.nodes.length.toString()} />
            <Stat label="Edges" value={workflow.canonical.edges.length.toString()} />
            <Stat label="Current version" value={workflow.current_version_id ?? "Unknown"} />
          </div>
          {workflow.source_prompt && (
            <div className="mt-4 border border-line bg-panel p-4 text-sm text-slate-700">{workflow.source_prompt}</div>
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

        <Panel title="Source">
          <pre className="max-h-[520px] overflow-auto border border-line bg-panel p-4 text-xs">
            {JSON.stringify(workflow.canonical, null, 2)}
          </pre>
        </Panel>

        <Panel title="Versions">
          <div className="text-sm text-slate-700">Version 1 · {workflow.current_version_id}</div>
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
