from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_HELPER = _ROOT / "app" / "frontend" / "scripts" / "frontend-content-revision.mjs"
_VITE_CONFIG = _ROOT / "app" / "frontend" / "vite.config.ts"


def _revision(frontend_root: Path, inputs: tuple[str, ...]) -> str:
    script = (
        f"import {{ frontendContentRevision }} from {json.dumps(_HELPER.as_uri())};"
        f"console.log(frontendContentRevision({json.dumps(str(frontend_root))}, "
        f"{json.dumps(inputs)}));"
    )
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _production_environment_error(environment: dict[str, str]) -> str:
    script = (
        f"import {{ assertProductionBuildEnvironment }} from {json.dumps(_HELPER.as_uri())};"
        "try {"
        f"assertProductionBuildEnvironment({json.dumps(environment)});"
        "console.log('OK');"
        "} catch (error) { console.log(String(error.message)); }"
    )
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_frontend_content_revision_is_stable_and_sensitive_to_declared_inputs(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.ts").write_text("export const value = 1;\n", encoding="utf-8")
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    inputs = ("package-lock.json", "src")

    first = _revision(tmp_path, inputs)
    assert re.fullmatch(r"[0-9a-f]{12}", first)
    assert _revision(tmp_path, inputs) == first

    (tmp_path / "README.md").write_text("not a build input\n", encoding="utf-8")
    assert _revision(tmp_path, inputs) == first

    (tmp_path / "src" / "app.ts").write_text("export const value = 2;\n", encoding="utf-8")
    assert _revision(tmp_path, inputs) != first


def test_vite_build_identity_does_not_depend_on_the_commit_being_created() -> None:
    source = _VITE_CONFIG.read_text(encoding="utf-8")

    assert "frontendContentRevision" in source
    assert "git rev-parse" not in source
    assert "execSync" not in source


def test_production_frontend_refuses_development_or_machine_specific_inputs() -> None:
    assert _production_environment_error({}) == "OK"
    for name in (
        "STOCKROOM_DEV_BOOTSTRAP",
        "STOCKROOM_DEV_BACKEND_URL",
        "STOCKROOM_DEV_ENV_DIR",
        "VITE_API_BASE",
        "VITE_API_TOKEN",
    ):
        assert name in _production_environment_error({name: "machine-specific"})


def test_production_frontend_ignores_local_dotenv_files() -> None:
    vite_source = _VITE_CONFIG.read_text(encoding="utf-8")
    runtime_source = (
        _ROOT / "app" / "frontend" / "src" / "lib" / "runtime.ts"
    ).read_text(encoding="utf-8")

    assert 'command === "build" ? false' in vite_source
    assert "import.meta.env.DEV\n    ? (import.meta.env.VITE_API_BASE" in runtime_source


def test_production_bundle_strips_translation_only_descriptions() -> None:
    source = _VITE_CONFIG.read_text(encoding="utf-8")

    assert "stripRuntimeLocaleDescriptionsPlugin()" in source
    assert 'delete entry.description' in source
