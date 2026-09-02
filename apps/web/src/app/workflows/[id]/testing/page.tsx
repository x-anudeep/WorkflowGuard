import { notFound } from "next/navigation";

import { FuzzPanel } from "@/components/FuzzPanel";
import { Panel, ScoreCard } from "@/components/ScorePanels";
import { TestsPanel } from "@/components/TestsPanel";
import { WorkflowTabs } from "@/components/WorkflowTabs";
import { api } from "@/lib/api";
import { isUuid } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function WorkflowTestingPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) notFound();

  const [workflow, tests, testRuns, fuzzRun] = await Promise.all([
    api.workflow(id),
    api.tests(id),
    api.testRuns(id),
    api.latestFuzz(id).catch(() => null),
  ]);

  const hasRun = testRuns.runs.length > 0;
  const notRun = tests.length - testRuns.runs.length;

  return (
    <section className="px-5 py-7 lg:px-8">
      <WorkflowTabs workflow={workflow} active="testing" />

      <div className="mt-7 grid gap-9">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Stat label="Tests" value={tests.length ? String(tests.length) : "None"} />
          <Stat
            label="Passing"
            value={hasRun ? `${testRuns.passed}/${testRuns.total_tests}` : "Not run"}
            tone={hasRun && testRuns.passed === testRuns.total_tests ? "good" : hasRun ? "bad" : "neutral"}
          />
          {/* Errored tests could not run at all, so they are worse than failing ones and are
              counted separately rather than folded into "failed". */}
          <Stat
            label="Failed / errored"
            value={hasRun ? `${testRuns.failed} / ${testRuns.error}` : "—"}
            tone={hasRun && testRuns.failed + testRuns.error > 0 ? "bad" : "neutral"}
          />
          <ScoreCard
            label="Coverage"
            score={hasRun ? testRuns.latest_coverage : null}
            note={hasRun ? undefined : "run the suite to measure"}
          />
        </div>

        {notRun > 0 && (
          <p className="-mt-6 text-sm text-slate-500">{notRun} test(s) have never been run.</p>
        )}

        <Panel title="Tests & execution traces">
          <TestsPanel workflowId={workflow.id} initialTests={tests} initialRuns={testRuns} />
        </Panel>

        <Panel title="Fuzz & error handling">
          <FuzzPanel workflowId={workflow.id} initialRun={fuzzRun} />
        </Panel>
      </div>
    </section>
  );
}

function Stat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "good" | "bad";
}) {
  const toneClass = tone === "good" ? "text-success" : tone === "bad" ? "text-danger" : "text-ink";
  return (
    <div className="border border-line bg-white p-4">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-3xl font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}
