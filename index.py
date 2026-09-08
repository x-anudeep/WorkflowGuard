"""Vercel Python runtime entrypoint for the WorkflowGuard API.

Vercel's FastAPI preset looks for a top-level ``app`` in one of app.py,
index.py, server.py, main.py, wsgi.py or asgi.py at the project root, and
then routes every path to it. That is the whole reason the API is reachable
on Vercel, and why there are no rewrites to configure. The application
itself lives in apps/api; this file only re-exports it.

requirements.txt installs both local packages properly. The sys.path append
below is a fallback for the case where that install changes shape: the
source tree is bundled either way, so the import still resolves. It appends
rather than inserts so an installed distribution always wins over it.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SOURCES = (_ROOT / "packages" / "workflow-core", _ROOT / "apps" / "api")
for _candidate in _SOURCES:
    _path = str(_candidate)
    if _path not in sys.path:
        sys.path.append(_path)

from workflowguard_api.main import app  # noqa: E402

__all__ = ["app"]
