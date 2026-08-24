from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from workflow_core.canonical.models import SourceType, Workflow


@dataclass(frozen=True)
class ParsedWorkflow:
    workflow: Workflow
    raw_content: str
    content_type: str | None = None


class WorkflowParser(ABC):
    format_name: str
    extensions: set[str]

    def supports(self, filename: str, content: bytes, content_type: str | None = None) -> bool:
        suffix = Path(filename).suffix.lower()
        return suffix in self.extensions and self.validate_source(content)

    @abstractmethod
    def validate_source(self, content: bytes) -> bool:
        raise NotImplementedError

    @abstractmethod
    def parse(
        self,
        filename: str,
        content: bytes,
        source_type: SourceType = SourceType.UNKNOWN,
        source_prompt: str | None = None,
        content_type: str | None = None,
    ) -> ParsedWorkflow:
        raise NotImplementedError
