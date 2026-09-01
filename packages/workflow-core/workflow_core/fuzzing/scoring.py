from __future__ import annotations

from collections import defaultdict

from workflow_core.canonical.models import ValidationSeverity, Workflow
from workflow_core.evaluation.models import (
    Confidence,
    EvaluationDimension,
    EvaluationFinding,
)
from workflow_core.fuzzing.models import ErrorHandlingVerdict, FuzzCaseResult

#: Credit each verdict earns towards the robustness score.
VERDICT_WEIGHTS: dict[ErrorHandlingVerdict, float] = {
    ErrorHandlingVerdict.HANDLED: 1.0,
    ErrorHandlingVerdict.SILENT_SUCCESS: 0.0,
    ErrorHandlingVerdict.UNHANDLED_CRASH: 0.0,
    ErrorHandlingVerdict.HUNG: 0.0,
}

#: Verdicts that did not actually exercise the workflow, excluded from the denominator.
UNEXERCISED = frozenset({ErrorHandlingVerdict.NOT_TRIGGERED})

#: Cap so one badly-behaved node cannot emit dozens of near-identical findings.
MAX_FINDINGS_PER_RULE = 8


def robustness_score(results: list[FuzzCaseResult]) -> int:
    """Share of exercised fuzz cases the workflow survived, as 0-100.

    Returns 100 when nothing was exercised: an unexercised workflow has not been shown
    to be fragile, and the caller records the case count alongside the score so an
    empty campaign is never mistaken for a proven-robust one.
    """
    exercised = [
        result for result in results if ErrorHandlingVerdict(result.verdict) not in UNEXERCISED
    ]
    if not exercised:
        return 100
    earned = sum(VERDICT_WEIGHTS.get(ErrorHandlingVerdict(result.verdict), 0.0) for result in exercised)
    return round(100 * earned / len(exercised))


def fuzz_findings(workflow: Workflow, results: list[FuzzCaseResult]) -> list[EvaluationFinding]:
    """Turn fuzz outcomes into reliability findings, grouped so they stay readable."""
    findings: list[EvaluationFinding] = []
    findings.extend(_crash_findings(results))
    findings.extend(_silent_findings(results))
    findings.extend(_hung_findings(results))
    return findings


def _crash_findings(results: list[FuzzCaseResult]) -> list[EvaluationFinding]:
    dependency: dict[str, list[FuzzCaseResult]] = defaultdict(list)
    input_driven: list[FuzzCaseResult] = []
    for result in results:
        if ErrorHandlingVerdict(result.verdict) != ErrorHandlingVerdict.UNHANDLED_CRASH:
            continue
        if result.case.failure_injections:
            for injection in result.case.failure_injections:
                dependency[injection.node_id].append(result)
        else:
            input_driven.append(result)

    findings = [
        EvaluationFinding(
            rule_id="WG-FUZZ-001",
            dimension=EvaluationDimension.RELIABILITY,
            severity=ValidationSeverity.ERROR,
            title="Dependency failure crashes the workflow",
            message=(
                f"{len(group)} fuzz case(s) failed node '{_node_label(group)}' and the run aborted "
                "with no error path to continue on."
            ),
            expected="A failing dependency should route to a declared error or compensation path.",
            found=f"Run aborted on {_failure_types(group)}.",
            why_it_matters=(
                "An unhandled dependency failure leaves the workflow half-executed: work already "
                "done is not rolled back and nobody is told the run stopped."
            ),
            node_id=node_id,
            remediation="Add an error branch from this node to compensation, retry, or human review.",
            confidence=Confidence.HIGH,
            metadata=_repro(group),
        )
        for node_id, group in sorted(dependency.items())
    ][:MAX_FINDINGS_PER_RULE]

    if input_driven:
        findings.append(
            EvaluationFinding(
                rule_id="WG-FUZZ-004",
                dimension=EvaluationDimension.RELIABILITY,
                severity=ValidationSeverity.WARNING,
                title="Malformed input crashes the workflow",
                message=f"{len(input_driven)} fuzz case(s) crashed the run using only mutated input data.",
                expected="Malformed or hostile input should be validated and rejected, not abort the run.",
                found=f"Crashing inputs: {_case_names(input_driven)}.",
                why_it_matters=(
                    "Input arrives from upstream systems and users. Input that aborts the run turns a "
                    "bad record into an outage."
                ),
                remediation="Validate and coerce inputs at the trigger, and route invalid records to an error path.",
                confidence=Confidence.HIGH,
                metadata=_repro(input_driven),
            )
        )
    return findings


