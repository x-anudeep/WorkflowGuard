from __future__ import annotations

import re

from workflow_core.documents.models import (
    DocumentClause,
    DocumentConstraint,
    DocumentKind,
    DocumentSection,
    RequirementDocument,
)
from workflow_core.evaluation.models import RequirementKind
from workflow_core.evaluation.text import normalize_text

#: Headings whose subtree carries scoreable requirements. Matched as substrings against the
#: lowercased heading, and inherited by every nested heading beneath them.
SCORED_PARENTS = (
    "business requirement",
    "requirements",
    "process flow",
    "process steps",
    "technical flow",
    "functional requirement",
    "exception handling",
    "error handling",
    "exception cases",
    "decision matrix",
    "decision tree",
    "decision points",
    "integration points",
)

#: Headings that describe the project rather than requiring anything of the workflow. Kept on
#: the document for display, never turned into clauses. Checked before SCORED_PARENTS, so
#: "Performance Requirements" lands here despite containing "requirements".
INFORMATIONAL_PARENTS = (
    "business context",
    "process overview",
    "solution overview",
    "current state",
    "target state",
    "acceptance criteria",
    "success metric",
    "performance requirement",
    "data field",
    "data model",
    "sla",
    "timeline",
    "assumption",
    "out of scope",
    "glossary",
)

#: A `**Label:** value` metadata line — document front-matter, not a requirement.
METADATA_LINE = re.compile(r"^\*\*[^*]+:\*\*")
#: An inline `**Decision:**` label at the head of a bullet.
LABEL_PREFIX = re.compile(r"^\**[A-Z][A-Za-z /&-]{2,24}:\**\s*")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
TABLE_DIVIDER = re.compile(r"^\s*\|[\s:|-]+\|\s*$")

#: `### BR-4: Workspace Setup` -> `BR-4`, `### Step 3: Vendor Validation` -> `Step 3`,
#: `### 2.4 Shipping Label Generation` -> `2.4`.
ANCHOR_PATTERNS = (
    re.compile(r"^((?:BR|FR|NFR|UC|AC)-\d+)", re.IGNORECASE),
    re.compile(r"^(Step\s+\d+)", re.IGNORECASE),
    re.compile(r"^(\d+(?:\.\d+)+)"),
)

#: Table header keywords that mark the first column as a condition rather than a subject.
CONDITION_HEADERS = ("condition", "exception", "error", "scenario", "when", "if", "trigger", "case")
SYSTEM_HEADERS = ("system", "integration", "service", "source")

APPROVAL_TERMS = ("approval", "approve", "sign-off", "review", "escalate")
ERROR_TERMS = ("error", "failure", "fallback", "retry", "timeout", "exception", "unreachable")
OUTPUT_VERBS = ("send", "save", "write", "create", "update", "notify", "post", "generate", "publish")
TRIGGER_TERMS = ("when ", "webhook", "arrive", "receipt", "submission", "trigger", "signs up", "on new")

#: An HTTP method + path, or a bare API path - the strongest signal that a clause calls out.
ENDPOINT = re.compile(r"\b(?:GET|POST|PUT|PATCH|DELETE)\s+/|/api/")
#: `DocumentAI`, `DocuSign` - an internal capital is a product name, not a sentence start.
CAMEL_CASE = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+\b")
#: `SAP`, `ISO`, `SOC2`, `EIN`. Short all-caps tokens.
ACRONYM = re.compile(r"\b[A-Z]{2,6}[0-9]?\b")
#: All-caps words that are roles, document jargon or HTTP verbs rather than systems.
ACRONYM_STOPWORDS = frozenset(
    {
        "GET", "POST", "PUT", "PATCH", "DELETE", "API", "APIS", "URL", "URI", "JSON", "XML",
        "CSV", "PDF", "HTTP", "HTTPS", "REST", "CFO", "CEO", "CTO", "COO", "VP", "HR", "AP",
        "IT", "AND", "OR", "IF", "ID", "IDS", "OK", "NA", "TBD", "ETA", "SLA", "SLAS", "KPI",
        "KPIS", "T", "TCS", "US", "EU", "UK", "AI", "ML", "OCR", "PII", "MFA", "SSO",
    }
)


