import re
from pathlib import Path

import pytest

from workflow_core.canonical.models import (
    Edge,
    Node,
    NodeType,
    SourceFormat,
    SourceType,
    ValidationSeverity,
    Workflow,
)
from workflow_core.documents import DocumentKind, MarkdownRequirementParser
from workflow_core.evaluation.alignment import AlignmentAnalyzer
from workflow_core.evaluation.models import RequirementKind, RequirementMatch
from workflow_core.evaluation.requirements import DeterministicRequirementExtractor

CORPUS = Path(__file__).resolve().parents[3] / "references" / "documents"

#: The 10 complex reference workflows are the only ones with requirement documents, and the
#: parser is tuned against them, so the tests run on the real files rather than toy fixtures.
EXPECTED_KINDS = {
    "C01_invoice_processing_pdd.md": DocumentKind.PDD,
    "C02_customer_onboarding_brd.md": DocumentKind.BRD,
    "C03_order_fulfillment_sdd.md": DocumentKind.SDD,
    "C04_loan_approval_pdd.md": DocumentKind.PDD,
    "C05_employee_offboarding_brd.md": DocumentKind.BRD,
    "C06_insurance_claims_pdd.md": DocumentKind.PDD,
    "C07_data_pipeline_sdd.md": DocumentKind.SDD,
    "C08_vendor_management_brd.md": DocumentKind.BRD,
    "C09_kyc_verification_pdd.md": DocumentKind.PDD,
    "C10_incident_management_sdd.md": DocumentKind.SDD,
}

pytestmark = pytest.mark.skipif(not CORPUS.is_dir(), reason="reference corpus not checked out")


def _parse(name: str):
    return MarkdownRequirementParser().parse((CORPUS / name).read_text(), filename=name)


@pytest.mark.parametrize("name,kind", sorted(EXPECTED_KINDS.items()))
def test_document_kind_detected(name: str, kind: DocumentKind) -> None:
    assert _parse(name).kind == kind


def test_brd_sections_are_split_and_classified() -> None:
    document = _parse("C02_customer_onboarding_brd.md")
    anchors = {section.anchor for section in document.sections if section.scored}
    assert {"BR-1", "BR-2", "BR-3", "BR-4", "BR-5", "BR-6"} <= anchors

    unscored = {section.heading for section in document.sections if not section.scored}
    assert "1. Business Context" in unscored
    assert "5. Acceptance Criteria" in unscored


def test_clauses_carry_their_source_anchor() -> None:
    document = _parse("C02_customer_onboarding_brd.md")
    assert all(clause.source_anchor for clause in document.clauses)
    assert {clause.source_anchor for clause in document.clauses} & {"BR-1", "BR-4"}


def test_document_parsing_beats_the_prompt_splitter() -> None:
    """The regression guard for the whole feature.

    Feeding a BRD straight into the prompt splitter produced 70 requirements for this file,
    almost all of them headings and metadata. Every one that fails to match a node costs 18
    points of PROMPT_ALIGNMENT, so the parser has to yield far fewer, and only real ones.
    """
    raw = (CORPUS / "C02_customer_onboarding_brd.md").read_text()
    split_count = len(DeterministicRequirementExtractor().extract(raw).requirements)
    parsed = _parse("C02_customer_onboarding_brd.md")

    assert split_count > 60
    assert len(parsed.clauses) < split_count / 2


@pytest.mark.parametrize("name", sorted(EXPECTED_KINDS))
def test_no_clause_is_a_heading_or_metadata_line(name: str) -> None:
    for clause in _parse(name).clauses:
        assert not clause.text.startswith("#"), clause.text
        assert not re.match(r"^\*\*[A-Z][a-z]+:\*\*", clause.text), clause.text
        assert len(clause.text.split()) >= 2, clause.text


def test_decision_matrix_becomes_constraints() -> None:
    document = _parse("C08_vendor_management_brd.md")
    assert len(document.constraints) >= 3
    whens = " ".join(constraint.when.lower() for constraint in document.constraints)
    assert "sanctions match" in whens


def test_integration_table_names_its_own_systems() -> None:
    """The alignment matcher's nine hardcoded aliases cover none of this corpus."""
    document = _parse("C08_vendor_management_brd.md")
    systems = {
        system
        for clause in document.clauses
        for system in clause.metadata.get("systems", [])
    }
    assert {"docusign", "documentai"} <= systems

    integrations = [c for c in document.clauses if c.kind == RequirementKind.INTEGRATION]
    assert any("DocuSign" in clause.text for clause in integrations)


def test_exception_table_is_error_behaviour_not_branching() -> None:
    document = _parse("C01_invoice_processing_pdd.md")
    errors = [c for c in document.clauses if c.kind == RequirementKind.ERROR_BEHAVIOR]
    assert any("PO not found" in clause.text for clause in errors)


