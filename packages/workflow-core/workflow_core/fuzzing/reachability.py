"""Backwards-compatible re-export.

The reachability solver moved to :mod:`workflow_core.analysis.reachability` so the test
generator can use it too; `testing` importing from `fuzzing` would have been a cycle, since
`fuzzing` builds on the simulator in `testing`.
"""

from workflow_core.analysis.reachability import (
    path_to,
    reaching_input,
    satisfying_state,
)

__all__ = ["path_to", "reaching_input", "satisfying_state"]
