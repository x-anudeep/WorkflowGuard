import { formatDimension, money } from "@/lib/format";
import type { CostEstimate } from "@/types/workflow";

export function CostPanel({ initialEstimate }: { initialEstimate: CostEstimate }) {
  const estimate = initialEstimate;

  const top = [...estimate.line_items].sort((a, b) => b.estimated_cost_per_run - a.estimated_cost_per_run).slice(0, 5);
  return (
    <div className="grid gap-5">
      <div className="grid gap-3 md:grid-cols-4">
        <Stat label="Cost / Run" value={money(estimate.cost_per_run)} />
        <Stat label="Daily" value={money(estimate.daily_cost)} />
        <Stat label="Monthly" value={money(estimate.monthly_cost)} />
        <Stat label="Annual" value={money(estimate.annual_cost)} />
      </div>
      <div className="overflow-hidden border border-line">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="bg-panel text-xs uppercase text-slate-500">
            <tr><th className="px-4 py-3">Node</th><th>Category</th><th>Provider</th><th>Tokens</th><th>Cost / Run</th></tr>
          </thead>
          <tbody>
            {top.map((item) => (
              <tr key={`${item.node_id}-${item.category}`} className="border-t border-line">
                <td className="px-4 py-3 font-medium">{item.node_name ?? item.node_id}</td>
                <td>{formatDimension(item.category)}</td>
                <td>{item.provider}{item.model ? ` / ${item.model}` : ""}</td>
                <td>{item.input_tokens + item.output_tokens}</td>
                <td>{money(item.estimated_cost_per_run)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {estimate.optimization_findings.length > 0 && (
        <div className="grid gap-3">
          <h3 className="text-sm font-semibold">Optimization Opportunities</h3>
          {estimate.optimization_findings.map((finding) => (
            <div key={finding.id} className="border border-line p-4 text-sm">
              <div className="font-semibold">{finding.title} - {money(finding.estimated_monthly_savings)}/month potential</div>
              <p className="mt-1 text-slate-700">{finding.message}</p>
              <p className="mt-1 text-slate-600">{finding.recommendation}</p>
            </div>
          ))}
        </div>
      )}
      <div className="border border-line bg-panel p-4 text-sm text-slate-700">
        {estimate.assumptions.map((assumption) => <div key={assumption}>{assumption}</div>)}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-line bg-white p-4">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold">{value}</div>
    </div>
  );
}
