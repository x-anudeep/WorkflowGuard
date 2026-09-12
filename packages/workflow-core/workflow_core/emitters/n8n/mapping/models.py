"""What a format-specific mapping produces for one canonical node."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from workflow_core.canonical.models import Node

#: Request timeout for a redirected call when the node declares none, in milliseconds. Without a
#: timeout an injected TIMEOUT failure cannot be observed *as* a timeout - the node hangs until
#: the whole execution deadline instead of failing and retrying - so every mapping that emits an
#: HTTP node has to set one.
DEFAULT_REQUEST_TIMEOUT_MS = 2_000

#: Capped below the workflow's own execution deadline. A node that declares a 20s timeout inside
#: a run bounded at 10s would never time out on its own terms - the whole execution would be
#: stopped first, attributing the failure to the run rather than to the call that caused it.
MAX_REQUEST_TIMEOUT_MS = 8_000


@dataclass(frozen=True)
class MappedNode:
    """An n8n node type and its parameters, derived from a canonical node."""

    type: str
    type_version: float
    parameters: dict[str, Any] = field(default_factory=dict)

    #: True when this node's calls were redirected at the mock server, so the engine knows to
    #: expect it in the call log and the result mapper can attribute retries to it.
    mocked: bool = False

    #: Set when the mapping is an approximation, naming what was not reproduced. Surfaced on the
    #: run so a report never implies a node's real work was exercised when it was not.
    warning: str | None = None


def request_timeout_ms(node: Node) -> int:
    """The node's declared timeout, or a short default, clamped to something survivable."""
    declared = node.configuration.get("timeout_seconds") or node.configuration.get("timeout")
    try:
        milliseconds = int(float(declared) * 1000) if declared else DEFAULT_REQUEST_TIMEOUT_MS
    except (TypeError, ValueError):
        milliseconds = DEFAULT_REQUEST_TIMEOUT_MS
    return max(250, min(milliseconds, MAX_REQUEST_TIMEOUT_MS))
