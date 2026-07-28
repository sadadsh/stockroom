from pathlib import Path

import pytest

from stockroom.model.part import PartRecord

FIX = Path(__file__).parent / "fixtures"


def _seed(ops, pid, mpn):
    ops.lib.parts_dir.mkdir(parents=True, exist_ok=True)
    (ops.lib.parts_dir / f"{pid}.json").write_text(
        PartRecord(id=pid, display_name=pid, category="Diodes", mpn=mpn).dumps(), encoding="utf-8"
    )


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


def test_attach_binds_the_first_symbol_when_the_mpn_matches_none(library_ops):
    # permissive by owner directive (2026-07-24): a multi-symbol lib with no MPN match
    # binds its first entry instead of refusing the capture (the lib is stored verbatim
    # and the binding is re-attachable).
    ops = library_ops
    _seed(ops, "amb", "NOMATCH")
    record = ops.attach_altium_assets("amb", FIX / "multi_symbol.SchLib", FIX / "sample.PcbLib")
    assert record.assets_for("altium").symbol is not None
    assert record.assets_for("altium").symbol.name  # bound to a real entry, never empty


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
