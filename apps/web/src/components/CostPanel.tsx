"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";

import { api } from "@/lib/api";
import { formatDimension, money } from "@/lib/format";
import type { CostEstimate } from "@/types/workflow";

export function CostPanel({ workflowId, initialEstimate }: { workflowId: string; initialEstimate: CostEstimate }) {
  const [estimate, setEstimate] = useState(initialEstimate);
  const [executions, setExecutions] = useState(Number(initialEstimate.scenario.executions_per_day ?? 100));
  const [retryRate, setRetryRate] = useState(Number(initialEstimate.scenario.failure_retry_rate ?? 0.05));
  const [busy, setBusy] = useState(false);

  async function recalculate() {
    setBusy(true);
    try {
      setEstimate(await api.estimateCost(workflowId, { executions_per_day: executions, failure_retry_rate: retryRate }));
    } finally {
      setBusy(false);
    }
  }

  const top = [...estimate.line_items].sort((a, b) => b.estimated_cost_per_run - a.estimated_cost_per_run).slice(0, 5);
  return (
    <div className="grid gap-5">
      <div className="grid gap-3 md:grid-cols-4">
        <Stat label="Cost / Run" value={money(estimate.cost_per_run)} />
        <Stat label="Daily" value={money(estimate.daily_cost)} />
        <Stat label="Monthly" value={money(estimate.monthly_cost)} />
        <Stat label="Annual" value={money(estimate.annual_cost)} />
      </div>
      <div className="grid gap-3 border border-line bg-panel p-4 md:grid-cols-[1fr_1fr_auto] md:items-end">
        <label className="grid gap-1 text-sm">
          <span className="font-medium">Executions / day</span>
          <input value={executions} onChange={(event) => setExecutions(Number(event.target.value))} type="number" className="border border-line bg-white px-3 py-2" />
        </label>
        <label className="grid gap-1 text-sm">
          <span className="font-medium">Failure retry rate</span>
          <input value={retryRate} onChange={(event) => setRetryRate(Number(event.target.value))} type="number" step="0.01" className="border border-line bg-white px-3 py-2" />
        </label>
        <button type="button" onClick={recalculate} disabled={busy} className="inline-flex items-center gap-2 rounded-md bg-ink px-3 py-2 text-sm font-medium text-white">
          <RefreshCw size={16} />
          {busy ? "Calculating..." : "Run Scenario"}
        </button>
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
