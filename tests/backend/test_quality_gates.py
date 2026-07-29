"""The repository-wide type boundary is a required gate, not an advisory command."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TYPE_TARGET = "app/backend/stockroom"


def test_windows_gate_enforces_backend_types() -> None:
    text = (ROOT / "scripts" / "Gates.ps1").read_text(encoding="utf-8")

    assert "Invoke-Checked 'Backend Type Check'" in text
    assert "& uv run ty check app\\backend\\stockroom" in text


def test_windows_gate_enforces_github_actions_validation() -> None:
    text = (ROOT / "scripts" / "Gates.ps1").read_text(encoding="utf-8")

    assert "Invoke-Checked 'GitHub Actions Workflows'" in text
    assert "Get-Command actionlint -CommandType Application" in text
    assert "& $actionlint.Source .github\\workflows\\ci.yml .github\\workflows\\release.yml" in text


def test_shell_all_gate_enforces_backend_types() -> None:
    text = (ROOT / "scripts" / "gates.sh").read_text(encoding="utf-8")

    assert 'types)    run "ty" .venv/bin/ty check app/backend/stockroom' in text
    all_block = text.split("  all)", 1)[1].split("  *)", 1)[0]
    assert 'run "ty" .venv/bin/ty check app/backend/stockroom' in all_block
    assert "advisory" not in text


def test_ci_enforces_backend_types() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "name: Type check backend" in text
    assert f"run: uv run ty check {TYPE_TARGET}" in text
    assert "uv sync --frozen" in text
    assert "persist-credentials: false" in text
    assert "permissions:\n  contents: read" in text
    assert "actions/checkout@v" not in text
    assert "astral-sh/setup-uv@v" not in text
