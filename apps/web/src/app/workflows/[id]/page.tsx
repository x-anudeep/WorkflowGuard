import Link from "next/link";
import { notFound } from "next/navigation";

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
  const [workflow, evaluations, tests, testRuns, cost, qualityGate] = await Promise.all([
    api.workflow(id),
    api.evaluations(id).catch(() => []),
    api.tests(id).catch(() => []),
    api.testRuns(id),
    api.cost(id),
    api.qualityGate(id).catch(() => null),
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
        <div className="flex flex-col items-start gap-3 lg:items-end">
          <div className={`text-3xl font-semibold ${scoreTone(workflow.structural_quality_score)}`}>
            {workflow.structural_quality_score ?? "Pending"}
            <span className="ml-2 text-sm font-medium text-slate-500">Structural Quality Score</span>
          </div>
          <Link
            href={`/workflows/${workflow.id}/results`}
            className="inline-flex items-center rounded-md bg-ink px-3 py-2 text-sm font-medium text-white"
          >
            View scores &amp; tests
          </Link>
        </div>
      </div>

      <div className="mt-7 grid gap-8">
        <WorkflowAssessmentActions
          workflowId={workflow.id}
          hasEvaluation={evaluations.length > 0}
          hasTests={tests.length > 0}
          hasTestRuns={testRuns.runs.length > 0}
          hasUsefulCost={cost.line_items.length > 0}
          gateStatus={qualityGate?.status}
        />

        <section>
          <h2 className="mb-3 text-base font-semibold">Graph</h2>
          <WorkflowGraph workflow={workflow} />
        </section>

        <div className="grid gap-4 md:grid-cols-3">
          <Stat label="Nodes" value={workflow.canonical.nodes.length.toString()} />
          <Stat label="Edges" value={workflow.canonical.edges.length.toString()} />
          <Stat label="Current version" value={workflow.current_version_id ?? "Unknown"} />
        </div>
      </div>
    </section>
  );
}

function isUuid(value: string | undefined): value is string {
  return Boolean(value && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value));
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-line bg-white p-4">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className="mt-2 break-all text-lg font-semibold">{value}</div>
    </div>
  );
}
