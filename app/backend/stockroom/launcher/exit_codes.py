"""Exit codes shared between the windowed host and the frozen launcher (M9d).

A LEAF module with zero heavy imports on purpose: the frozen launcher imports EXIT_RESTART
from here, NOT from stockroom.host.run (which drags the whole FastAPI app), so PyInstaller
bundles only the tiny launcher, never the full backend. The host env lives in the git
working copy the launcher runs via `uv run`, not inside the frozen exe.
"""

from __future__ import annotations

# The host exits with this when a self-update restart was requested (git pull + uv sync
# already ran); the launcher recognizes it and relaunches on the freshly pulled code.
EXIT_RESTART = 42
