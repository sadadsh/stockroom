import hashlib
from pathlib import Path

import pytest

from stockroom.model.cad_variant import CadVariantArtifactPointer, CadVariantPointer
from stockroom.model.part import AssetRef, PartRecord

FIX = Path(__file__).parent / "fixtures"


def _seed(ops, pid, mpn):
    ops.lib.parts_dir.mkdir(parents=True, exist_ok=True)
    (ops.lib.parts_dir / f"{pid}.json").write_text(
        PartRecord(id=pid, display_name=pid, category="Diodes", mpn=mpn).dumps(), encoding="utf-8"
    )


def _digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _seed_installed_kicad_with_pointers(ops, pid: str):
    _seed(ops, pid, "S1M")
    record = ops.load_record(pid)
    library = ops.lib
    symbol = library.symbol_lib_path("Diodes")
    footprint = library.footprint_lib_path("Diodes") / "S1M.kicad_mod"
    model = library.models_dir / "S1M.step"
    for path in (symbol, footprint, model):
        path.parent.mkdir(parents=True, exist_ok=True)
    symbol_bytes = b'(kicad_symbol_lib (version 20240101) (symbol "S1M"))'
    footprint_bytes = b'(footprint "S1M" (version 20240108))'
    model_bytes = b"ISO-10303-21;\nEND-ISO-10303-21;\n"
    symbol.write_bytes(symbol_bytes)
    footprint.write_bytes(footprint_bytes)
    model.write_bytes(model_bytes)
    record.assets_for("kicad").symbol = AssetRef(lib="SR-Diodes", name="S1M")
    record.assets_for("kicad").footprint = AssetRef(lib="SR-Diodes", name="S1M")
    record.assets_for("kicad").model = AssetRef(file="models/S1M.step")
    record_path = library.parts_dir / f"{pid}.json"
    record_path.write_text(record.dumps(), encoding="utf-8")
    ops.repo.commit("seed installed KiCad projection", [symbol, footprint, model, record_path])

    kicad_manifest = _digest(b"installed KiCad manifest")
    kicad_pointer = CadVariantPointer(
        manifest_digest=kicad_manifest,
        provider="stockroom-library",
        artifacts={
            "symbol": CadVariantArtifactPointer(_digest(symbol_bytes), "symbol"),
            "footprint": CadVariantArtifactPointer(_digest(footprint_bytes), "footprint"),
            "model": CadVariantArtifactPointer(_digest(model_bytes), "model"),
        },
    )
    altium_pointer = CadVariantPointer(
        manifest_digest=_digest(b"composed Altium manifest"),
        provider="ultralibrarian",
        artifacts={
            "symbol": CadVariantArtifactPointer(_digest(b"SchLib"), "altium_symbol"),
            "footprint": CadVariantArtifactPointer(
                _digest(b"PcbLib"),
                "altium_footprint",
            ),
        },
        source_manifests=(kicad_manifest,),
    )
    return kicad_pointer, altium_pointer, model, record_path


def test_attach_from_loose_pair(library_ops):
    ops = library_ops
    _seed(ops, "r", "S1M")

    record = ops.attach_altium_assets("r", FIX / "sample.SchLib", FIX / "sample.PcbLib")

    altium_dir = ops.lib.parts_dir.parent / "altium"
    assert (altium_dir / "r.SchLib").exists() and (altium_dir / "r.PcbLib").exists()
    assert record.assets_for("altium").symbol.lib == "r.SchLib" and record.assets_for("altium").symbol.name == "S1M"
    assert record.assets_for("altium").footprint.lib == "r.PcbLib"
    assert record.assets_for("altium").footprint.name == "DIOM5227X270N"
    assert ops.load_record("r").assets_for("altium").symbol == record.assets_for("altium").symbol  # persisted


def test_attach_from_intlib_autoextracts(library_ops):
    ops = library_ops
    _seed(ops, "d", "S1M")

    record = ops.attach_altium_assets("d", FIX / "sample.IntLib")

    altium_dir = ops.lib.parts_dir.parent / "altium"
    assert (altium_dir / "d.SchLib").exists() and (altium_dir / "d.PcbLib").exists()
    assert record.assets_for("altium").symbol.name == "S1M"
    assert record.assets_for("altium").footprint.name == "DIOM5227X270N"
    # only loose files are stored; the .IntLib itself is not committed into the library
    assert not (altium_dir / "d.IntLib").exists()


