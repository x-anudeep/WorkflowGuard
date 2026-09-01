from __future__ import annotations

from workflow_core.canonical.models import ValidationFinding, Workflow
from workflow_core.evaluation.alignment import AlignmentAnalyzer
from workflow_core.evaluation.hallucination import HallucinationAnalyzer
from workflow_core.evaluation.maintainability import MaintainabilityAnalyzer
from workflow_core.evaluation.models import EvaluationResult, RequirementSpec
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
        self.hallucination = HallucinationAnalyzer()
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
    ) -> EvaluationResult:
        spec = requirement_spec
        if spec is None and workflow.source_prompt:
            spec = self.extractor.extract(workflow.source_prompt)

        matches = []
        findings = []
        if spec is not None:
            matches, alignment_findings = self.alignment.analyze(spec, workflow)
            findings.extend(alignment_findings)

        findings.extend(self.reliability.analyze(workflow))
        findings.extend(self.hallucination.analyze(workflow))
        findings.extend(self.security.analyze(workflow))
        findings.extend(self.maintainability.analyze(workflow))
        if fuzz_report is not None:
            findings.extend(fuzz_report.findings)
        scores = dimension_scores(workflow, structural_score, validation_findings, findings, fuzz_report)

        limitations = [
            "Semantic evaluation combines deterministic graph analysis with optional AI-assisted requirement extraction.",
            "Security and reliability analysis are best-effort static checks and are not a penetration test or runtime proof.",
        ]
        if spec is None:
            limitations.append("No source prompt was available, so prompt alignment could not be evaluated.")
        if fuzz_report is None:
            limitations.append(
                "No fuzz campaign has been run, so reliability reflects declared error handling only."
            )
        else:
            limitations.extend(fuzz_report.limitations)

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
