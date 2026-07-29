"""Adversarial guard for the shared CAD-requirements/readiness path.

Native encoders necessarily differ by EDA tool.  The shared decision path must not: part class
and tool capability are registry data, and a literal tool branch there is how Stockroom formerly
made the default tool look complete while every other tool was guessed.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from stockroom.eda.registry import all_tools

ROOT = Path(__file__).resolve().parents[3]
PYTHON_SHARED = (
    ROOT / "app/backend/stockroom/model/part.py",
    ROOT / "app/backend/stockroom/model/part_class.py",
    ROOT / "app/backend/stockroom/capture/requirements.py",
    ROOT / "app/backend/stockroom/store/index.py",
)
TYPESCRIPT_SHARED = (ROOT / "app/frontend/src/lib/edaTarget.ts",)
_TOOL_VARIABLES = frozenset({"tool", "tool_key", "eda"})


def _python_literal_tool_branches(source: str) -> list[str]:
    """Literal `if tool == "..."` comparisons in executable Python syntax."""
    known = {tool.key for tool in all_tools()}
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.If, ast.IfExp)):
            continue
        for comparison in (
            child for child in ast.walk(node.test) if isinstance(child, ast.Compare)
        ):
            names = {
                child.id
                for child in ast.walk(comparison)
                if isinstance(child, ast.Name)
            }
            literals = {
                child.value
                for child in ast.walk(comparison)
                if isinstance(child, ast.Constant) and isinstance(child.value, str)
            }
            if names & _TOOL_VARIABLES and literals & known:
                found.append(ast.unparse(comparison))
    return found


def _typescript_literal_tool_branches(source: str) -> list[str]:
    """Literal tool comparisons after comments are removed.

    This intentionally targets the shared module's decision variables, not native adapter code.
    """
    uncommented = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    uncommented = re.sub(r"//[^\n]*", "", uncommented)
    known = "|".join(re.escape(tool.key) for tool in all_tools())
    variable = r"(?:tool|toolKey|eda)"
    patterns = (
        rf"\b{variable}\s*={{2,3}}\s*[\"'](?:{known})[\"']",
        rf"[\"'](?:{known})[\"']\s*={{2,3}}\s*\b{variable}\b",
    )
    return [
        match.group(0)
        for pattern in patterns
        for match in re.finditer(pattern, uncommented)
    ]


def test_the_branch_detector_rejects_known_bad_python_and_typescript_inputs():
    """Negative control: a detector that cannot go red is not acceptance evidence."""
    assert _python_literal_tool_branches(
        "def wrong(tool):\n"
        "    if tool == 'kicad':\n"
        "        return True\n"
        "    return False\n"
    ) == ["tool == 'kicad'"]
    assert _typescript_literal_tool_branches(
        'function wrong(tool: string) { return tool === "altium" ? true : false; }'
    ) == ['tool === "altium"']


def test_shared_requirements_and_readiness_have_no_literal_tool_branch():
    failures: dict[str, list[str]] = {}
    for path in PYTHON_SHARED:
        matches = _python_literal_tool_branches(path.read_text(encoding="utf-8"))
        if matches:
            failures[path.relative_to(ROOT).as_posix()] = matches
    for path in TYPESCRIPT_SHARED:
        matches = _typescript_literal_tool_branches(path.read_text(encoding="utf-8"))
        if matches:
            failures[path.relative_to(ROOT).as_posix()] = matches
    assert failures == {}, (
        "shared CAD decisions must come from part-class and EDA registry data; "
        f"literal tool branches found: {failures}"
    )