def test_attach_rejects_symbol_only_intlib_zero_trace(library_ops):
    ops = library_ops
    _seed(ops, "x", "B6B")

    with pytest.raises(ValueError, match="Extract"):
        ops.attach_altium_assets("x", FIX / "symbol_only.IntLib")

    # zero trace: no altium dir/files created, record left untouched
    assert not (ops.lib.parts_dir.parent / "altium").exists()
    assert ops.load_record("x").assets_for("altium").symbol is None


def test_attach_refuses_multi_symbol_library_when_the_mpn_matches_none(library_ops):
    ops = library_ops
    _seed(ops, "amb", "NOMATCH")

    with pytest.raises(ValueError, match="refusing to choose by file order"):
        ops.attach_altium_assets(
            "amb",
            FIX / "multi_symbol.SchLib",
            FIX / "sample.PcbLib",
        )

    # Validation precedes directory creation and mutation: an ambiguous download leaves no trace.
    assert not (ops.lib.parts_dir.parent / "altium").exists()
    assert ops.load_record("amb").assets_for("altium").symbol is None


def test_attach_picks_the_mpn_matching_symbol_from_a_multi_symbol_lib(library_ops):
    ops = library_ops
    _seed(ops, "hir", "HIROSE_BM28_40_RECEPTACLE")

    record = ops.attach_altium_assets("hir", FIX / "multi_symbol.SchLib", FIX / "sample.PcbLib")

    assert record.assets_for("altium").symbol.name == "HIROSE_BM28_40_RECEPTACLE"  # not the alphabetical first


def test_attach_rolls_back_first_file_if_second_copy_fails(library_ops, monkeypatch):
    import shutil

    ops = library_ops
    _seed(ops, "leak", "S1M")
    real = shutil.copyfile
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:  # fail the second copy (the .PcbLib), after the .SchLib landed
            raise OSError("disk full")
        return real(src, dst)

    monkeypatch.setattr(shutil, "copyfile", flaky)
    with pytest.raises(OSError):
        ops.attach_altium_assets("leak", FIX / "sample.SchLib", FIX / "sample.PcbLib")

    # the first-copied .SchLib must NOT leak, and the record stays untouched (zero trace)
    assert not (ops.lib.parts_dir.parent / "altium" / "leak.SchLib").exists()
    assert ops.load_record("leak").assets_for("altium").symbol is None


def test_attach_prefers_the_mpn_matching_footprint_from_a_multi_footprint_lib(library_ops, monkeypatch):
    # Live 2026-07-24: a vendor PcbLib carrying several footprint variants failed the
    # attach outright because only the SYMBOL side preferred the MPN. The footprint
    # side now prefers it the same way (exact, then the one name containing it).
    import stockroom.altium.oleread as oleread

    ops = library_ops
    _seed(ops, "tpd", "S1M")
    monkeypatch.setattr(
        oleread, "read_footprint_names",
        lambda path: ["SOT-23_DENSE", "S1M_VARIANT"],
    )
    record = ops.attach_altium_assets("tpd", FIX / "sample.SchLib", FIX / "sample.PcbLib")
    assert record.assets_for("altium").footprint.name == "S1M_VARIANT"


def test_attach_accepts_a_lone_schlib_then_the_pcblib_completes_the_pair(library_ops):
    # Robustness (owner 2026-07-24): vendors can serve the SchLib and PcbLib as SEPARATE
    # downloads, and each capture forward attaches per file. A lone .SchLib lands the
    # symbol side; the later lone .PcbLib lands the footprint side WITHOUT clearing the
    # symbol already attached.
    ops = library_ops
    _seed(ops, "split", "S1M")

    first = ops.attach_altium_assets("split", FIX / "sample.SchLib")
    assert first.assets_for("altium").symbol is not None and first.assets_for("altium").symbol.name == "S1M"
    assert first.assets_for("altium").footprint is None

    second = ops.attach_altium_assets("split", FIX / "sample.PcbLib")
    assert second.assets_for("altium").footprint is not None
    assert second.assets_for("altium").footprint.name == "DIOM5227X270N"
    assert second.assets_for("altium").symbol is not None and second.assets_for("altium").symbol.name == "S1M"
    # both files stored
    altium_dir = ops.lib.parts_dir.parent / "altium"
    assert (altium_dir / "split.SchLib").exists() and (altium_dir / "split.PcbLib").exists()


