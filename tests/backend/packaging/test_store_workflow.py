from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[3]


def _workflow(name: str) -> tuple[str, dict[str, Any]]:
    text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    return text, yaml.load(text, Loader=yaml.BaseLoader)


def test_store_workflow_builds_private_unsigned_candidate_after_ci() -> None:
    text, workflow = _workflow("store.yml")
    assert workflow["permissions"] == {}
    assert workflow["on"] == {"workflow_dispatch": ""}
    assert workflow["jobs"]["quality-gate"]["uses"] == "./.github/workflows/ci.yml"
    build = workflow["jobs"]["build-store-package"]
    assert build["needs"] == "quality-gate"
    assert build["permissions"] == {"contents": "read"}
    assert "-Mode Store" in text
    assert "WINDOWS_CERT" not in text
    assert "STOCKROOM_TUF" not in text
    assert "gh release" not in text
    assert "retention-days: 14" in text
    assert "1.0.${{ github.run_number }}.0" in text


def test_pages_workflow_deploys_only_public_store_site() -> None:
    text, workflow = _workflow("pages.yml")
    assert "path: store-site" in text
    assert "app/frontend-dist" not in text
    assert workflow["permissions"] == {"contents": "read"}
    deploy = workflow["jobs"]["deploy"]
    assert deploy["permissions"] == {"pages": "write", "id-token": "write"}


def test_store_workflows_pin_every_external_action() -> None:
    references: list[str] = []
    for name in ("store.yml", "pages.yml"):
        text, _workflow_value = _workflow(name)
        references.extend(re.findall(r"uses:\s*([^\s#]+)", text))
    external = [value for value in references if not value.startswith("./")]
    assert external
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", value) for value in external)
