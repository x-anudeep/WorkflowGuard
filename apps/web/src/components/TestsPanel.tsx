"use client";

import { useMemo, useState } from "react";
import { FlaskConical, Play, Plus } from "lucide-react";

import { api } from "@/lib/api";
import { formatDate, statusTone } from "@/lib/format";
import type { TestRunSummary, WorkflowTest } from "@/types/workflow";

export function TestsPanel({
  workflowId,
  initialTests,
  initialRuns,
}: {
  workflowId: string;
  initialTests: WorkflowTest[];
  initialRuns: TestRunSummary;
}) {
  const [tests, setTests] = useState(initialTests);
  const [runs, setRuns] = useState(initialRuns);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [draft, setDraft] = useState({
    name: "",
    description: "",
    targetNode: "",
    inputJson: "{\n  \"approved\": true\n}",
  });
  const runsByTest = useMemo(() => {
    const map = new Map<string, TestRunSummary["runs"][number]>();
    for (const run of runs.runs) {
      if (!map.has(run.test_id)) map.set(run.test_id, run);
    }
    return map;
  }, [runs]);

  async function generate() {
    setBusy("generate");
    setError(null);
    try {
      const response = await api.generateTests(workflowId, true, false);
      setTests(response.tests);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Test generation failed");
    } finally {
      setBusy(null);
    }
  }

  async function runAll() {
    setBusy("run");
    setError(null);
    try {
      const response = await api.runTests(workflowId);
      setRuns(response);
      setTests(await api.tests(workflowId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Test run failed");
    } finally {
      setBusy(null);
    }
  }

  async function createTest() {
    setBusy("create");
    setError(null);
    try {
      const input = JSON.parse(draft.inputJson || "{}") as Record<string, unknown>;
      const created = await api.createTest(workflowId, {
        name: draft.name || "Manual workflow test",
        description: draft.description || "Human-authored workflow test.",
        generated_by: "HUMAN",
        input_data: input,
        assertions: [
          ...(draft.targetNode ? [{ type: "node_executed", target: draft.targetNode }] : []),
          { type: "terminated_successfully" },
        ],
        tags: ["manual"],
        importance: "MEDIUM",
      });
      setTests((current) => [created, ...current]);
      setShowCreate(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create test");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="grid gap-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <Stat label="Total Tests" value={tests.length.toString()} />
          <Stat label="Passed" value={runs.passed.toString()} />
          <Stat label="Failed" value={(runs.failed + runs.error).toString()} tone={runs.failed + runs.error ? "text-danger" : "text-good"} />
          <Stat label="Coverage" value={`${runs.latest_coverage}%`} />
          <Stat label="Last Run" value={runs.last_run_at ? formatDate(runs.last_run_at) : "Never"} />
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={generate} disabled={busy !== null} className="inline-flex items-center gap-2 rounded-md border border-line px-3 py-2 text-sm font-medium">
            <FlaskConical size={16} />
            {busy === "generate" ? "Generating..." : "Generate Tests"}
          </button>
          <button type="button" onClick={runAll} disabled={busy !== null || tests.length === 0} className="inline-flex items-center gap-2 rounded-md bg-ink px-3 py-2 text-sm font-medium text-white disabled:opacity-60">
            <Play size={16} />
            {busy === "run" ? "Running..." : "Run All Tests"}
          </button>
          <button type="button" onClick={() => setShowCreate((current) => !current)} className="inline-flex items-center gap-2 rounded-md border border-line px-3 py-2 text-sm font-medium">
            <Plus size={16} />
            Create Test
          </button>
        </div>
      </div>
      {error && <div className="border border-danger bg-red-50 p-3 text-sm text-danger">{error}</div>}
      {showCreate && (
        <div className="grid gap-3 border border-line bg-panel p-4">
          <div className="grid gap-3 md:grid-cols-2">
            <input
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              placeholder="Test name"
              className="border border-line bg-white px-3 py-2 text-sm"
            />
            <input
              value={draft.targetNode}
              onChange={(event) => setDraft({ ...draft, targetNode: event.target.value })}
              placeholder="Expected node ID"
              className="border border-line bg-white px-3 py-2 text-sm"
            />
          </div>
          <input
            value={draft.description}
            onChange={(event) => setDraft({ ...draft, description: event.target.value })}
            placeholder="Description"
            className="border border-line bg-white px-3 py-2 text-sm"
          />
          <textarea
            value={draft.inputJson}
            onChange={(event) => setDraft({ ...draft, inputJson: event.target.value })}
            rows={5}
            className="border border-line bg-white px-3 py-2 font-mono text-xs"
          />
          <button type="button" onClick={createTest} disabled={busy !== null} className="w-fit rounded-md bg-ink px-3 py-2 text-sm font-medium text-white disabled:opacity-60">
            {busy === "create" ? "Creating..." : "Save Test"}
          </button>
        </div>
      )}
      <div className="grid gap-3">
        {tests.map((test) => (
          <TestCard key={test.id} test={test} run={runsByTest.get(test.id)} />
        ))}
        {tests.length === 0 && (
          <div className="border border-line bg-panel p-4 text-sm text-slate-700">
            No tests yet. Generate a deterministic suite or create a custom test.
          </div>
        )}
      </div>
    </div>
  );
}

function TestCard({ test, run }: { test: WorkflowTest; run?: TestRunSummary["runs"][number] }) {
  return (
    <details className="border border-line bg-white p-4">
      <summary className="cursor-pointer">
        <div className="inline-flex flex-wrap items-center gap-2">
          <span className="font-semibold">{test.name}</span>
          <span className="rounded-sm bg-panel px-2 py-1 text-xs">{test.generated_by}</span>
          <span className="rounded-sm bg-panel px-2 py-1 text-xs">{test.importance}</span>
          <span className={`text-sm font-semibold ${statusTone(run?.status ?? test.latest_status)}`}>{run?.status ?? test.latest_status ?? "NOT RUN"}</span>
        </div>
      </summary>
      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_1.2fr]">
        <div className="grid gap-3 text-sm text-slate-700">
          <p>{test.description}</p>
          {test.rationale && <Field label="Rationale" value={test.rationale} />}
          {test.linked_requirement_id && <Field label="Requirement" value={test.linked_requirement_id} />}
          <JsonBlock label="Input" value={test.input_data} />
          <JsonBlock label="Assertions" value={test.assertions} />
          {test.failure_injections.length > 0 && <JsonBlock label="Failure Injection" value={test.failure_injections} />}
        </div>
        <div>
          <div className="mb-2 text-sm font-semibold">Execution Trace</div>
          {run ? <Trace run={run} /> : <div className="border border-line bg-panel p-3 text-sm text-slate-600">No execution trace yet.</div>}
        </div>
      </div>
    </details>
  );
}

function Trace({ run }: { run: TestRunSummary["runs"][number] }) {
  const nodes = run.execution_trace.node_executions ?? [];
  return (
    <div className="border border-line bg-panel p-3">
      <div className={`text-sm font-semibold ${statusTone(run.status)}`}>{run.status}</div>
      <div className="mt-3 grid gap-2">
        {nodes.map((node, index) => (
          <div key={`${node.node_id}-${index}`}>
            <div className="flex items-center justify-between border border-line bg-white px-3 py-2 text-sm">
              <span>{node.node_name}</span>
              <span className={node.error ? "text-danger" : "text-good"}>{node.error ? "FAILED" : "OK"}</span>
            </div>
            {index < nodes.length - 1 && <div className="px-3 py-1 text-xs text-slate-500">down</div>}
          </div>
        ))}
      </div>
      {run.failures.length > 0 && (
        <div className="mt-3 border border-danger bg-red-50 p-3 text-sm text-danger">
          {run.failures.map((failure) => <div key={failure}>{failure}</div>)}
        </div>
      )}
      {run.coverage && (
        <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-600 md:grid-cols-4">
          <span>Nodes {run.coverage.node_coverage}%</span>
          <span>Edges {run.coverage.edge_coverage}%</span>
          <span>Branches {run.coverage.branch_coverage}%</span>
          <span>Requirements {run.coverage.requirement_coverage}%</span>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, tone = "text-ink" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="border border-line bg-white p-3">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${tone}`}>{value}</div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="font-medium text-ink">{label}: </span>
      <span>{value}</span>
    </div>
  );
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <div className="mb-1 font-medium text-ink">{label}</div>
      <pre className="max-h-44 overflow-auto border border-line bg-panel p-2 text-xs">{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}
