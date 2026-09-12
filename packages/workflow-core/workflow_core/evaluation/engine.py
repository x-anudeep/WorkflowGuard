from __future__ import annotations

from workflow_core.canonical.models import ValidationFinding, Workflow
from workflow_core.evaluation.alignment import AlignmentAnalyzer
from workflow_core.evaluation.maintainability import MaintainabilityAnalyzer
from workflow_core.evaluation.models import EvaluationResult, RequirementMatch, RequirementSpec
from workflow_core.evaluation.reliability import ReliabilityAnalyzer
from workflow_core.evaluation.requirements import DeterministicRequirementExtractor
from workflow_core.evaluation.scoring import dimension_scores, overall_score
from workflow_core.evaluation.security import SecurityAnalyzer
from workflow_core.fuzzing.models import FuzzReport


class SemanticEvaluationEngine:
    def __init__(self) -> None:
        self.extractor = DeterministicRequirementExtractor()
        self.alignment = AlignmentAnalyzer()
        self.reliability = ReliabilityAnalyzer()
        self.security = SecurityAnalyzer()
        self.maintainability = MaintainabilityAnalyzer()

    def evaluate(
        self,
        workflow: Workflow,
        *,
        structural_score: int,
        validation_findings: list[ValidationFinding],
        requirement_spec: RequirementSpec | None = None,
        fuzz_report: FuzzReport | None = None,
        requirement_matches: list[RequirementMatch] | None = None,
        test_coverage: float | None = None,
    ) -> EvaluationResult:
        spec = requirement_spec
        if spec is None and workflow.source_prompt:
            spec = self.extractor.extract(workflow.source_prompt)

        matches = []
        findings = []
        if spec is not None:
            matches, alignment_findings = self.alignment.analyze(
                spec, workflow, supplied_matches=requirement_matches
            )
            findings.extend(alignment_findings)

        findings.extend(self.reliability.analyze(workflow))
        findings.extend(self.security.analyze(workflow))
        findings.extend(self.maintainability.analyze(workflow))
        if fuzz_report is not None:
            findings.extend(fuzz_report.findings)
        scores = dimension_scores(
            workflow, structural_score, validation_findings, findings, fuzz_report, test_coverage
        )

        limitations = [
            "Semantic evaluation combines deterministic graph analysis with optional AI-assisted requirement extraction.",
            "Security and reliability analysis are best-effort static checks and are not a penetration test or runtime proof.",
        ]
        if spec is None:
            limitations.append("No source prompt was available, so prompt alignment could not be evaluated.")
        else:
            limitations.extend(_alignment_limitations(spec, matches))
        if fuzz_report is None:
            limitations.append(
                "No fuzz campaign has been run, so reliability reflects declared error handling only."
            )
        else:
            limitations.extend(fuzz_report.limitations)
        if test_coverage is None:
            limitations.append(
                "No test run exists for this version, so test coverage could not be measured."
            )

        return EvaluationResult(
            workflow_id=workflow.id,
            requirement_spec=spec,
            requirement_matches=matches,
            findings=findings,
            dimension_scores=scores,
            overall_score=overall_score(scores),
            structural_score=structural_score,
            limitations=limitations,
        )


def _alignment_limitations(spec: RequirementSpec, matches: list[RequirementMatch]) -> list[str]:
    """Say plainly when a document requirement was judged by keyword matching alone."""
    limitations: list[str] = []
    document_items = {item.id for item in spec.requirements if item.source == "document"}
    if not document_items:
        return limitations
    limitations.append(
        f"{len(document_items)} requirement(s) came from attached documents rather than the prompt. "
        "Document requirements are matched but not order-checked: a document lists requirements "
        "in presentation order, which is not a required execution sequence."
    )
    weak = [
        match
        for match in matches
        if match.requirement_id in document_items and match.match_method == "deterministic"
    ]
    if weak:
        limitations.append(
            "Requirement matching for attached documents ran without an AI provider; unmatched "
            "document requirements are reported as warnings because keyword matching cannot "
            "bridge document vocabulary."
        )
    return limitations
