"use client";

import { useState } from "react";
import { Wrench } from "lucide-react";

import { api } from "@/lib/api";
import { money, statusTone } from "@/lib/format";
import type { RepairProposal } from "@/types/workflow";

export function RepairPanel({ workflowId, initialRepairs }: { workflowId: string; initialRepairs: RepairProposal[] }) {
  const [repairs, setRepairs] = useState(initialRepairs);
  const [busy, setBusy] = useState<string | null>(null);

  async function generate() {
    setBusy("generate");
    try {
      const proposal = await api.generateRepair(workflowId, { message: "Generate a safe reliability repair." });
      setRepairs((current) => [proposal, ...current]);
    } finally {
      setBusy(null);
    }
  }

  async function decide(id: string, action: "accept" | "reject") {
    setBusy(id);
    try {
      const proposal = action === "accept" ? await api.acceptRepair(id) : await api.rejectRepair(id);
      setRepairs((current) => current.map((item) => (item.id === id ? proposal : item)));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="grid gap-4">
      <button type="button" onClick={generate} disabled={busy !== null} className="inline-flex w-fit items-center gap-2 rounded-md bg-ink px-3 py-2 text-sm font-medium text-white">
        <Wrench size={16} />
        {busy === "generate" ? "Generating..." : "Generate Fix"}
      </button>
      {repairs.map((repair) => <RepairCard key={repair.id} repair={repair} busy={busy === repair.id} onDecision={decide} />)}
      {repairs.length === 0 && <div className="border border-line bg-panel p-4 text-sm text-slate-700">No repair proposals yet.</div>}
    </div>
  );
}

function RepairCard({ repair, busy, onDecision }: { repair: RepairProposal; busy: boolean; onDecision: (id: string, action: "accept" | "reject") => void }) {
  const preview = repair.preview as {
    validation?: { structural_quality_score?: number };
    evaluation?: { overall_score?: number };
    tests?: { coverage?: { overall_coverage?: number }; passed?: number; error?: number; failed?: number };
    cost?: { cost_per_run?: number; monthly_cost?: number };
  };
  return (
    <div className="border border-line p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="font-semibold">{String(repair.patch.title ?? "Repair proposal")}</div>
          <div className={`text-sm font-semibold ${statusTone(repair.status === "accepted" ? "PASSED" : repair.status === "rejected" ? "FAILED" : null)}`}>{repair.status}</div>
        </div>
        {repair.status === "proposed" && (
          <div className="flex gap-2">
            <button type="button" onClick={() => onDecision(repair.id, "accept")} disabled={busy} className="rounded-md bg-ink px-3 py-2 text-sm font-medium text-white">Accept</button>
            <button type="button" onClick={() => onDecision(repair.id, "reject")} disabled={busy} className="rounded-md border border-line px-3 py-2 text-sm font-medium">Reject</button>
          </div>
        )}
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <Stat label="Structural" value={String(preview.validation?.structural_quality_score ?? "-")} />
        <Stat label="Overall" value={String(preview.evaluation?.overall_score ?? "-")} />
        <Stat label="Coverage" value={`${preview.tests?.coverage?.overall_coverage ?? 0}%`} />
        <Stat label="Cost / Run" value={money(preview.cost?.cost_per_run ?? 0)} />
      </div>
      {repair.safety_flags.length > 0 && (
        <div className="mt-3 border border-danger bg-red-50 p-3 text-sm text-danger">
          {repair.safety_flags.map((flag) => <div key={flag}>{flag}</div>)}
        </div>
      )}
      <pre className="mt-3 max-h-64 overflow-auto border border-line bg-panel p-3 text-xs">{JSON.stringify(repair.patch, null, 2)}</pre>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-line bg-white p-3">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}
