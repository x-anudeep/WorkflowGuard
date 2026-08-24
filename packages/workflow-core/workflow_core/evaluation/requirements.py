from __future__ import annotations

import re

from workflow_core.evaluation.models import Confidence, RequirementConstraint, RequirementItem, RequirementKind, RequirementSpec
from workflow_core.evaluation.text import normalize_text


ACTION_VERBS = {
    "read",
    "extract",
    "require",
    "save",
    "send",
    "create",
    "update",
    "delete",
    "notify",
    "route",
    "approve",
    "reject",
    "check",
    "validate",
    "transform",
    "load",
    "write",
    "post",
    "call",
    "fetch",
    "log",
}
APPROVAL_TERMS = {"approval", "approve", "manual approval", "human approval", "review"}
ERROR_TERMS = {"error", "failure", "fallback", "retry", "timeout", "dead letter", "exception"}
PROHIBITED_PATTERNS = (r"\bdo not\b(.+)", r"\bnever\b(.+)", r"\bwithout\b(.+)")
SYSTEM_ALIASES = {
    "gmail": "gmail",
    "sap": "sap",
    "slack": "slack",
    "salesforce": "salesforce",
    "stripe": "stripe",
    "postgres": "postgres",
    "postgresql": "postgres",
    "mysql": "mysql",
    "s3": "s3",
    "openai": "openai",
}


class DeterministicRequirementExtractor:
    def extract(self, prompt: str) -> RequirementSpec:
        clauses = _split_prompt(prompt)
        requirements: list[RequirementItem] = []
        expected_outputs: list[RequirementItem] = []
        prohibited: list[RequirementItem] = []
        constraints: list[RequirementConstraint] = []
        trigger: RequirementItem | None = None
        order: list[str] = []

        for index, clause in enumerate(clauses):
            normalized = normalize_text(clause)
            if not normalized:
                continue
            kind = _classify_clause(clause, index)
            item = RequirementItem(
                kind=kind,
                text=clause,
                normalized=normalized,
                source_excerpt=clause,
                metadata={"systems": _systems_in_text(clause)},
            )
            if kind == RequirementKind.TRIGGER and trigger is None:
                trigger = item
            elif kind == RequirementKind.OUTPUT:
                expected_outputs.append(item)
                requirements.append(item)
            else:
                requirements.append(item)
            if kind in {RequirementKind.ACTION, RequirementKind.APPROVAL, RequirementKind.INTEGRATION, RequirementKind.OUTPUT}:
                order.append(item.id)

            for constraint in _extract_constraints(clause):
                constraints.append(constraint)

        for pattern in PROHIBITED_PATTERNS:
            for match in re.finditer(pattern, prompt, flags=re.IGNORECASE):
                text = match.group(0).strip(" .")
                prohibited.append(
                    RequirementItem(
                        kind=RequirementKind.PROHIBITED_BEHAVIOR,
                        text=text,
                        normalized=normalize_text(text),
                        source_excerpt=text,
                    )
                )

        if not requirements and prompt.strip():
            requirements.append(
                RequirementItem(
                    kind=RequirementKind.ACTION,
                    text=prompt.strip(),
                    normalized=normalize_text(prompt),
                    source_excerpt=prompt.strip(),
                )
            )

        return RequirementSpec(
            source_prompt=prompt,
            summary=_summary(prompt),
            trigger=trigger,
            requirements=requirements,
            required_order=order,
            constraints=constraints,
            prohibited_behaviors=prohibited,
            expected_outputs=expected_outputs,
            extraction_method="deterministic",
            confidence=Confidence.MEDIUM,
            metadata={"clause_count": len(clauses)},
        )


def _split_prompt(prompt: str) -> list[str]:
    prompt = prompt.strip()
    if not prompt:
        return []
    protected_amounts: list[str] = []

    def protect_amount(match: re.Match[str]) -> str:
        protected_amounts.append(match.group(0))
        return f"__AMOUNT_{len(protected_amounts) - 1}__"

    prompt = re.sub(r"\$?\d{1,3}(?:,\d{3})+(?:\.\d+)?", protect_amount, prompt)
    prompt = re.sub(r"\bthen\b", ", then ", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r"\band then\b", ", then ", prompt, flags=re.IGNORECASE)
    parts = re.split(r"[,;\n]+|(?:\s+→\s+)", prompt)
    restored = []
    for part in parts:
        for index, amount in enumerate(protected_amounts):
            part = part.replace(f"__AMOUNT_{index}__", amount)
        part = re.sub(r"^then\s+", "", part.strip(), flags=re.IGNORECASE)
        if part.strip(" ."):
            restored.append(part.strip(" ."))
    return restored


def _classify_clause(clause: str, index: int) -> RequirementKind:
    lower = clause.lower()
    if index == 0 and ("when" in lower or "new " in lower or "from " in lower or "trigger" in lower):
        return RequirementKind.TRIGGER
    if any(term in lower for term in ERROR_TERMS):
        return RequirementKind.ERROR_BEHAVIOR
    if lower.startswith(("save", "send", "write", "create", "update", "notify")):
        return RequirementKind.OUTPUT
    if any(term in lower for term in APPROVAL_TERMS):
        return RequirementKind.APPROVAL
    if "if " in lower or "when " in lower or "exceeds" in lower or "greater than" in lower or ">" in lower:
        return RequirementKind.CONDITION
    if _systems_in_text(clause):
        return RequirementKind.INTEGRATION
    if set(normalize_text(clause).split()) & ACTION_VERBS:
        return RequirementKind.ACTION
    return RequirementKind.ACTION


def _extract_constraints(clause: str) -> list[RequirementConstraint]:
    lower = clause.lower()
    constraints: list[RequirementConstraint] = []
    if ("when" in lower or "if" in lower or "exceeds" in lower or ">" in lower) and any(
        term in lower for term in APPROVAL_TERMS
    ):
        when = clause
        amount = re.search(r"(\$?\d[\d,]*(?:\.\d+)?)", clause)
        if amount:
            when = f"amount > {amount.group(1).replace('$', '').replace(',', '')}"
        constraints.append(
            RequirementConstraint(
                when=when,
                must="human_approval",
                source_excerpt=clause,
                metadata={"detected_type": "conditional_approval"},
            )
        )
    return constraints


def _systems_in_text(value: str) -> list[str]:
    lower = value.lower()
    return sorted({canonical for alias, canonical in SYSTEM_ALIASES.items() if alias in lower})


def _summary(prompt: str) -> str:
    prompt = prompt.strip()
    return prompt[:220] + ("..." if len(prompt) > 220 else "")
