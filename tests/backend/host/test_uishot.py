"""Regression tests for the browser evidence harness."""

from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
UISHOT = runpy.run_path(str(ROOT / "scripts" / "uishot.py"))


def test_browser_errors_invalidate_a_screenshot_but_expected_4xx_does_not():
    classify = UISHOT["_browser_failures"]

    assert classify(
        ["uncaught render error"],
        {
            "404 GET /api/previews/model/missing.glb": 2,
            "500 GET /broken": 1,
            "FAILED GET /disconnected": 3,
        },
    ) == [
        "browser console errors (1)",
        "500 GET /broken x1",
        "FAILED GET /disconnected x3",
    ]
    assert classify([], {"404 GET /api/previews/model/missing.glb": 1}) == []


def test_surface_registry_contains_only_live_frontend_surfaces():
    choices = UISHOT["_SURFACE_CHOICES"]
    all_surfaces = UISHOT["_ALL_SURFACES"]

    # Projects and the STM viewer joined on 2026-08-06: both rail destinations render real
    # content in the seeded library (the Phase 0 audit found neither route was photographable
    # at all), so the registry naming them IS the live set, and this mirror moved with it.
    assert choices == (
        "components",
        "assets",
        "manage-models",
        "search",
        "part-vendor-data",
        "ingest",
        "projects",
        "stm",
        "settings",
        "all",
    )
    assert all_surfaces == ("components", "assets", "search", "projects", "stm", "settings")
    assert set(UISHOT["_SURFACE_ROOT"]) == set(choices) - {"all"}


def test_help_advertises_only_live_ui_surfaces():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "uishot.py"), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert (
        "{components,assets,manage-models,search,part-vendor-data,ingest,projects,stm,settings,all}"
        in result.stdout
    )
    for surface in UISHOT["_SURFACE_CHOICES"]:
        assert surface in result.stdout


def test_seed_workspace_creates_only_a_disposable_library(tmp_path: Path):
    source = tmp_path / "source-library"
    (source / "Stockroom" / "parts").mkdir(parents=True)
    (source / "README.md").write_text("source library\n", encoding="utf-8")
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    library = UISHOT["_seed_workspace"](scratch, source)

    assert library == scratch / "libraries"
    assert sorted(path.name for path in scratch.iterdir()) == ["libraries"]
    assert (library / ".git").is_dir()
    assert (library / "Stockroom" / "parts" / "vendordata.json").is_file()
