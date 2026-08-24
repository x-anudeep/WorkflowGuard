import Link from "next/link";

import { api } from "@/lib/api";
import { formatDate, formatSourceFormat, scoreTone } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function WorkflowsPage() {
  const workflows = await api.workflows().catch(() => []);

  return (
    <section className="px-5 py-7 lg:px-8">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Workflows</h1>
          <p className="mt-1 text-sm text-slate-600">Uploaded BPMN, generic JSON, and n8n workflows.</p>
        </div>
        <Link href="/upload" className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-white">Upload</Link>
      </div>
      <div className="mt-7 grid gap-3">
        {workflows.map((workflow) => (
          <Link key={workflow.id} href={`/workflows/${workflow.id}`} className="border border-line bg-white p-4 hover:border-slate-400">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="font-semibold">{workflow.name}</div>
                <div className="mt-1 text-sm text-slate-600">
                  {formatSourceFormat(workflow.source_format)} · {workflow.source_type.replace("_", " ")} · {formatDate(workflow.created_at)}
                </div>
              </div>
              <div className="flex items-center gap-5 text-sm">
                <span className={`font-semibold ${scoreTone(workflow.structural_quality_score)}`}>
                  {workflow.structural_quality_score ?? "Pending"}
                </span>
                <span className="text-slate-600">{workflow.critical_findings} critical</span>
              </div>
            </div>
          </Link>
        ))}
        {workflows.length === 0 && (
          <div className="border border-line bg-panel p-5 text-sm text-slate-700">No workflows uploaded yet.</div>
        )}
      </div>
    </section>
  );
}