def _silent_findings(results: list[FuzzCaseResult]) -> list[EvaluationFinding]:
    grouped: dict[str, list[FuzzCaseResult]] = defaultdict(list)
    for result in results:
        if ErrorHandlingVerdict(result.verdict) != ErrorHandlingVerdict.SILENT_SUCCESS:
            continue
        for injection in result.case.failure_injections:
            grouped[injection.node_id].append(result)

    return [
        EvaluationFinding(
            rule_id="WG-FUZZ-002",
            dimension=EvaluationDimension.RELIABILITY,
            severity=ValidationSeverity.ERROR,
            title="Failure is silently swallowed",
            message=(
                f"Node '{_node_label(group)}' failed in {len(group)} fuzz case(s), but the run still "
                "reported success without notifying anyone or compensating."
            ),
            expected="A handled failure should still notify, compensate, or escalate before finishing.",
            found="The error branch ran no recovery work before terminating.",
            why_it_matters=(
                "This is the most expensive failure mode to operate: the run looks green, so nobody "
                "investigates, while the record it was supposed to process is quietly dropped."
            ),
            node_id=node_id,
            remediation="Have the error path raise an alert, write a dead-letter record, or request human review.",
            confidence=Confidence.MEDIUM,
            metadata=_repro(group),
        )
        for node_id, group in sorted(grouped.items())
    ][:MAX_FINDINGS_PER_RULE]


def _hung_findings(results: list[FuzzCaseResult]) -> list[EvaluationFinding]:
    hung = [result for result in results if ErrorHandlingVerdict(result.verdict) == ErrorHandlingVerdict.HUNG]
    if not hung:
        return []
    return [
        EvaluationFinding(
            rule_id="WG-FUZZ-003",
            dimension=EvaluationDimension.RELIABILITY,
            severity=ValidationSeverity.WARNING,
            title="Retry or loop does not terminate under repeated failure",
            message=f"{len(hung)} fuzz case(s) never terminated and hit the simulator step limit.",
            expected="Retries and loops must be bounded so a persistent outage still ends the run.",
            found=f"Non-terminating cases: {_case_names(hung)}.",
            why_it_matters=(
                "An unbounded retry loop turns a transient outage into runaway cost, duplicated side "
                "effects, and a run that never reports failure."
            ),
            remediation="Add a maximum attempt count and an exit path once retries are exhausted.",
            confidence=Confidence.MEDIUM,
            metadata=_repro(hung),
        )
    ]


def _node_label(group: list[FuzzCaseResult]) -> str:
    for result in group:
        for execution in result.simulation.node_executions:
            if execution.error:
                return execution.node_name
    return group[0].case.targeted_node_ids[0] if group[0].case.targeted_node_ids else "unknown"


def _failure_types(group: list[FuzzCaseResult]) -> str:
    types = sorted(
        {str(injection.failure_type) for result in group for injection in result.case.failure_injections}
    )
    return ", ".join(types) or "injected failures"


def _case_names(group: list[FuzzCaseResult]) -> str:
    names = [result.case.name for result in group[:4]]
    if len(group) > 4:
        names.append(f"and {len(group) - 4} more")
    return "; ".join(names)


def _repro(group: list[FuzzCaseResult]) -> dict[str, object]:
    """Enough to re-run the exact failing case."""
    return {
        "fuzz_case_count": len(group),
        "fuzz_seed": group[0].case.seed,
        "fuzz_case_names": [result.case.name for result in group[:10]],
        "fuzz_case_ids": [result.case.id for result in group[:10]],
    }
