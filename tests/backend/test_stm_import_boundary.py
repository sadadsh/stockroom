"""API-04: the Qt-free + no-switch-fabric import boundary for the stm-viewer workstream's
backend surface. Two layers, both needed (the repo's convention: a CI-only bash grep alone is
not TDD-able/locally-runnable):

1. A text/regex scan of every file under app/backend/stockroom/stm/ and
   api/routers/stm.py for a PyQt/pywebview import or a banned board/switch-fabric identifier.
2. A real import-side check: `import stockroom.stm` succeeds with neither PyQt5 nor
   webview/pywebview present in sys.modules afterward - catching a transitive import a text
   grep could miss.

This is the SAME check CI runs (region-scoped, see .github/workflows/ci.yml's "Zero-Qt /
zero-pywebview import gate" step); this file makes it part of the standard local
`pytest tests/backend` gate too, and self-extends as 03-02/03-03/03-04 add files to the
package (files are discovered dynamically, never hardcoded)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import stockroom.stm

# Kept verbatim from INTERFACES.md section 6's DO-NOT-REUSE row: legitimate identifiers under
# legacy/tools/ (which this test never scans), but must never be reachable from stm/.
_BANNED_IDENTIFIERS = (
    "ADG714",
    "switch_identity",
    "classify_pin",
    "SwitchDecision",
    "TARGET_NET",
    "CELL_",
    "ZIF",
    "CoreSight",
    "lint_card",
    "fabric_drc",
)

_PYQT_PYWEBVIEW_PATTERN = re.compile(
    r"\b(PyQt5|QtCore|QtWidgets|QtGui)\b|"
    r"^\s*(import|from)\s+(py)?webview\b",
    re.MULTILINE,
)


def _target_files() -> list[Path]:
    """Every .py under the stm package dir plus api/routers/stm.py, discovered dynamically so
    this test keeps guarding files added by later plans in the phase (03-02/03-03/03-04) without
    itself needing an update."""
    stm_pkg_dir = Path(stockroom.stm.__file__).parent
    files = sorted(stm_pkg_dir.glob("*.py"))
    router_file = stm_pkg_dir.parent / "api" / "routers" / "stm.py"
    if router_file.exists():
        files.append(router_file)
    return files


def test_no_pyqt_or_pywebview_import_in_stm_files():
    for path in _target_files():
        text = path.read_text(encoding="utf-8")
        match = _PYQT_PYWEBVIEW_PATTERN.search(text)
        assert match is None, (
            f"{path}: found a PyQt/pywebview import pattern ({match.group(0)!r}) - "
            "stockroom.stm and api/routers/stm.py must stay Qt-free (API-04)"
        )


def test_no_banned_switch_fabric_identifier_in_stm_files():
    # Whole-line comments are allowed to NAME an excluded identifier for documentation
    # purposes (e.g. families.py's "NOT ported here: ... TARGET_NET ..." note) - the
    # boundary this guards is REACHABILITY (an import, a call, a definition), not the bare
    # text of the word appearing in prose. Mirrors the CI grep's own comment-line exclusion.
    for path in _target_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            for identifier in _BANNED_IDENTIFIERS:
                assert identifier not in line, (
                    f"{path}:{lineno}: found banned board/switch-fabric identifier "
                    f"{identifier!r} in code - this concept must never be reachable from "
                    "stm/ (INTERFACES.md section 6)"
                )


def test_stockroom_stm_imports_clean_of_qt_and_webview():
    # A real import-side check (not just text grep): even a transitive import of PyQt5 or
    # webview/pywebview through some indirection would show up in sys.modules afterward.
    for name in ("PyQt5", "webview", "pywebview"):
        sys.modules.pop(name, None)

    import stockroom.stm.db  # noqa: F401
    import stockroom.stm.families  # noqa: F401
    import stockroom.stm.geometry  # noqa: F401
    import stockroom.stm.source  # noqa: F401

    assert "PyQt5" not in sys.modules
    assert "webview" not in sys.modules
    assert "pywebview" not in sys.modules