def test_pdd_and_sdd_step_shapes_parse() -> None:
    pdd = _parse("C01_invoice_processing_pdd.md")
    assert {"Step 1", "Step 8"} <= {section.anchor for section in pdd.sections}

    sdd = _parse("C03_order_fulfillment_sdd.md")
    assert {"2.1", "2.7"} <= {section.anchor for section in sdd.sections}


def test_reference_tables_produce_no_clauses() -> None:
    """Data Fields / Data Model describe payload shape, not behaviour to look for in a graph."""
    document = _parse("C01_invoice_processing_pdd.md")
    assert not [c for c in document.clauses if c.source_anchor.startswith("4-data")]


def test_parsing_is_stable() -> None:
    first = _parse("C05_employee_offboarding_brd.md")
    second = _parse("C05_employee_offboarding_brd.md")
    assert [c.text for c in first.clauses] == [c.text for c in second.clauses]


def test_empty_document_is_harmless() -> None:
    document = MarkdownRequirementParser().parse("", filename="empty.md")
    assert document.clauses == []
    assert document.kind == DocumentKind.OTHER


def _tiny_workflow() -> Workflow:
    return Workflow(
        name="Onboarding",
        source_format=SourceFormat.GENERIC_JSON,
        source_type=SourceType.HUMAN,
        nodes=[
            Node(id="start", name="Signup Webhook", type=NodeType.TRIGGER),
            Node(id="acct", name="Create Account", type=NodeType.EXTERNAL_API),
            Node(id="end", name="End", type=NodeType.END),
        ],
        edges=[Edge(id="e1", source="start", target="acct"), Edge(id="e2", source="acct", target="end")],
    )


def test_prompt_misses_stay_errors() -> None:
    """Regression guard: the prompt path must score exactly as it did before documents existed."""
    spec = DeterministicRequirementExtractor().extract("Create the account and archive to Postgres.")
    _matches, findings = AlignmentAnalyzer().analyze(spec, _tiny_workflow())
    misses = [f for f in findings if f.rule_id == "WG-ALIGN-001"]
    assert misses
    assert all(f.severity == ValidationSeverity.ERROR for f in misses)


def test_document_miss_by_keyword_is_a_warning() -> None:
    document = _parse("C02_customer_onboarding_brd.md")
    spec = DeterministicRequirementExtractor().extract_composite(None, [document])
    _matches, findings = AlignmentAnalyzer().analyze(spec, _tiny_workflow())
    misses = [f for f in findings if f.rule_id == "WG-ALIGN-001"]
    assert misses
    assert all(f.severity == ValidationSeverity.WARNING for f in misses)
    assert all(f.metadata["requirement_source"] == "document" for f in misses)


def test_document_miss_judged_by_ai_is_an_error() -> None:
    """When something competent said it is missing, it is worth a full penalty."""
    document = _parse("C02_customer_onboarding_brd.md")
    spec = DeterministicRequirementExtractor().extract_composite(None, [document])
    supplied = [
        RequirementMatch(
            requirement_id=item.id,
            requirement_text=item.text,
            status="missing",
            evidence="Judged absent by the model.",
            match_method="ai:mock",
        )
        for item in spec.requirements
    ]
    _matches, findings = AlignmentAnalyzer().analyze(spec, _tiny_workflow(), supplied_matches=supplied)
    misses = [f for f in findings if f.rule_id == "WG-ALIGN-001"]
    assert misses
    assert all(f.severity == ValidationSeverity.ERROR for f in misses)


def test_supplied_matches_are_used_verbatim() -> None:
    document = _parse("C02_customer_onboarding_brd.md")
    spec = DeterministicRequirementExtractor().extract_composite(None, [document])
    first = spec.requirements[0]
    supplied = [
        RequirementMatch(
            requirement_id=first.id,
            requirement_text=first.text,
            status="matched",
            matched_node_ids=["acct"],
            evidence="Model matched this to Create Account.",
            match_method="ai:mock",
        )
    ]
    matches, _findings = AlignmentAnalyzer().analyze(spec, _tiny_workflow(), supplied_matches=supplied)
    by_id = {match.requirement_id: match for match in matches}
    assert by_id[first.id].matched_node_ids == ["acct"]
    assert by_id[first.id].match_method == "ai:mock"


def test_document_clauses_do_not_drive_ordering_checks() -> None:
    """Presentation order is not execution order.

    Ordering the bullets of a BRD against the graph produced 8 WG-ALIGN-002 errors against a
    single real miss on the reference corpus, flooring the dimension for reasons unrelated to
    alignment. Prompt ordering still applies.
    """
    document = _parse("C01_invoice_processing_pdd.md")
    spec = DeterministicRequirementExtractor().extract_composite(None, [document])
    assert spec.required_order == []

    _matches, findings = AlignmentAnalyzer().analyze(spec, _tiny_workflow())
    assert not [f for f in findings if f.rule_id == "WG-ALIGN-002"]


def test_prompt_ordering_still_applies() -> None:
    spec = DeterministicRequirementExtractor().extract(
        "Create the account, then send the welcome email, then log the metrics."
    )
    assert len(spec.required_order) >= 2
