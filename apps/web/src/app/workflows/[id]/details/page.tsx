import { notFound } from "next/navigation";

import { RepairPanel } from "@/components/RepairPanel";
import { Empty, Panel } from "@/components/ScorePanels";
import { VersionComparePanel } from "@/components/VersionComparePanel";
import { WorkflowTabs } from "@/components/WorkflowTabs";
import { api } from "@/lib/api";
import { formatDate, isUuid } from "@/lib/format";

export const dynamic = "force-dynamic";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";

export default async function WorkflowDetailsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) notFound();

  const [workflow, comparison, repairs, history, versions] = await Promise.all([
    api.workflow(id),
    api.compareVersions(id),
    api.repairs(id),
    api.history(id).catch(() => []),
    api.versions(id).catch(() => []),
  ]);

  return (
    <section className="px-5 py-7 lg:px-8">
      <WorkflowTabs workflow={workflow} active="details" />

      <div className="mt-7 grid gap-9">
        <Panel title="Reports">
          <div className="flex flex-wrap gap-3">
            {(["html", "markdown", "json"] as const).map((format) => (
              <a
                key={format}
                href={`${API_BASE}/workflows/${workflow.id}/report?format=${format}`}
                className="border border-line px-3 py-2 text-sm font-medium hover:border-slate-400"
              >
                {format.toUpperCase()} report
              </a>
            ))}
          </div>
        </Panel>

        <Panel title="Repair proposals">
          <RepairPanel workflowId={workflow.id} initialRepairs={repairs} />
        </Panel>

        <Panel title="Versions">
          <div className="grid gap-2">
            {versions.map((version) => (
              <div
                key={version.id}
                className="flex flex-col gap-1 border border-line bg-white p-3 text-sm md:flex-row md:items-center md:justify-between"
              >
                <span className="font-medium">Version {version.version_number}</span>
                <span className="text-slate-500">{formatDate(version.created_at)}</span>
              </div>
            ))}
            {versions.length === 0 && <Empty>No versions recorded.</Empty>}
          </div>
        </Panel>

        <Panel title="Compare versions">
          <VersionComparePanel workflow={workflow} comparison={comparison} />
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
            {history.length === 0 && <Empty>No audit events recorded yet.</Empty>}
          </div>
        </Panel>

        <Panel title="Canonical source">
          <pre className="max-h-[520px] overflow-auto border border-line bg-panel p-4 text-xs">
            {JSON.stringify(workflow.canonical, null, 2)}
          </pre>
        </Panel>
      </div>
    </section>
  );
}
