"""The duplicates surface (M6e): GET /api/duplicates groups parts that share an
MPN (a real accidental duplicate) or a footprint name (often a legitimate shared
standard footprint) so the user can review and resolve them. Read-only over the
derived index; the keep/delete resolution reuses DELETE /api/library/parts/{id}."""

from __future__ import annotations

from stockroom.api.context import AppContext

# a symbol node in the SR-ICs lib text, matching the conftest fixture shape so the
# atomic delete's _remove_symbol_node finds and removes it.
_SYMBOL_NODE = (
    '\t(symbol "{name}"\n'
    '\t\t(property "Reference" "U" (at 0 0 0))\n'
    '\t\t(property "Value" "{name}" (at 0 0 0))\n'
    '\t\t(property "Footprint" "SR-ICs:{name}" (at 0 0 0))\n'
    '\t\t(property "Datasheet" "" (at 0 0 0))\n'
    "\t)\n"
)
_FOOTPRINT = (
    '(footprint "{name}"\n'
    "\t(version 20240108)\n"
    '\t(generator "pcbnew")\n'
    '\t(layer "F.Cu")\n'
    '\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))\n'
    ")\n"
)


def _materialize(lib, name: str) -> None:
    """Append a real symbol node into the ICs symbol lib and drop a footprint file
    keyed on the symbol name, so a seeded part is genuinely deletable by the engine
    (delete_part removes the symbol node + the <name>.kicad_mod file)."""
    sym_path = lib.symbol_lib_path("ICs")
    text = sym_path.read_text(encoding="utf-8")
    assert text.rstrip().endswith(")")
    body = text.rstrip()[:-1]  # drop the trailing ")"
    sym_path.write_text(body + _SYMBOL_NODE.format(name=name) + ")\n", encoding="utf-8", newline="")
    fp_dir = lib.footprint_lib_path("ICs")
    fp_dir.mkdir(parents=True, exist_ok=True)
    (fp_dir / f"{name}.kicad_mod").write_text(_FOOTPRINT.format(name=name), encoding="utf-8", newline="")


def _seed(
    ctx: AppContext,
    part_id: str,
    *,
    mpn: str = "",
    footprint_name: str = "",
    complete: bool = False,
) -> None:
    """Write one more real, deletable PartRecord into the active profile (JSON +
    an on-disk symbol node + footprint file) and rebuild the index, so the
    duplicates endpoint (which reads the warm index) sees it and DELETE can resolve
    it. The symbol name drives the on-disk assets; footprint_name (the LibRef name)
    drives the index's footprint grouping and is kept independent."""
    from stockroom.model.part import (
        Datasheet,
        LibRef,
        ModelRef,
        PartRecord,
        Purchase,
    )

    name = part_id.upper()
    lib = ctx.profile.library
    _materialize(lib, name)
    rec = PartRecord(
        id=part_id,
        display_name=name,
        category="ICs",
        description="a part" if complete else "",
        mpn=mpn,
        manufacturer="TI" if complete else "",
    )
    rec.symbol = LibRef(lib="SR-ICs", name=name)
    if footprint_name:
        rec.footprint = LibRef(lib="SR-ICs", name=footprint_name)
    if complete:
        rec.footprint = LibRef(lib="SR-ICs", name=footprint_name or name)
        rec.model = ModelRef(file="models/x.step")
        rec.datasheet = Datasheet(file="datasheets/x.pdf")
        rec.purchase = [Purchase(vendor="LCSC", url="https://x/p")]
    (lib.parts_dir / f"{part_id}.json").write_text(rec.dumps(), encoding="utf-8")
    # commit the seed so the worktree is clean before the atomic delete runs its
    # own transaction (a dirty tree makes the engine raise GitError -> 503).
    ctx.repo.commit(f"seed duplicate fixture {part_id}", [ctx.libraries_root])
    ctx.rebuild_index()


def test_no_duplicates_is_two_empty_lists(client):
    # The seed fixture has two distinct parts (distinct MPNs, distinct footprints).
    r = client.get("/api/duplicates")
    assert r.status_code == 200
    body = r.json()
    assert body == {"by_mpn": [], "by_footprint": []}


def test_groups_parts_that_share_an_mpn(client, app_ctx):
    # a second part carrying tps62130's MPN, on its own distinct footprint
    _seed(app_ctx, "tps62130_alt", mpn="TPS62130", footprint_name="ALT_FP")
    body = client.get("/api/duplicates").json()
    assert len(body["by_mpn"]) == 1
    group = body["by_mpn"][0]
    assert group["key"] == "TPS62130"
    assert {p["id"] for p in group["parts"]} == {"tps62130", "tps62130_alt"}
    # sharing an MPN is not sharing a footprint here
    assert body["by_footprint"] == []


def test_groups_parts_that_share_a_footprint(client, app_ctx):
    # two brand new parts on the same standard footprint, each with its own MPN
    _seed(app_ctx, "r1", mpn="RES-1", footprint_name="R0402")
    _seed(app_ctx, "r2", mpn="RES-2", footprint_name="R0402")
    body = client.get("/api/duplicates").json()
    fp_groups = body["by_footprint"]
    assert len(fp_groups) == 1
    assert fp_groups[0]["key"] == "R0402"
    assert {p["id"] for p in fp_groups[0]["parts"]} == {"r1", "r2"}
    # distinct MPNs mean no MPN duplicate
    assert body["by_mpn"] == []


def test_group_lists_the_most_complete_part_first(client, app_ctx):
    # tps62130 (from the fixture) is complete; the alt sharing its MPN is not.
    _seed(app_ctx, "tps62130_alt", mpn="TPS62130", footprint_name="ALT_FP")
    group = client.get("/api/duplicates").json()["by_mpn"][0]
    ids = [p["id"] for p in group["parts"]]
    assert ids[0] == "tps62130"  # complete part is the keep-candidate, listed first
    assert ids[1] == "tps62130_alt"
    assert group["parts"][0]["is_complete"] is True
    assert group["parts"][1]["is_complete"] is False


def test_blank_mpn_and_footprint_never_group(client, app_ctx):
    # mystery (fixture) has a blank MPN; a second blank-MPN, no-footprint part must
    # not group with it, else every unfilled part would look like a duplicate.
    _seed(app_ctx, "blank", mpn="", footprint_name="")
    body = client.get("/api/duplicates").json()
    assert all(g["key"] != "" for g in body["by_mpn"])
    assert all(g["key"] != "" for g in body["by_footprint"])
    assert body == {"by_mpn": [], "by_footprint": []}


def test_deleting_a_member_resolves_the_duplicate(client, app_ctx):
    _seed(app_ctx, "tps62130_alt", mpn="TPS62130", footprint_name="ALT_FP")
    assert len(client.get("/api/duplicates").json()["by_mpn"]) == 1
    # resolve it through the existing atomic delete, then the group is gone
    assert client.delete("/api/library/parts/tps62130_alt").status_code == 204
    assert client.get("/api/duplicates").json()["by_mpn"] == []


def test_duplicates_requires_a_token(anon_client):
    assert anon_client.get("/api/duplicates").status_code == 401
