"""The repository-wide type boundary is a required gate, not an advisory command."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TYPE_TARGET = "app/backend/stockroom"


def _windows_gate_violations(text: str) -> list[str]:
    violations: list[str] = []
    required = (
        ("backend-type-stage", "Invoke-Checked 'Backend Type Check'"),
        ("backend-type-command", "& uv run ty check app\\backend\\stockroom"),
        ("actionlint-stage", "Invoke-Checked 'GitHub Actions Workflows'"),
        (
            "actionlint-resolution",
            "Get-Command actionlint -CommandType Application -ErrorAction SilentlyContinue",
        ),
        (
            "actionlint-command",
            "& $actionlint.Source .github\\workflows\\ci.yml .github\\workflows\\release.yml",
        ),
        ("native-test-stage", "Invoke-Checked 'Native Window Host Tests'"),
        (
            "native-locked-restore",
            "tests\\native\\Stockroom.WindowHost.Tests\\Stockroom.WindowHost.Tests.csproj `\n"
            "            --locked-mode",
        ),
        ("native-no-restore-test", "--configuration Release `\n            --no-restore"),
    )
    for name, contract in required:
        if contract not in text:
            violations.append(name)
    return violations


def _shell_gate_violations(text: str) -> list[str]:
    violations: list[str] = []
    types_command = 'run "ty" .venv/bin/ty check app/backend/stockroom'
    if f"types)    {types_command}" not in text:
        violations.append("types-route")
    if "  all)" not in text or "  *)" not in text:
        violations.append("all-route")
        all_block = ""
    else:
        all_block = text.split("  all)", 1)[1].split("  *)", 1)[0]
    if types_command not in all_block:
        violations.append("all-types-command")
    if "advisory" in text.casefold():
        violations.append("advisory-type-check")
    return violations


def _ci_violations(text: str) -> list[str]:
    violations: list[str] = []
    required = (
        ("type-step", "name: Type check backend"),
        ("type-command", f"run: uv run ty check {TYPE_TARGET}"),
        ("frozen-sync", "uv sync --frozen"),
        ("readonly-checkout", "persist-credentials: false"),
        ("readonly-permissions", "permissions:\n  contents: read"),
        ("native-sdk-step", "name: Install Pinned .NET SDK"),
        ("native-sdk-version", 'dotnet-version: "10.0.302"'),
        ("native-test-step", "name: Run Native Window Host Suite"),
        ("native-locked-restore", "dotnet restore $project --locked-mode --nologo"),
        ("native-no-restore-test", "--configuration Release --no-restore --nologo"),
    )
    for name, contract in required:
        if contract not in text:
            violations.append(name)
    if (
        "actions/checkout@v" in text
        or "astral-sh/setup-uv@v" in text
        or "actions/setup-dotnet@v" in text
    ):
        violations.append("floating-action-ref")
    return violations


def test_windows_gate_enforces_types_and_workflow_validation() -> None:
    text = (ROOT / "scripts" / "Gates.ps1").read_text(encoding="utf-8")

    assert _windows_gate_violations(text) == []


def test_shell_all_gate_enforces_backend_types() -> None:
    text = (ROOT / "scripts" / "gates.sh").read_text(encoding="utf-8")

    assert _shell_gate_violations(text) == []


def test_ci_enforces_backend_types() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert _ci_violations(text) == []


def test_windows_detector_rejects_label_only_known_bad_gate() -> None:
    known_bad = """
    Invoke-Checked 'Backend Type Check' { & uv run ruff check app\\backend\\stockroom }
    Invoke-Checked 'GitHub Actions Workflows' { Write-Output 'looks valid' }
    """

    assert _windows_gate_violations(known_bad) == [
        "backend-type-command",
        "actionlint-resolution",
        "actionlint-command",
        "native-test-stage",
        "native-locked-restore",
        "native-no-restore-test",
    ]


def test_shell_detector_rejects_an_advisory_or_omitted_all_route() -> None:
    known_bad = """
      types)    run "ty" .venv/bin/ty check app/backend/stockroom ;;
      all)
        run "ruff" .venv/bin/ruff check app/backend/stockroom
        echo "ty is advisory"
        ;;
      *) exit 2 ;;
    """

    assert _shell_gate_violations(known_bad) == [
        "all-types-command",
        "advisory-type-check",
    ]


def test_ci_detector_rejects_a_named_but_non_enforcing_type_step() -> None:
    known_bad = """
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: true
      - name: Type check backend
        run: echo "type check skipped"
    """

    assert _ci_violations(known_bad) == [
        "type-command",
        "frozen-sync",
        "readonly-checkout",
        "readonly-permissions",
        "native-sdk-step",
        "native-sdk-version",
        "native-test-step",
        "native-locked-restore",
        "native-no-restore-test",
        "floating-action-ref",
    ]
