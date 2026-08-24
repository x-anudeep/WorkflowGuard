import Link from "next/link";
import { AlertTriangle, DollarSign, FlaskConical, Gauge, GitBranch, ShieldCheck, TrendingUp } from "lucide-react";

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
          <p className="mt-1 text-sm text-slate-600">Workflow correctness, safety, testing, and cost signals from real runs.</p>
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
          <div className="mt-7 grid gap-4 md:grid-cols-2 xl:grid-cols-5">
            <Metric icon={<GitBranch size={20} />} label="Workflows" value={metrics.total_workflows.toString()} />
            <Metric icon={<GitBranch size={20} />} label="Versions" value={metrics.total_workflow_versions.toString()} />
            <Metric icon={<Gauge size={20} />} label="Avg quality" value={metrics.average_quality_score.toFixed(1)} />
            <Metric icon={<ShieldCheck size={20} />} label="Validation runs" value={metrics.total_validation_runs.toString()} />
            <Metric icon={<AlertTriangle size={20} />} label="Critical findings" value={metrics.critical_issues.toString()} />
            <Metric icon={<FlaskConical size={20} />} label="Tests generated" value={metrics.total_workflow_tests.toString()} />
            <Metric icon={<Gauge size={20} />} label="Test pass rate" value={`${metrics.test_pass_rate.toFixed(1)}%`} />
            <Metric icon={<Gauge size={20} />} label="Avg coverage" value={`${metrics.average_coverage.toFixed(1)}%`} />
            <Metric icon={<DollarSign size={20} />} label="Monthly cost" value={`$${metrics.latest_monthly_cost.toFixed(2)}`} />
            <Metric icon={<TrendingUp size={20} />} label="Potential savings" value={`$${metrics.potential_cost_savings.toFixed(2)}`} />
          </div>

          <div className="mt-8 grid gap-5 xl:grid-cols-3">
            <ChartPanel title="Quality Over Time" points={(metrics.charts.quality_over_time ?? []).map((item) => item.score)} />
            <ChartPanel title="Cost Trend" points={(metrics.charts.cost_trend ?? []).map((item) => item.monthly_cost)} currency />
            <SeverityPanel severities={metrics.charts.findings_by_severity ?? {}} />
          </div>

          <div className="mt-8 grid gap-6 xl:grid-cols-[1.5fr_1fr]">
            <div>
              <h2 className="text-base font-semibold">Recent workflows</h2>
              <div className="mt-3 overflow-hidden border border-line bg-white">
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
            <div>
              <h2 className="text-base font-semibold">Most expensive workflows</h2>
              <div className="mt-3 border border-line bg-white">
                {(metrics.charts.most_expensive_workflows ?? []).map((workflow) => (
                  <Link key={workflow.workflow_id} href={`/workflows/${workflow.workflow_id}`} className="block border-b border-line px-4 py-3 last:border-b-0">
                    <div className="text-sm font-medium">{workflow.name}</div>
                    <div className="mt-1 text-sm text-slate-600">${workflow.monthly_cost.toFixed(2)} / month</div>
                  </Link>
                ))}
                {(metrics.charts.most_expensive_workflows ?? []).length === 0 && (
                  <div className="p-4 text-sm text-slate-600">No cost estimates recorded yet.</div>
                )}
              </div>
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

function ChartPanel({ title, points, currency = false }: { title: string; points: number[]; currency?: boolean }) {
  const max = Math.max(...points, 1);
  return (
    <div className="border border-line bg-white p-5">
      <h2 className="text-sm font-semibold">{title}</h2>
      <div className="mt-4 flex h-36 items-end gap-2">
        {points.length === 0 ? (
          <div className="self-center text-sm text-slate-500">No data yet.</div>
        ) : (
          points.map((value, index) => (
            <div key={`${title}-${index}`} className="flex flex-1 flex-col items-center gap-2">
              <div className="w-full bg-accent" style={{ height: `${Math.max((value / max) * 100, 6)}%` }} />
              <span className="text-[10px] text-slate-500">{currency ? `$${value.toFixed(0)}` : value.toFixed(0)}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function SeverityPanel({ severities }: { severities: Record<string, number> }) {
  const entries = ["CRITICAL", "ERROR", "WARNING", "INFO"].map((key) => [key, severities[key] ?? 0] as const);
  const total = entries.reduce((sum, [, value]) => sum + value, 0);
  return (
    <div className="border border-line bg-white p-5">
      <h2 className="text-sm font-semibold">Findings by severity</h2>
      <div className="mt-4 space-y-3">
        {entries.map(([severity, value]) => (
          <div key={severity}>
            <div className="flex justify-between text-xs text-slate-600">
              <span>{severity}</span>
              <span>{value}</span>
            </div>
            <div className="mt-1 h-2 bg-panel">
              <div className="h-2 bg-ink" style={{ width: total ? `${(value / total) * 100}%` : "0%" }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
