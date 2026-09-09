import { notFound } from "next/navigation";

import { AttachmentsPanel } from "@/components/AttachmentsPanel";
import { CostPanel } from "@/components/CostPanel";
import { EvaluationPanel } from "@/components/EvaluationPanel";
import { Empty, FindingCard, Panel, ScoreCard } from "@/components/ScorePanels";
import { WorkflowAssessmentActions } from "@/components/WorkflowAssessmentActions";
import { WorkflowTabs } from "@/components/WorkflowTabs";
import { api } from "@/lib/api";
import { isUuid } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function WorkflowScoresPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) notFound();

  const [workflow, validation, evaluations, cost, qualityGate, attachments, fuzzRun, tests, testRuns] =
    await Promise.all([
      api.workflow(id),
      api.validation(id),
      api.evaluations(id),
      api.cost(id),
      api.qualityGate(id).catch(() => null),
      api.attachments(id).catch(() => []),
      api.latestFuzz(id).catch(() => null),
      api.tests(id).catch(() => []),
      api.testRuns(id).catch(() => null),
    ]);

  const latest = evaluations[0];
  const dimensions = Object.fromEntries(
    (latest?.dimension_scores ?? []).map((score) => [score.dimension, score.score]),
  );
  // Reliability only counts as measured when a campaign actually exercised the workflow;
  // a declared-only score must never read as a proven one.
  const measured = Boolean(fuzzRun && fuzzRun.exercised_cases > 0);
  // Prompt alignment only means something when there is a stated requirement to align *to*.
  // A hand-built workflow with no prompt and no requirement document scores a vacuous 100
  // because nothing was checked, which reads as a pass it never earned.
  const hasRequirements = Boolean(workflow.source_prompt) || attachments.length > 0;
  const findings = latest?.findings ?? [];
  const attention = [
    ...(validation?.findings ?? []).filter((f) => f.severity === "CRITICAL" || f.severity === "ERROR"),
    ...findings.filter((f) => f.severity === "CRITICAL" || f.severity === "ERROR"),
  ];

  return (
    <section className="px-5 py-7 lg:px-8">
      <WorkflowTabs workflow={workflow} active="results" />

      <div className="mt-7 grid gap-9">
        <div>
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500">Overall</div>
              <div className="text-5xl font-semibold">{latest ? Math.round(latest.overall_score) : "—"}</div>
              {latest && !hasRequirements && (
                <div className="mt-1 text-xs text-slate-500">
                  includes an unscored requirement-matching weight
                </div>
              )}
            </div>
            {qualityGate && (
              <div className="text-right">
                <div className="text-xs uppercase tracking-wide text-slate-500">Quality gate</div>
                <div
                  className={`text-2xl font-semibold ${qualityGate.status === "PASS" ? "text-success" : "text-danger"}`}
                >
                  {qualityGate.status}
                </div>
              </div>
            )}
          </div>

        </div>

        <Panel title="Structural validation">
          <p className="-mt-1 mb-3 text-sm text-slate-500">
            Deterministic graph rules. No AI involved: the same workflow always scores the same.
          </p>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <ScoreCard label="Structural" score={dimensions.structural} />
          </div>
        </Panel>

        <Panel title="Semantic evaluation">
          <p className="-mt-1 mb-3 text-sm text-slate-500">
            A second layer over validation, not a replacement for it.{" "}
            {latest?.ai_provider
              ? `Requirements analysed with ${latest.ai_provider}${latest.ai_model ? ` (${latest.ai_model})` : ""}.`
              : "Running deterministically - no AI provider configured."}
          </p>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {hasRequirements && (
              <ScoreCard
                label="Matches requirements"
                score={dimensions.prompt_alignment}
                note={workflow.source_prompt ? "against the prompt" : "against attached documents"}
              />
            )}
            <ScoreCard label="Security" score={dimensions.security} />
            <ScoreCard
              label="Reliability"
              score={dimensions.reliability}
              note={measured ? "measured by fuzzing" : "declared only"}
            />
            <ScoreCard label="Maintainability" score={dimensions.maintainability} />
            <ScoreCard
              label="Test Coverage"
              score={dimensions.test_coverage}
              note={typeof dimensions.test_coverage === "number" ? "from the latest test run" : "no test run yet"}
            />
          </div>
          {!hasRequirements && (
            <p className="mt-3 text-sm text-slate-500">
              Requirement matching is not scored: this workflow has no source prompt and no
              requirement document, so there is nothing to match it against. Attach a BRD, PDD or
              SDD below to score it.
            </p>
          )}
        </Panel>

        {qualityGate && qualityGate.reasons.some((reason) => !reason.passed) && (
          <Panel title="Why the gate fails">
            <div className="border border-line bg-white">
              {qualityGate.reasons
                .filter((reason) => !reason.passed)
                .map((reason) => (
                  <div
                    key={reason.rule_id}
                    className="flex flex-col gap-1 border-b border-line px-4 py-3 text-sm last:border-b-0 md:flex-row md:items-center md:justify-between"
                  >
                    <span>{reason.title}</span>
                    <span className="text-slate-600">
                      {reason.actual} <span className="text-slate-400">expected {reason.expected}</span>
                    </span>
                  </div>
                ))}
            </div>
          </Panel>
        )}

        {attention.length > 0 && (
          <Panel title={`Needs attention (${attention.length})`}>
            <div className="grid gap-3">
              {attention.slice(0, 6).map((finding) => (
                <FindingCard key={`${finding.rule_id}-${finding.message}`} finding={finding} />
              ))}
            </div>
          </Panel>
        )}

        <Panel title="Requirement documents">
          <AttachmentsPanel workflowId={workflow.id} initialAttachments={attachments} />
        </Panel>

        <Panel title="Requirement matching">
          <EvaluationPanel workflowId={workflow.id} initialEvaluations={evaluations} />
        </Panel>

        <Panel title="Structural findings">
          <div className="grid gap-3">
            {(validation?.findings ?? []).map((finding) => (
              <FindingCard
                key={`${finding.rule_id}-${finding.node_id}-${finding.edge_id}-${finding.message}`}
                finding={finding}
              />
            ))}
            {validation?.findings.length === 0 && <Empty>No structural findings detected.</Empty>}
          </div>
        </Panel>

        <Panel title="Cost">
          <CostPanel initialEstimate={cost} />
        </Panel>

        <Panel title="Run an assessment">
          <WorkflowAssessmentActions
            workflowId={workflow.id}
            hasEvaluation={Boolean(latest)}
            hasTests={tests.length > 0}
            hasTestRuns={Boolean(testRuns && testRuns.runs.length > 0)}
            hasUsefulCost={cost.line_items.length > 0}
            gateStatus={qualityGate?.status}
          />
        </Panel>
      </div>
    </section>
  );
}
