from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class VersionComparison(BaseModel):
    workflow_a_id: str
    workflow_b_id: str
    nodes_added: list[str] = Field(default_factory=list)
    nodes_removed: list[str] = Field(default_factory=list)
    edges_added: list[str] = Field(default_factory=list)
    edges_removed: list[str] = Field(default_factory=list)
    configuration_changed: list[str] = Field(default_factory=list)
    validation_score_delta: float | None = None
    prompt_alignment_delta: float | None = None
    security_delta: float | None = None
    reliability_delta: float | None = None
    test_coverage_delta: float | None = None
    estimated_cost_delta: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
