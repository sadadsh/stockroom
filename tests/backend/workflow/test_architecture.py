import ast
from pathlib import Path

WORKFLOW_ROOT = Path(__file__).resolve().parents[3] / "app" / "backend" / "stockroom" / "workflow"
FORBIDDEN_PREFIXES = (
    "stockroom.api.jobs",
    "stockroom.model",
    "stockroom.capture",
    "stockroom.enrich",
    "stockroom.ingest",
    "pickle",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_workflow_foundation_cannot_import_legacy_orchestration_or_pickle():
    offenders: list[str] = []
    for path in sorted(WORKFLOW_ROOT.glob("*.py")):
        for imported in _imports(path):
            if any(
                imported == prefix or imported.startswith(f"{prefix}.")
                for prefix in FORBIDDEN_PREFIXES
            ):
                offenders.append(f"{path.name}: {imported}")

    assert offenders == []
