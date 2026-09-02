from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class QualityGateConfig(BaseModel):
    """Per-dimension floors. Every one must pass - the gate is a conjunction, not an average.

    Recalibrated for the budgeted penalty scale (`evaluator_version` part2-deterministic-v2).
    Under the old uncapped scale these floors were unreachable for any workflow above roughly
    14 nodes, because per-node rules pushed reliability and security to 0 by construction; the
    gate could only ever fail. They are now reachable, and set against the measured
    distribution over the 30 reference workflows rather than by guesswork.
    """

    #: Unchanged: a structurally invalid graph is not a judgement call.
    structural_min: float = 90
    #: Unchanged: 25 of 30 reference workflows score 100 here.
    prompt_alignment_min: float = 90
    #: Corpus: min 78, p25 80, median 98. Kept strict - the gap from 100 is real findings
    #: (missing auth, sensitive data reaching an LLM), and most workflows clear it comfortably.
    security_min: float = 85
    #: Corpus: min 71, median 74, p75 86. Lowered from 80 because roughly 10 points of every
    #: workflow's reliability is spent on WG-REL-004 (single point of failure), which is INFO
    #: and fires on nearly every external call by construction. 75 keeps the gate sensitive to
    #: what it should catch - an LLM or dependency with no failure path - without failing every
    #: workflow for an advisory rule it cannot avoid.
    reliability_min: float = 75
    #: Unchanged: the whole corpus scores 100.
    maintainability_min: float = 70
    #: Lowered from 85. Branch and failure-injection coverage is bounded by how much of the
    #: graph the generated suite can legitimately reach, and 85 was set when nothing had been
    #: measured. Revisit once the remaining generated-test failures are separated into real
    #: findings and generator defects.
    test_coverage_min: float = 75
    require_all_critical_tests_pass: bool = True
    allow_critical_security_findings: bool = False
    monthly_cost_increase_max_percent: float = 20
    metadata: dict[str, Any] = Field(default_factory=dict)


class QualityGateReason(BaseModel):
    rule_id: str
    passed: bool
    title: str
    message: str
    expected: str
    actual: str
    severity: Literal["INFO", "WARNING", "ERROR", "CRITICAL"] = "ERROR"
    metadata: dict[str, Any] = Field(default_factory=dict)


class QualityGateResult(BaseModel):
    status: Literal["PASS", "FAIL"]
    score: float
    reasons: list[QualityGateReason]
    config: QualityGateConfig
    dimensions: dict[str, float | None] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
