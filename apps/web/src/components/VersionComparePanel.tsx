import type { VersionComparison, WorkflowDetail } from "@/types/workflow";

export function VersionComparePanel({ workflow, comparison }: { workflow: WorkflowDetail; comparison: VersionComparison }) {
  return (
    <div className="grid gap-4">
      <div className="grid gap-3 md:grid-cols-3">
        <Stat label="Nodes Added" value={comparison.nodes_added.length.toString()} />
        <Stat label="Nodes Removed" value={comparison.nodes_removed.length.toString()} />
        <Stat label="Config Changes" value={comparison.configuration_changed.length.toString()} />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <ChangeList title="Added" items={[...comparison.nodes_added, ...comparison.edges_added]} />
        <ChangeList title="Removed" items={[...comparison.nodes_removed, ...comparison.edges_removed]} />
      </div>
      <ChangeList title="Configuration Changed" items={comparison.configuration_changed} />
      <div className="border border-line bg-panel p-4 text-sm text-slate-700">
        Current version: {workflow.current_version_id ?? "Unknown"}. Deltas appear after multiple versions and stored run history are available.
      </div>
    </div>
  );
}

function ChangeList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="border border-line p-4">
      <div className="text-sm font-semibold">{title}</div>
      <div className="mt-2 grid gap-1 text-sm text-slate-700">
        {items.length ? items.map((item) => <div key={item}>{item}</div>) : <div>None</div>}
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