class MarkdownRequirementParser:
    """Turns a BRD/PDD/SDD markdown document into atomic, scoreable requirement clauses.

    The clauses it emits are deliberately *not* run through the prompt clause splitter. Splitting
    a document on `[,;\\n]` treats every heading and metadata line as a requirement, which on this
    corpus inflates a 2.8 KB BRD into 70 requirements and floors the alignment score.
    """

    def parse(self, content: str, *, filename: str | None = None) -> RequirementDocument:
        sections = self._sections(content, filename=filename)
        title = next((section.heading for section in sections if section.level == 1), "")
        document = RequirementDocument(
            kind=_detect_kind(filename, title),
            title=title or (filename or ""),
            filename=filename,
            sections=sections,
        )
        for section in sections:
            if not section.scored:
                continue
            clauses, constraints = self._section_requirements(section)
            document.clauses.extend(clauses)
            document.constraints.extend(constraints)
        document.metadata = {
            "section_count": len(sections),
            "scored_section_count": sum(1 for section in sections if section.scored),
            "clause_count": len(document.clauses),
        }
        return document

    def _sections(self, content: str, *, filename: str | None) -> list[DocumentSection]:
        sections: list[DocumentSection] = []
        current: DocumentSection | None = None
        body: list[str] = []
        table: list[str] = []
        #: level -> scored flag, so a `### Step 1` inherits the verdict of its `## Process Flow`.
        inherited: dict[int, bool] = {}

        def flush() -> None:
            if current is None:
                return
            _absorb_table(current, table)
            table.clear()
            current.body = "\n".join(body).strip()
            sections.append(current)
            body.clear()

        for line in content.splitlines():
            heading = HEADING.match(line)
            if heading:
                flush()
                level = len(heading.group(1))
                text = heading.group(2).strip()
                for deeper in [key for key in inherited if key >= level]:
                    del inherited[deeper]
                scored = _scored_for(text, inherited, level)
                inherited[level] = scored
                current = DocumentSection(heading=text, level=level, anchor=_anchor(text), scored=scored)
                continue
            if current is None:
                continue
            if TABLE_ROW.match(line):
                table.append(line)
                continue
            if table:
                _absorb_table(current, table)
                table.clear()
            bullet = BULLET.match(line)
            if bullet:
                indent = len(bullet.group(1))
                current.bullets.append(f"{'  ' * (indent // 2)}{bullet.group(2).strip()}")
                continue
            body.append(line)
        flush()
        return sections

    def _section_requirements(
        self, section: DocumentSection
    ) -> tuple[list[DocumentClause], list[DocumentConstraint]]:
        clauses: list[DocumentClause] = []
        constraints: list[DocumentConstraint] = []
        context = section.heading

        for text in _leaf_bullets(section.bullets):
            clause = _clause(text, section, context)
            if _is_substantive(clause.text):
                clauses.append(clause)

        for line in section.body.splitlines():
            line = line.strip()
            if not line or METADATA_LINE.match(line) or line.startswith(">"):
                continue
            if len(normalize_text(line).split()) < 3:
                continue
            clause = _clause(line, section, context)
            if _is_substantive(clause.text):
                clauses.append(clause)

        for rows in section.tables:
            table_clauses, table_constraints = _table_requirements(rows, section)
            clauses.extend(table_clauses)
            constraints.extend(table_constraints)

        return clauses, constraints


def _scored_for(text: str, inherited: dict[int, bool], level: int) -> bool:
    lowered = text.lower()
    # An explicitly numbered requirement heading (`BR-6: Success Metrics Tracking`) is a
    # requirement whatever its topic, so the anchor wins over the informational keywords.
    if any(pattern.match(text) for pattern in ANCHOR_PATTERNS[:2]):
        return True
    if any(term in lowered for term in INFORMATIONAL_PARENTS):
        return False
    if any(term in lowered for term in SCORED_PARENTS):
        return True
    parent = max((key for key in inherited if key < level), default=None)
    return inherited[parent] if parent is not None else False


def _anchor(heading: str) -> str:
    for pattern in ANCHOR_PATTERNS:
        match = pattern.match(heading)
        if match:
            return match.group(1)
    slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
    return slug[:48] or "section"


def _absorb_table(section: DocumentSection, lines: list[str]) -> None:
    rows = _parse_table(lines)
    if rows:
        section.tables.append(rows)


def _parse_table(lines: list[str]) -> list[dict[str, str]]:
    cells = [
        [cell.strip() for cell in TABLE_ROW.match(line).group(1).split("|")]
        for line in lines
        if TABLE_ROW.match(line) and not TABLE_DIVIDER.match(line)
    ]
    if len(cells) < 2:
        return []
    header, *body = cells
    return [dict(zip(header, row)) for row in body if any(cell for cell in row)]


def _leaf_bullets(bullets: list[str]) -> list[str]:
    """Keep bullets that state something, drop parents that only introduce their children.

    `- When a customer signs up, automatically:` is scaffolding for the three nested bullets
    underneath it; scoring it as its own requirement double-counts the same behaviour.
    """
    result: list[str] = []
    for index, bullet in enumerate(bullets):
        text = bullet.strip()
        if not text:
            continue
        indent = len(bullet) - len(bullet.lstrip())
        next_indent = None
        if index + 1 < len(bullets):
            following = bullets[index + 1]
            next_indent = len(following) - len(following.lstrip())
        has_children = next_indent is not None and next_indent > indent
        if has_children and text.endswith(":"):
            continue
        result.append(text)
    return result


def _clause(text: str, section: DocumentSection, context: str) -> DocumentClause:
    text = _strip_label(text.strip())
    return DocumentClause(
        kind=_classify(text, section),
        text=text,
        source_anchor=section.anchor,
        metadata={"section": context, "systems": _systems_in(text)},
    )


