from __future__ import annotations

from pathlib import Path

from workflow_core.canonical.models import SourceType
from workflow_core.parsers.base import ParsedWorkflow, WorkflowParser
from workflow_core.parsers.bpmn import BPMNParser
from workflow_core.parsers.errors import WorkflowParseError
from workflow_core.parsers.generic_json import GenericJSONParser
from workflow_core.parsers.n8n import N8NParser
from workflow_core.parsers.security import ALLOWED_EXTENSIONS, assert_safe_size


class ParserRegistry:
    def __init__(self, parsers: list[WorkflowParser] | None = None) -> None:
        self.parsers = parsers or []

    def register(self, parser: WorkflowParser) -> None:
        self.parsers.append(parser)

    def detect(self, filename: str, content: bytes, content_type: str | None = None) -> WorkflowParser:
        assert_safe_size(content)
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise WorkflowParseError(f"Unsupported workflow extension: {suffix or '<none>'}")
        for parser in self.parsers:
            if parser.supports(filename, content, content_type):
                return parser
        raise WorkflowParseError("No supported workflow parser could parse this file.")

    def parse(
        self,
        filename: str,
        content: bytes,
        source_type: SourceType = SourceType.UNKNOWN,
        source_prompt: str | None = None,
        content_type: str | None = None,
    ) -> ParsedWorkflow:
        parser = self.detect(filename, content, content_type)
        return parser.parse(filename, content, source_type, source_prompt, content_type)


def default_parser_registry() -> ParserRegistry:
    return ParserRegistry([BPMNParser(), N8NParser(), GenericJSONParser()])
