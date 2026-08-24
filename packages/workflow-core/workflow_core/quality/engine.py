from __future__ import annotations

from workflow_core.quality.models import QualityGateConfig, QualityGateReason, QualityGateResult


class QualityGateEngine:
    def __init__(self, config: QualityGateConfig | None = None) -> None:
        self.config = config or QualityGateConfig()

    def evaluate(
        self,
        *,
        structural_score: float | None = None,
        prompt_alignment_score: float | None = None,
        security_score: float | None = None,
        reliability_score: float | None = None,
        maintainability_score: float | None = None,
        test_coverage: float | None = None,
        critical_test_failures: int = 0,
        critical_security_findings: int = 0,
        monthly_cost_before: float | None = None,
        monthly_cost_after: float | None = None,
    ) -> QualityGateResult:
        reasons = [
            self._minimum("WG-GATE-STRUCTURAL", "Structural score", structural_score, self.config.structural_min),
            self._minimum("WG-GATE-ALIGNMENT", "Prompt alignment score", prompt_alignment_score, self.config.prompt_alignment_min),
            self._minimum("WG-GATE-SECURITY", "Security score", security_score, self.config.security_min),
            self._minimum("WG-GATE-RELIABILITY", "Reliability score", reliability_score, self.config.reliability_min),
            self._minimum("WG-GATE-MAINTAINABILITY", "Maintainability score", maintainability_score, self.config.maintainability_min),
            self._minimum("WG-GATE-COVERAGE", "Workflow test coverage", test_coverage, self.config.test_coverage_min),
        ]
        if self.config.require_all_critical_tests_pass:
            reasons.append(
                QualityGateReason(
                    rule_id="WG-GATE-TESTS",
                    passed=critical_test_failures == 0,
                    title="Critical tests",
                    message="All critical workflow tests must pass.",
                    expected="0 critical failed/error tests",
                    actual=str(critical_test_failures),
                    severity="CRITICAL" if critical_test_failures else "INFO",
                )
            )
        if not self.config.allow_critical_security_findings:
            reasons.append(
                QualityGateReason(
                    rule_id="WG-GATE-SECURITY-CRITICAL",
                    passed=critical_security_findings == 0,
                    title="Critical security findings",
                    message="No critical security finding may remain open.",
                    expected="0 critical security findings",
                    actual=str(critical_security_findings),
                    severity="CRITICAL" if critical_security_findings else "INFO",
                )
            )
        if monthly_cost_before and monthly_cost_after is not None and monthly_cost_before > 0:
            increase = ((monthly_cost_after - monthly_cost_before) / monthly_cost_before) * 100
            reasons.append(
                QualityGateReason(
                    rule_id="WG-GATE-COST",
                    passed=increase <= self.config.monthly_cost_increase_max_percent,
                    title="Monthly cost increase",
                    message="Projected monthly cost increase must stay within the configured budget guardrail.",
                    expected=f"<= {self.config.monthly_cost_increase_max_percent:.1f}%",
                    actual=f"{increase:.1f}%",
                    severity="ERROR" if increase > self.config.monthly_cost_increase_max_percent else "INFO",
                    metadata={"monthly_cost_before": monthly_cost_before, "monthly_cost_after": monthly_cost_after},
                )
            )

        relevant = [reason for reason in reasons if reason.rule_id not in {"WG-GATE-COST"} or reason.metadata]
        passed = all(reason.passed for reason in relevant)
        measured_scores = [
            score
            for score in (
                structural_score,
                prompt_alignment_score,
                security_score,
                reliability_score,
                maintainability_score,
                test_coverage,
            )
            if score is not None
        ]
        aggregate = sum(measured_scores) / len(measured_scores) if measured_scores else 0.0
        return QualityGateResult(
            status="PASS" if passed else "FAIL",
            score=round(float(aggregate), 2),
            reasons=relevant,
            config=self.config,
            dimensions={
                "structural": structural_score,
                "prompt_alignment": prompt_alignment_score,
                "security": security_score,
                "reliability": reliability_score,
                "maintainability": maintainability_score,
                "test_coverage": test_coverage,
            },
        )

    @staticmethod
    def _minimum(rule_id: str, title: str, actual: float | None, expected: float) -> QualityGateReason:
        passed = actual is not None and actual >= expected
        return QualityGateReason(
            rule_id=rule_id,
            passed=passed,
            title=title,
            message=f"{title} must meet the configured threshold.",
            expected=f">= {expected:.1f}",
            actual="not measured" if actual is None else f"{actual:.1f}",
            severity="ERROR" if not passed else "INFO",
        )
