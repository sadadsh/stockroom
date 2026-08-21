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
        ("kicad-native-only", "@('.cmd', '.bat') -contains ("),
        ("kicad-extension-check", "[System.IO.Path]::GetExtension($command.Source)"),
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
        ("ruff-step", "name: Run Ruff"),
        ("ruff-command", "uv run ruff check app/backend scripts tests"),
        ("readonly-checkout", "persist-credentials: false"),
        ("readonly-permissions", "permissions:\n  contents: read"),
        ("actionlint-step", "name: Validate workflows with pinned actionlint"),
        (
            "actionlint-archive",
            "actionlint_1.7.12_windows_amd64.zip",
        ),
        (
            "actionlint-sha256",
            "6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9",
        ),
        (
            "actionlint-command",
            "& $actionlint .github/workflows/ci.yml .github/workflows/release.yml",
        ),
        ("native-sdk-step", "name: Install Pinned .NET SDK"),
        ("native-sdk-version", 'dotnet-version: "10.0.302"'),
        ("native-test-step", "name: Run Native Window Host Suite"),
        ("native-locked-restore", "dotnet restore $project --locked-mode --nologo"),
        ("native-no-restore-test", "--configuration Release --no-restore --nologo"),
        (
            "hosted-runner-excludes-workstation-performance-budget",
            "not live_enrich and (global_windows_mutex or serial_only) and not performance_budget",
        ),
        ("frontend-install-step", "name: Install frontend dependencies"),
        ("frontend-frozen-install", "npm.cmd --prefix app/frontend ci"),
        ("frontend-test-step", "name: Run frontend suite"),
        ("frontend-test-command", "npm.cmd --prefix app/frontend run test:run -- --maxWorkers=1"),
        ("frontend-type-step", "name: Type check frontend"),
        ("frontend-type-command", "npm.cmd --prefix app/frontend run typecheck"),
        ("frontend-build-step", "name: Verify production build and committed distribution"),
        ("frontend-build-command", "npm.cmd --prefix app/frontend run build"),
        ("frontend-dist-status", "git status --porcelain --untracked-files=all -- app/frontend-dist"),
        ("package-fixture-step", "name: Run Windows package fixture"),
        ("package-fixture-command", r".\packaging\Build-Windows-Package.ps1 `"),
        ("package-fixture-mode", "-Mode Fixture `"),
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


def test_main_push_runs_the_canonical_gate_only_through_release() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    trigger = text.split("permissions:", 1)[0]

    assert "  pull_request:" in trigger
    assert "  workflow_call:" in trigger
    assert "  push:" not in trigger


def test_scale_wall_clock_acceptance_is_workstation_only() -> None:
    text = (ROOT / "tests/backend/planning/test_scale_simulation.py").read_text(
        encoding="utf-8"
    )

    assert "@pytest.mark.performance_budget\n@pytest.mark.parametrize" in text


def test_ci_initializes_every_native_cad_converter_source() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "shared/OriginalCircuit.Eda.Abstractions" in text
    assert "shared/OriginalCircuit.Eda.Rendering" in text
    assert "b24200f06618cecd36f42ff966e9db9ea9491f35" in text


def test_release_repository_excludes_personal_editor_tooling() -> None:
    frontend = ROOT / "app" / "frontend"
    assert list(frontend.glob("**/SKILL.md")) == []
    assert not (ROOT / "doctor.config.jsonc").exists()
    assert not (ROOT / "scripts" / "workflows" / "rebuild-library.js").exists()


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
        "kicad-native-only",
        "kicad-extension-check",
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
        "ruff-step",
        "ruff-command",
        "readonly-checkout",
        "readonly-permissions",
        "actionlint-step",
        "actionlint-archive",
        "actionlint-sha256",
        "actionlint-command",
        "native-sdk-step",
        "native-sdk-version",
        "native-test-step",
        "native-locked-restore",
        "native-no-restore-test",
        "hosted-runner-excludes-workstation-performance-budget",
        "frontend-install-step",
        "frontend-frozen-install",
        "frontend-test-step",
        "frontend-test-command",
        "frontend-type-step",
        "frontend-type-command",
        "frontend-build-step",
        "frontend-build-command",
        "frontend-dist-status",
        "package-fixture-step",
        "package-fixture-command",
        "package-fixture-mode",
        "floating-action-ref",
    ]