def test_attach_records_where_the_altium_libraries_came_from(library_ops):
    """PROVENANCE, for the tool that did not have it.

    `attach_symbol` and `IngestPipeline.attach_assets` have recorded an origin since the owner's
    *"its not trusted where we've gotten them"*. This path had none, so a guided capture filed a
    real Altium library beside an attributed KiCad one and left it `origin: None` - the story
    holding for one tool and quietly not for the other.
    """
    from stockroom.model.asset import AssetOrigin

    ops = library_ops
    _seed(ops, "prov", "S1M")

    record = ops.attach_altium_assets(
        "prov", FIX / "sample.IntLib",
        origin=AssetOrigin(vendor="snapmagic", url="https://www.snapeda.com/parts/S1M/"),
        now_iso="2026-07-27T00:00:00Z",
    )

    for kind in ("symbol", "footprint"):
        asset = record.assets_for("altium").get(kind)
        assert asset.origin is not None, f"the altium {kind} landed unattributed"
        assert asset.origin.vendor == "snapmagic"
        assert asset.origin.url == "https://www.snapeda.com/parts/S1M/"
        # stamped HERE, never taken from a caller-chosen field on the origin itself
        assert asset.origin.captured_at == "2026-07-27T00:00:00Z"
    # and it PERSISTS - an origin that only exists on the returned object is not provenance
    reloaded = ops.load_record("prov")
    assert reloaded.assets_for("altium").get("symbol").origin.vendor == "snapmagic"


def test_attach_without_an_origin_stays_honestly_unattributed(library_ops):
    """No origin must mean `None`, never a vendor whose name is the empty string."""
    ops = library_ops
    _seed(ops, "bare", "S1M")

    record = ops.attach_altium_assets("bare", FIX / "sample.IntLib")

    assert record.assets_for("altium").get("symbol").origin is None
    assert record.assets_for("altium").get("footprint").origin is None


def test_attach_takes_the_loose_pair_when_a_bundle_carries_intlib_and_pair(library_ops):
    # Some vendor bundles ship the IntLib AND the loose pair together; the loose pair
    # wins and the IntLib fills nothing (never a refused capture over redundancy).
    ops = library_ops
    _seed(ops, "trio", "S1M")
    record = ops.attach_altium_assets(
        "trio", FIX / "sample.IntLib", FIX / "sample.SchLib", FIX / "sample.PcbLib"
    )
    assert record.assets_for("altium").symbol is not None and record.assets_for("altium").footprint is not None


def test_composed_altium_attach_atomically_adopts_only_the_exact_installed_kicad_pointer(
    library_ops,
):
    ops = library_ops
    kicad_pointer, altium_pointer, model_path, record_path = (
        _seed_installed_kicad_with_pointers(ops, "composed")
    )

    record = ops.attach_altium_assets(
        "composed",
        FIX / "sample.SchLib",
        FIX / "sample.PcbLib",
        active_variant=altium_pointer,
        compatible_kicad_variant=kicad_pointer,
    )

    assert record.cad_variants.selection_for("kicad") == kicad_pointer
    assert record.cad_variants.selection_for("altium") == altium_pointer
    persisted = ops.load_record("composed")
    assert persisted.cad_variants.selection_for("kicad") == kicad_pointer
    assert persisted.cad_variants.selection_for("altium") == altium_pointer

    altium_dir = ops.lib.parts_dir.parent / "altium"
    sch_before = (altium_dir / "composed.SchLib").read_bytes()
    pcb_before = (altium_dir / "composed.PcbLib").read_bytes()
    record_before = record_path.read_bytes()
    head_before = ops.repo.head()
    model_path.write_bytes(b"tampered installed model")

    with pytest.raises(ValueError, match="differs from the cross-EDA source manifest"):
        ops.attach_altium_assets(
            "composed",
            FIX / "sample.SchLib",
            FIX / "sample.PcbLib",
            active_variant=altium_pointer,
            compatible_kicad_variant=kicad_pointer,
        )

    assert ops.repo.head() == head_before
    assert (altium_dir / "composed.SchLib").read_bytes() == sch_before
    assert (altium_dir / "composed.PcbLib").read_bytes() == pcb_before
    assert record_path.read_bytes() == record_before