def _is_substantive(text: str) -> bool:
    """A clause has to say something. Stripping a `**Label:**` can leave nothing behind."""
    return len(text.split()) >= 2


def _strip_label(text: str) -> str:
    """Drop a leading `**Decision:**` / `**Note:**` marker but keep the sentence after it.

    Unlike a standalone `**Sponsor:** ...` metadata line, an inline label prefixes real
    requirement text, so the label is noise but the remainder is the requirement.
    """
    text = LABEL_PREFIX.sub("", text).strip()
    return text.strip("*").strip()


def _classify(text: str, section: DocumentSection) -> RequirementKind:
    lowered = text.lower()
    heading = section.heading.lower()
    if any(term in heading for term in ("exception", "error handling")) or any(
        term in lowered for term in ERROR_TERMS
    ):
        return RequirementKind.ERROR_BEHAVIOR
    if any(term in lowered for term in APPROVAL_TERMS):
        return RequirementKind.APPROVAL
    if lowered.startswith(("if ", "when ", "for ")) or " if " in lowered or "\u2192" in text:
        return RequirementKind.CONDITION
    if ENDPOINT.search(text) or "integrate with" in lowered:
        return RequirementKind.INTEGRATION
    if lowered.startswith(OUTPUT_VERBS):
        return RequirementKind.OUTPUT
    if any(term in lowered for term in TRIGGER_TERMS) and "trigger" in heading:
        return RequirementKind.TRIGGER
    if _systems_in(text):
        return RequirementKind.INTEGRATION
    return RequirementKind.ACTION


def _systems_in(text: str) -> list[str]:
    """Named systems referenced by a clause.

    Deliberately not a fixed alias list: these documents name their own integrations, and the
    nine hardcoded aliases in the alignment matcher cover none of this corpus. Kept tight on
    purpose - a bare capitalised word like "Vendors" or "Collect" is a sentence start, not a
    system, and treating it as one would classify most of a document as an integration.
    """
    found = set()
    for token in CAMEL_CASE.findall(text):
        found.add(token.lower())
    for token in ACRONYM.findall(text):
        if token not in ACRONYM_STOPWORDS:
            found.add(token.lower())
    for match in re.finditer(r"\(([^)]+)\)", text):
        inner = match.group(1).strip()
        if inner and " " not in inner and (CAMEL_CASE.fullmatch(inner) or ACRONYM.fullmatch(inner)):
            found.add(inner.lower())
    return sorted(found)


def _table_requirements(
    rows: list[dict[str, str]], section: DocumentSection
) -> tuple[list[DocumentClause], list[DocumentConstraint]]:
    if not rows:
        return [], []
    headers = list(rows[0].keys())
    first = headers[0].lower()
    clauses: list[DocumentClause] = []
    constraints: list[DocumentConstraint] = []

    if any(term in first for term in CONDITION_HEADERS):
        for row in rows:
            when = row.get(headers[0], "").strip()
            must = " ".join(row.get(header, "").strip() for header in headers[1:]).strip()
            if not when or not must:
                continue
            constraints.append(DocumentConstraint(when=when, must=must, source_anchor=section.anchor))
            clauses.append(
                DocumentClause(
                    kind=_table_condition_kind(section),
                    text=f"When {when}, {must}.",
                    source_anchor=section.anchor,
                    metadata={"section": section.heading, "table": "condition", "systems": _systems_in(must)},
                )
            )
        return clauses, constraints

    if any(term in first for term in SYSTEM_HEADERS):
        for row in rows:
            system = row.get(headers[0], "").strip()
            detail = " ".join(row.get(header, "").strip() for header in headers[1:]).strip()
            if not system:
                continue
            clauses.append(
                DocumentClause(
                    kind=RequirementKind.INTEGRATION,
                    text=f"Integrate with {system}: {detail}." if detail else f"Integrate with {system}.",
                    source_anchor=section.anchor,
                    metadata={"section": section.heading, "table": "integration", "systems": [system.lower()]},
                )
            )
        return clauses, constraints

    # Reference tables (Data Fields, Data Model) describe payload shape, not behaviour.
    return [], []


def _table_condition_kind(section: DocumentSection) -> RequirementKind:
    """An Exception/Error Handling table states failure behaviour, not business branching."""
    heading = section.heading.lower()
    if any(term in heading for term in ("exception", "error")):
        return RequirementKind.ERROR_BEHAVIOR
    return RequirementKind.CONDITION


def _detect_kind(filename: str | None, title: str) -> DocumentKind:
    haystack = f"{filename or ''} {title}".lower()
    if "_brd" in haystack or "business requirement" in haystack:
        return DocumentKind.BRD
    if "_pdd" in haystack or "process design" in haystack:
        return DocumentKind.PDD
    if "_sdd" in haystack or "solution design" in haystack or "system design" in haystack:
        return DocumentKind.SDD
    return DocumentKind.OTHER
