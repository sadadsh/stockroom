"""Application updates automatically apply deterministic presentation rules."""

from __future__ import annotations

import json

from stockroom.api.context import build_context
from stockroom.model.derived import DERIVED_BY
from stockroom.model.part import PartRecord
from stockroom.model.sourced import SourceEntry, source_rel_path
from stockroom.store.machine_config import MachineConfig


def test_context_build_rederives_stale_evidence_and_refreshes_the_live_index(
    library_root, tmp_path
):
    profile = library_root / "Main"
    path = profile / "parts" / "tps62130.json"
    rec = PartRecord.loads(path.read_text(encoding="utf-8"))
    rec.derived_by = "rules@2"
    rec.description = "OLD DESCRIPTION"

    sourced = profile / "sourced" / rec.id
    sourced.mkdir(parents=True, exist_ok=True)
    (sourced / "mouser.json").write_text(
        json.dumps(
            {
                "SearchResults": {
                    "Parts": [
                        {
                            "ManufacturerProductNumber": rec.mpn,
                            "Manufacturer": rec.manufacturer,
                            "MouserPartNumber": f"595-{rec.mpn}",
                            "Description": "Switching Regulators Short Cat Text",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    (sourced / "digikey.json").write_text(
        json.dumps(
            {
                "Products": [
                    {
                        "ManufacturerProductNumber": rec.mpn,
                        "Manufacturer": {"Name": rec.manufacturer},
                        "Description": {
                            "DetailedDescription": (
                                "3A synchronous step-down converter with adjustable output"
                            )
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    rec.sources["mouser"] = SourceEntry(
        fetched_at="2026-07-29T00:00:00Z",
        file=source_rel_path(rec.id, "mouser"),
    )
    rec.sources["digikey"] = SourceEntry(
        fetched_at="2026-07-29T00:00:00Z",
        file=source_rel_path(rec.id, "digikey"),
    )
    path.write_text(rec.dumps(), encoding="utf-8")

    ctx = build_context(
        library_root,
        kicad_dir=tmp_path / "kicad-auto-derive",
        config=MachineConfig(active_profile="Main"),
        token="T",
    )
    try:
        stored = PartRecord.loads(path.read_text(encoding="utf-8"))
        assert ctx.last_derivation is not None
        assert ctx.last_derivation["rewritten"] == 1
        assert stored.derived_by == DERIVED_BY
        assert stored.description == (
            "3A synchronous step-down converter with adjustable output"
        )
        assert [row.id for row in ctx.index.search("adjustable output")] == [rec.id]
    finally:
        ctx.close()
