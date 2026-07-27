from __future__ import annotations

import json
import zipfile

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
    assert body["assets"]["kicad"]["symbol"]["ref"]["name"] == "TESTPART"
    assert body["assets"]["kicad"]["footprint"]["ref"]["name"] == "TESTPART"
    assert body["assets"]["kicad"]["model"] is not None  # the snapeda fixture zip carries a .step file

    persisted = app_ctx.ops.load_record(part_id)
    assert persisted.assets_for("kicad").symbol is not None and persisted.assets_for("kicad").symbol.name == "TESTPART"
    assert persisted.assets_for("kicad").footprint is not None and persisted.assets_for("kicad").footprint.name == "TESTPART"
    assert persisted.assets_for("kicad").model is not None

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


# ------------------------------------------------------- WHERE an asset came from, over the wire
#
# Owner: *"a lot of our symbols, footprints, and 3d models are broken so its not trusted where
# we've gotten them"*. Only the guided flow knows which vendor page the person actually downloaded
# from, so the vendor and URL cross the wire; the TIMESTAMP does not.


def test_an_attach_records_the_vendor_the_capture_came_from(client, library_root):
    from stockroom.model.part import PartRecord

    resp = client.post(
        "/api/library/parts/mystery/symbol",
        json={
            "lib": "SR-ICs", "name": "MYSTERY",
            "origin": {"vendor": "ultralibrarian", "url": "https://ultralibrarian.com/x"},
        },
    )
    assert resp.status_code == 200

    rec = PartRecord.loads(
        (library_root / "Main" / "parts" / "mystery.json").read_text(encoding="utf-8")
    )
    origin = rec.assets_for("kicad").symbol.origin
    assert (origin.vendor, origin.url) == ("ultralibrarian", "https://ultralibrarian.com/x")
    assert origin.captured_at, "the server must stamp when it was captured"


def test_the_capture_TIMESTAMP_is_the_servers_and_not_the_callers(client, library_root):
    """A provenance timestamp a client can set is not evidence of anything."""
    from stockroom.model.part import PartRecord

    client.post(
        "/api/library/parts/mystery/symbol",
        json={
            "lib": "SR-ICs", "name": "MYSTERY",
            "origin": {
                "vendor": "snapmagic", "url": "https://snapeda.com/x",
                "captured_at": "1999-01-01T00:00:00Z",
            },
        },
    )

    rec = PartRecord.loads(
        (library_root / "Main" / "parts" / "mystery.json").read_text(encoding="utf-8")
    )
    assert not rec.assets_for("kicad").symbol.origin.captured_at.startswith("1999")


def test_an_attach_with_no_origin_leaves_the_asset_unattributed(client, library_root):
    """NEGATIVE CONTROL. `None` and "vendor is the empty string" are different claims, and only
    one of them is honest about an asset nobody recorded a source for."""
    from stockroom.model.part import PartRecord

    client.post(
        "/api/library/parts/mystery/footprint", json={"lib": "SR-ICs", "name": "MYSTERY"}
    )

    rec = PartRecord.loads(
        (library_root / "Main" / "parts" / "mystery.json").read_text(encoding="utf-8")
    )
    assert rec.assets_for("kicad").footprint.origin is None
