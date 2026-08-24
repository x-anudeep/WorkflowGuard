import Link from "next/link";

import { api } from "@/lib/api";
import { formatDate, formatSourceFormat, scoreTone } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function WorkflowsPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const resolvedSearchParams = await searchParams;
  const params = Object.fromEntries(Object.entries(resolvedSearchParams).filter(([, value]) => value));
  const workflows = await api.workflows(params as Record<string, string>).catch(() => []);

  return (
    <section className="px-5 py-7 lg:px-8">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Workflows</h1>
          <p className="mt-1 text-sm text-slate-600">Uploaded BPMN, generic JSON, and n8n workflows.</p>
        </div>
        <Link href="/upload" className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-white">Upload</Link>
      </div>
      <form className="mt-6 grid gap-3 border border-line bg-panel p-4 md:grid-cols-[1.5fr_1fr_1fr_1fr_auto]">
        <input
          name="q"
          defaultValue={resolvedSearchParams.q ?? ""}
          className="border border-line bg-white px-3 py-2 text-sm outline-none focus:border-accent"
          placeholder="Search name, requirement, metadata"
        />
        <select name="source_format" defaultValue={resolvedSearchParams.source_format ?? ""} className="border border-line bg-white px-3 py-2 text-sm">
          <option value="">Any format</option>
          <option value="bpmn">BPMN</option>
          <option value="generic_json">Generic JSON</option>
          <option value="n8n">n8n</option>
        </select>
        <select name="source_type" defaultValue={resolvedSearchParams.source_type ?? ""} className="border border-line bg-white px-3 py-2 text-sm">
          <option value="">Any source</option>
          <option value="human">Human</option>
          <option value="ai_generated">AI generated</option>
        </select>
        <select name="has_critical" defaultValue={resolvedSearchParams.has_critical ?? ""} className="border border-line bg-white px-3 py-2 text-sm">
          <option value="">Critical: any</option>
          <option value="true">Has critical</option>
          <option value="false">No critical</option>
        </select>
        <button className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-white">Filter</button>
      </form>
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
          <div className="border border-line bg-panel p-5 text-sm text-slate-700">No workflows match the current filters.</div>
        )}
      </div>
    </section>
  );
}
