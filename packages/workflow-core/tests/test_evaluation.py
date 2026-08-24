from workflow_core.canonical.models import Edge, Node, NodeType, SourceFormat, SourceType, Workflow
from workflow_core.evaluation import DeterministicRequirementExtractor, RequirementSpec, SemanticEvaluationEngine
from workflow_core.evaluation.alignment import AlignmentAnalyzer
from workflow_core.evaluation.reliability import ReliabilityAnalyzer
from workflow_core.evaluation.security import SecurityAnalyzer


PROMPT = (
    "Read invoices from Gmail, extract invoice information, require human approval when the amount exceeds $10,000, "
    "then save approved invoices to SAP."
)


def test_requirement_extraction_structures_prompt() -> None:
    spec = DeterministicRequirementExtractor().extract(PROMPT)
    assert spec.trigger is not None
    assert any(req.kind == "approval" for req in spec.requirements)
    assert any(req.kind == "output" and req.metadata.get("systems") == ["sap"] for req in spec.requirements)
    assert spec.constraints[0].must == "human_approval"
    assert spec.constraints[0].when == "amount > 10000"
    assert all(req.text != "000" for req in spec.requirements)
    RequirementSpec.model_validate(spec.model_dump(mode="json"))


def test_alignment_detects_missing_approval_constraint() -> None:
    workflow = Workflow(
        name="Invoice shortcut",
        source_format=SourceFormat.GENERIC_JSON,
        source_type=SourceType.AI_GENERATED,
        source_prompt=PROMPT,
        nodes=[
            Node(id="gmail", name="Read Gmail invoice", type=NodeType.TRIGGER, provider="gmail"),
            Node(id="extract", name="Extract invoice information", type=NodeType.ACTION, configuration={"fields": ["amount"]}),
            Node(id="sap", name="Save approved invoice to SAP", type=NodeType.EXTERNAL_API, provider="sap", configuration={"url": "https://sap.example/api"}),
        ],
        edges=[Edge(source="gmail", target="extract"), Edge(source="extract", target="sap")],
    )
    spec = DeterministicRequirementExtractor().extract(PROMPT)
    _matches, findings = AlignmentAnalyzer().analyze(spec, workflow)
    assert any(finding.rule_id == "WG-ALIGN-003" for finding in findings)


def test_security_rules_detect_embedded_secret_and_http() -> None:
    workflow = Workflow(
        name="Unsafe API",
        source_format=SourceFormat.GENERIC_JSON,
        nodes=[
            Node(
                id="api",
                name="Call API",
                type=NodeType.EXTERNAL_API,
                configuration={"url": "http://example.test", "api_key": "sk-1234567890abcdef123456"},
            )
        ],
        edges=[],
    )
    findings = SecurityAnalyzer().analyze(workflow)
    assert {finding.rule_id for finding in findings} >= {"WG-SEC-001", "WG-SEC-003"}


def test_reliability_rules_detect_missing_timeout_and_retry() -> None:
    workflow = Workflow(
        name="Fragile API",
        source_format=SourceFormat.GENERIC_JSON,
        nodes=[
            Node(id="start", name="Start", type=NodeType.TRIGGER),
            Node(id="api", name="Call API", type=NodeType.EXTERNAL_API, configuration={"url": "https://example.test"}),
            Node(id="end", name="End", type=NodeType.END),
        ],
        edges=[Edge(source="start", target="api"), Edge(source="api", target="end")],
    )
    findings = ReliabilityAnalyzer().analyze(workflow)
    assert {"WG-REL-001", "WG-REL-002"} <= {finding.rule_id for finding in findings}


def test_semantic_evaluation_score_is_explainable() -> None:
    workflow = Workflow(
        name="Invoice workflow",
        source_format=SourceFormat.GENERIC_JSON,
        source_type=SourceType.AI_GENERATED,
        source_prompt=PROMPT,
        nodes=[Node(id="start", name="Read invoices from Gmail", type=NodeType.TRIGGER)],
        edges=[],
    )
    result = SemanticEvaluationEngine().evaluate(workflow, structural_score=80, validation_findings=[])
    assert 0 <= result.overall_score <= 100
    assert result.dimension_scores
    assert result.requirement_spec is not None
    assert any(score.calculation for score in result.dimension_scores)
