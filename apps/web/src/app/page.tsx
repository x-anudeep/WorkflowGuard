import Link from "next/link";
import { AlertTriangle, FlaskConical, Gauge, GitBranch, ShieldCheck } from "lucide-react";

import { api } from "@/lib/api";
import { formatDate, formatSourceFormat, scoreTone } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const metrics = await api.dashboard().catch(() => null);

  return (
    <section className="px-5 py-7 lg:px-8">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-normal">Dashboard</h1>
          <p className="mt-1 text-sm text-slate-600">Database-backed structural validation metrics.</p>
        </div>
        <Link href="/upload" className="inline-flex items-center justify-center rounded-md bg-ink px-4 py-2 text-sm font-medium text-white">
          Upload workflow
        </Link>
      </div>

      {!metrics ? (
        <div className="mt-8 border border-line bg-panel p-5 text-sm text-slate-700">
          API is not reachable. Start the backend to populate WorkflowGuard metrics.
        </div>
      ) : (
        <>
          <div className="mt-7 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <Metric icon={<GitBranch size={20} />} label="Total workflows" value={metrics.total_workflows.toString()} />
            <Metric icon={<ShieldCheck size={20} />} label="Validation runs" value={metrics.total_validation_runs.toString()} />
            <Metric icon={<Gauge size={20} />} label="Avg structural score" value={metrics.average_structural_score.toFixed(1)} />
            <Metric icon={<AlertTriangle size={20} />} label="Critical issues" value={metrics.critical_issues.toString()} />
            <Metric icon={<Gauge size={20} />} label="Avg workflow score" value={metrics.average_overall_score.toFixed(1)} />
            <Metric icon={<FlaskConical size={20} />} label="Workflow tests" value={metrics.total_workflow_tests.toString()} />
            <Metric icon={<Gauge size={20} />} label="Test coverage" value={`${metrics.latest_test_coverage.toFixed(1)}%`} />
            <Metric icon={<AlertTriangle size={20} />} label="Failing test runs" value={metrics.failing_test_runs.toString()} />
            <Metric icon={<Gauge size={20} />} label="Monthly cost" value={`$${metrics.latest_monthly_cost.toFixed(2)}`} />
            <Metric icon={<AlertTriangle size={20} />} label="Open repairs" value={metrics.open_repair_proposals.toString()} />
          </div>

          <div className="mt-8">
            <h2 className="text-base font-semibold">Recent workflows</h2>
            <div className="mt-3 overflow-hidden border border-line">
              <table className="w-full min-w-[760px] border-collapse text-left text-sm">
                <thead className="bg-panel text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Name</th>
                    <th className="px-4 py-3">Format</th>
                    <th className="px-4 py-3">Score</th>
                    <th className="px-4 py-3">Critical</th>
                    <th className="px-4 py-3">Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.recent_workflows.map((workflow) => (
                    <tr key={workflow.id} className="border-t border-line">
                      <td className="px-4 py-3 font-medium">
                        <Link href={`/workflows/${workflow.id}`} className="hover:text-accent">{workflow.name}</Link>
                      </td>
                      <td className="px-4 py-3">{formatSourceFormat(workflow.source_format)}</td>
                      <td className={`px-4 py-3 font-semibold ${scoreTone(workflow.structural_quality_score)}`}>
                        {workflow.structural_quality_score ?? "Pending"}
                      </td>
                      <td className="px-4 py-3">{workflow.critical_findings}</td>
                      <td className="px-4 py-3 text-slate-600">{formatDate(workflow.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="border border-line bg-white p-5 shadow-soft">
      <div className="flex items-center justify-between">
        <span className="text-sm text-slate-600">{label}</span>
        <span className="text-slate-500">{icon}</span>
      </div>
      <div className="mt-4 text-3xl font-semibold">{value}</div>
    </div>
  );
}
