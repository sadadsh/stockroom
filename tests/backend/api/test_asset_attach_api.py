from __future__ import annotations

import json
import zipfile

import pytest

from stockroom.model.part import Datasheet, PartRecord, Purchase
from tests.backend.conftest import requires_kicad_cli

pytestmark = requires_kicad_cli


def _drain_job(client, job_id):
    kind = None
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        for line in s.iter_lines():
            line = line.strip()
            if line.startswith("event:"):
                kind = line[len("event:"):].strip()
            elif line.startswith("data:") and kind in ("result", "error"):
                data = json.loads(line[len("data:"):].strip())
                if kind == "result":
                    return {"status": "done", "result": data["result"]}
                return {"status": "error", "result": data}
    return None


def _snapeda_zip(tmp_path, fixtures_dir, name="part.zip"):
    z = tmp_path / name
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(fixtures_dir / "one_symbol.kicad_sym", "MyPart.kicad_sym")
        zf.write(fixtures_dir / "one_footprint.kicad_mod", "MyPart.kicad_mod")
        zf.writestr("MyPart.step", "ISO-10303-21;\n")
    return z


def _land_bare_part(app_ctx) -> str:
    """A part that already exists (identity + sourcing only, no KiCad assets), the
    way add_reference_part lands a whole-BOM import; its assets get attached
    afterward through the routes under test."""
    record = PartRecord(
        id="",
        display_name="TESTPART",
        category="ICs",
        description="a test part",
        mpn="TESTPART",
        manufacturer="Acme",
        datasheet=Datasheet(source_url="https://example.com/testpart.pdf"),
        purchase=[Purchase(vendor="Mouser", url="https://mouser.com/p/1")],
    )
    landed = app_ctx.ops.add_reference_part(record)
    app_ctx.rebuild_index()  # so ctx.index.get(part_id) sees the freshly-landed part
    return landed.id


def test_inspect_and_commit_assets_onto_an_existing_part(client, app_ctx, tmp_path, fixtures_dir):
    part_id = _land_bare_part(app_ctx)
    z = _snapeda_zip(tmp_path, fixtures_dir)

    r = client.post(f"/api/parts/{part_id}/assets/inspect", json={"paths": [str(z)]})
    assert r.status_code == 200
    event = _drain_job(client, r.json()["job_id"])
    assert event["status"] == "done"
    [candidate] = event["result"]
    assert candidate["symbol_name"] == "TESTPART"
    candidate["entry_name"] = "TESTPART"

    r = client.post(f"/api/parts/{part_id}/assets/commit", json=candidate)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["symbol"]["name"] == "TESTPART"
    assert body["footprint"]["name"] == "TESTPART"
    assert body["model"] is not None  # the snapeda fixture zip carries a .step file

    persisted = app_ctx.ops.load_record(part_id)
    assert persisted.symbol is not None and persisted.symbol.name == "TESTPART"
    assert persisted.footprint is not None and persisted.footprint.name == "TESTPART"
    assert persisted.model is not None

    sym_path = app_ctx.profile.library.symbol_lib_path("ICs")
    fp_path = app_ctx.profile.library.footprint_lib_path("ICs") / "TESTPART.kicad_mod"
    assert fp_path.exists()
    from stockroom.kicad.symbol_lib import SymbolLib

    assert "TESTPART" in SymbolLib.load(sym_path).symbol_names


def test_inspect_for_an_unknown_part_is_an_honest_404(client, tmp_path):
    r = client.post("/api/parts/does-not-exist/assets/inspect", json={"paths": [str(tmp_path)]})
    assert r.status_code == 404
    assert r.json()["error"] == "FileNotFoundError"


def test_commit_for_an_unknown_part_is_an_honest_404(client):
    r = client.post("/api/parts/does-not-exist/assets/commit", json={
        "vendor": "snapeda", "symbol_lib_path": None, "symbol_name": "",
        "footprint_variants": [], "category": "ICs",
    })
    assert r.status_code == 404
    assert r.json()["error"] == "FileNotFoundError"
