from __future__ import annotations

import re
from typing import Any

from workflow_core.canonical.models import NodeType, ValidationSeverity, Workflow
from workflow_core.evaluation.models import (
    Confidence,
    EvaluationDimension,
    EvaluationFinding,
)

SECRET_KEYS = re.compile(r"(api[_-]?key|token|secret|password|private[_-]?key|credential)", re.IGNORECASE)
SECRET_VALUE = re.compile(r"(sk-[A-Za-z0-9]{16,}|xox[baprs]-|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]+PRIVATE KEY-----)")


class SecurityAnalyzer:
    def analyze(self, workflow: Workflow) -> list[EvaluationFinding]:
        findings: list[EvaluationFinding] = []
        # Denominators for the per-node rules, so scoring can weigh "8 of 8 external calls"
        # against "1 of 8" instead of subtracting a flat penalty each time.
        total = len(workflow.nodes)
        external = sum(1 for node in workflow.nodes if node.type == NodeType.EXTERNAL_API)
        llm = sum(1 for node in workflow.nodes if node.type == NodeType.LLM)
        # Same reasoning as the reliability timeout/retry rules: if no external call in the
        # whole workflow declares auth, the format has no field for it, and marking every node
        # down measures the export format rather than the workflow.
        declares_auth = any(
            _has_auth(node.configuration) for node in workflow.nodes if node.type == NodeType.EXTERNAL_API
        )
        if external and not declares_auth:
            findings.append(
                EvaluationFinding(
                    rule_id="WG-SEC-004",
                    dimension=EvaluationDimension.SECURITY,
                    severity=ValidationSeverity.INFO,
                    title="No authentication declared anywhere in this workflow",
                    message=(
                        f"None of the {external} external call(s) declare authentication. The "
                        f"'{workflow.source_format}' format may bind credentials outside the "
                        "workflow definition, so this is reported once as advice."
                    ),
                    expected="External integrations should declare credentials or authentication.",
                    found="No credential/auth field on any external call.",
                    why_it_matters=(
                        "Unauthenticated endpoints can fail unexpectedly or permit unintended "
                        "access - but platform-level credential binding would not appear here."
                    ),
                    remediation="Confirm where credentials are bound for this platform.",
                    confidence=Confidence.LOW,
                )
            )
        for node in workflow.nodes:
            flattened = _flatten(node.configuration)
            for key, value in flattened.items():
                value_text = str(value)
                if SECRET_KEYS.search(key) and value_text and not _looks_like_reference(value_text):
                    findings.append(
                        _finding(
                            "WG-SEC-001",
                            ValidationSeverity.CRITICAL,
                            "Embedded credential or secret",
                            f"Node '{node.name}' appears to contain a secret-like configuration value.",
                            "Credentials should be referenced from a secret store or provider credential binding.",
                            f"{key}=<redacted>",
                            "Secrets in workflow definitions can leak through version history, logs, exports, or UI access.",
                            node.id,
                            "Move the value into a managed credential/secret reference.",
                            Confidence.HIGH,
                            total,
                        )
                    )
                elif SECRET_VALUE.search(value_text):
                    findings.append(
                        _finding(
                            "WG-SEC-002",
                            ValidationSeverity.CRITICAL,
                            "Secret-like value detected",
                            f"Node '{node.name}' has a value matching a known secret pattern.",
                            "No raw tokens, keys, or private keys in workflow configuration.",
                            f"{key}=<redacted>",
                            "Raw secrets can be exfiltrated by anyone who can inspect workflow metadata.",
                            node.id,
                            "Replace with a secret reference and rotate the exposed value.",
                            Confidence.HIGH,
                            total,
                        )
                    )

            url = _first_url(node.configuration)
            if url and url.startswith("http://"):
                findings.append(
                    _finding(
                        "WG-SEC-003",
                        ValidationSeverity.ERROR,
                        "Unsafe HTTP endpoint",
                        f"Node '{node.name}' calls a non-TLS HTTP endpoint.",
                        "External calls should use HTTPS unless explicitly justified.",
                        url,
                        "Plain HTTP can expose sensitive workflow data in transit.",
                        node.id,
                        "Use HTTPS or document why this internal endpoint is safe.",
                        Confidence.HIGH,
                        total,
                    )
                )
            if node.type == NodeType.EXTERNAL_API and declares_auth and not _has_auth(node.configuration):
                findings.append(
                    _finding(
                        "WG-SEC-004",
                        ValidationSeverity.WARNING,
                        "Missing authentication configuration",
                        f"External API node '{node.name}' has no detectable authentication settings.",
                        "External integrations should declare credentials or authentication.",
                        "No credential/auth field detected.",
                        "Unauthenticated endpoints can fail unexpectedly or permit unintended access patterns.",
                        node.id,
                        "Attach a provider credential reference or explicit auth configuration.",
                        Confidence.MEDIUM,
                        external,
                    )
                )
            if node.type == NodeType.LLM and _mentions_sensitive_data(workflow):
                findings.append(
                    _finding(
                        "WG-SEC-005",
                        ValidationSeverity.WARNING,
                        "Sensitive data may be sent to an LLM",
                        f"LLM node '{node.name}' exists in a workflow that appears to process sensitive data.",
                        "Sensitive data should be minimized, redacted, or controlled before LLM calls.",
                        "LLM node without detectable redaction/control metadata.",
                        "LLMs can retain or expose sensitive data depending on provider configuration.",
                        node.id,
                        "Add redaction, data minimization, or explicit provider privacy controls before this node.",
                        Confidence.LOW,
                        llm,
                    )
                )
        return findings


def _finding(
    rule_id: str,
    severity: ValidationSeverity,
    title: str,
    message: str,
    expected: str,
    found: str,
    why: str,
    node_id: str,
    remediation: str,
    confidence: Confidence,
    rule_population: int | None = None,
) -> EvaluationFinding:
    return EvaluationFinding(
        rule_id=rule_id,
        dimension=EvaluationDimension.SECURITY,
        severity=severity,
        title=title,
        message=message,
        expected=expected,
        found=found,
        why_it_matters=why,
        node_id=node_id,
        remediation=remediation,
        confidence=confidence,
        rule_population=rule_population,
    )


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            child_key = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(child, child_key))
        return result
    if isinstance(value, list):
        result = {}
        for index, child in enumerate(value):
            result.update(_flatten(child, f"{prefix}[{index}]"))
        return result
    return {prefix: value}


def _looks_like_reference(value: str) -> bool:
    return value.startswith(("env:", "${", "secret:", "vault:", "cred:")) or "{{" in value


def _first_url(configuration: dict[str, Any]) -> str | None:
    for value in _flatten(configuration).values():
        text = str(value)
        if text.startswith(("http://", "https://")):
            return text
    return None


def _has_auth(configuration: dict[str, Any]) -> bool:
    return any(SECRET_KEYS.search(key) or "auth" in key.lower() or "credential" in key.lower() for key in _flatten(configuration))


def _mentions_sensitive_data(workflow: Workflow) -> bool:
    text = " ".join([workflow.name, str(workflow.metadata)] + [node.name for node in workflow.nodes]).lower()
    return any(term in text for term in ("invoice", "customer", "patient", "payment", "salary", "ssn", "personal"))
