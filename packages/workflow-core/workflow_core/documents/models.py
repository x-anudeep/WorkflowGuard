from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from workflow_core.evaluation.models import RequirementKind


class DocumentKind(StrEnum):
    """The flavour of requirement document, detected from the filename or the H1."""

    BRD = "brd"
    PDD = "pdd"
    SDD = "sdd"
    OTHER = "other"


class DocumentClause(BaseModel):
    """One atomic, scoreable requirement lifted out of a document.

    A clause is already the unit the evaluator should match against, so it never goes
    through ``_split_prompt``: splitting a document on punctuation is what turns a 2.8 KB
    BRD into 70 spurious requirements.
    """

    id: str = Field(default_factory=lambda: f"clause_{uuid4().hex[:10]}")
    kind: RequirementKind
    text: str
    source_anchor: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(use_enum_values=True)


class DocumentConstraint(BaseModel):
    """A conditional rule read out of a decision-matrix table."""

    when: str
    must: str
    source_anchor: str

    model_config = ConfigDict(use_enum_values=True)


class DocumentSection(BaseModel):
    """A heading and everything under it, until the next heading of the same or higher level."""

    heading: str
    level: int
    anchor: str
    body: str = ""
    bullets: list[str] = Field(default_factory=list)
    tables: list[list[dict[str, str]]] = Field(default_factory=list)
    #: False for context/boilerplate sections that are kept for display but never scored.
    scored: bool = True

    model_config = ConfigDict(use_enum_values=True)


class RequirementDocument(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    kind: DocumentKind = DocumentKind.OTHER
    title: str = ""
    filename: str | None = None
    sections: list[DocumentSection] = Field(default_factory=list)
    clauses: list[DocumentClause] = Field(default_factory=list)
    constraints: list[DocumentConstraint] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(use_enum_values=True)
