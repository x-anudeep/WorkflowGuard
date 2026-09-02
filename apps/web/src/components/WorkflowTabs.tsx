import Link from "next/link";

import { formatDate, formatSourceFormat } from "@/lib/format";
import type { WorkflowDetail } from "@/types/workflow";

const TABS = [
  { slug: "results", label: "Scores" },
  { slug: "testing", label: "Tests & Traces" },
  { slug: "details", label: "Details" },
] as const;

export function WorkflowTabs({
  workflow,
  active,
}: {
  workflow: WorkflowDetail;
  active: (typeof TABS)[number]["slug"];
}) {
  return (
    <div>
      <Link href={`/workflows/${workflow.id}`} className="text-sm text-slate-600 hover:text-accent">
        Back to workflow view
      </Link>
      <h1 className="mt-4 text-2xl font-semibold">{workflow.name}</h1>
      <p className="mt-1 text-sm text-slate-500">
        {formatSourceFormat(workflow.source_format)} · {formatDate(workflow.created_at)}
      </p>
      <nav className="mt-5 flex gap-1 border-b border-line">
        {TABS.map((tab) => (
          <Link
            key={tab.slug}
            href={`/workflows/${workflow.id}/${tab.slug}`}
            aria-current={tab.slug === active ? "page" : undefined}
            className={`-mb-px border-b-2 px-4 py-2 text-sm ${
              tab.slug === active
                ? "border-ink font-medium text-ink"
                : "border-transparent text-slate-500 hover:text-ink"
            }`}
          >
            {tab.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}
