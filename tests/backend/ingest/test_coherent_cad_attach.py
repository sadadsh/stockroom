from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from stockroom.ingest.errors import IngestError
from stockroom.ingest.pipeline import IngestPipeline
from stockroom.ingest.staging import StagingCandidate
from stockroom.model.cad_variant import CadVariantArtifactPointer, CadVariantPointer
from stockroom.model.part import PartRecord
from stockroom.store.profile import ProfileStore
from stockroom.vcs.repo import GitRepo

_ALTIUM = Path(__file__).parents[1] / "altium" / "fixtures"


def _digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _setup(tmp_path: Path, fixtures_dir: Path):
    repo = GitRepo(tmp_path / "repo")
    repo.init()
    seed = repo.root / "seed"
    seed.write_text("seed", encoding="utf-8")
    repo.commit("seed", [seed])
    profile = ProfileStore(repo.root / "libraries", repo).create("Main")
    record = PartRecord(
        id="pair",
        display_name="Pair",
        category="ICs",
        manufacturer="Texas Instruments",
        mpn="S1M",
    )
    record_path = profile.library.parts_dir / "pair.json"
    record_path.write_text(record.dumps(), encoding="utf-8")
    symbol_target = profile.library.symbol_lib_path("ICs")
    symbol_target.parent.mkdir(parents=True, exist_ok=True)
    symbol_target.write_text(
        "(kicad_symbol_lib (version 20240101) (generator stockroom))\n",
        encoding="utf-8",
    )
    repo.commit("seed pair", [record_path, symbol_target])

    symbol = tmp_path / "Source.kicad_sym"
    footprint = tmp_path / "Source.kicad_mod"
    model = tmp_path / "Source.step"
    shutil.copy2(fixtures_dir / "one_symbol.kicad_sym", symbol)
    shutil.copy2(fixtures_dir / "one_footprint.kicad_mod", footprint)
    model.write_bytes(b"ISO-10303-21;\nEND-ISO-10303-21;\n")
    candidate = StagingCandidate(
        vendor="ultralibrarian",
        symbol_lib_path=symbol,
        symbol_name="TESTPART",
        footprint_variants=[footprint],
        model_path=model,
        entry_name="S1M",
        category="ICs",
        manufacturer=record.manufacturer,
        mpn=record.mpn,
    )
    kicad_manifest = _digest(b"retained KiCad")
    kicad_pointer = CadVariantPointer(
        manifest_digest=kicad_manifest,
        provider="ultralibrarian",
        artifacts={
            "symbol": CadVariantArtifactPointer(_digest(symbol.read_bytes()), "symbol"),
            "footprint": CadVariantArtifactPointer(
                _digest(footprint.read_bytes()),
                "footprint",
            ),
            "model": CadVariantArtifactPointer(_digest(model.read_bytes()), "model"),
        },
    )
    altium_pointer = CadVariantPointer(
        manifest_digest=_digest(b"derived Altium"),
        provider="digikey-ultralibrarian",
        artifacts={
            "symbol": CadVariantArtifactPointer(
                _digest((_ALTIUM / "sample.SchLib").read_bytes()),
                "altium_symbol",
            ),
            "footprint": CadVariantArtifactPointer(
                _digest((_ALTIUM / "sample.PcbLib").read_bytes()),
                "altium_footprint",
            ),
        },
        source_manifests=(kicad_manifest,),
    )
    return (
        IngestPipeline(profile, repo, cli=None),
        candidate,
        kicad_pointer,
        altium_pointer,
        record_path,
    )


def test_coherent_pair_materializes_in_one_commit(tmp_path: Path, fixtures_dir: Path) -> None:
    pipeline, candidate, kicad_pointer, altium_pointer, _ = _setup(
        tmp_path,
        fixtures_dir,
    )
    before = pipeline.repo.head()

    record = pipeline.attach_coherent_cad_assets(
        "pair",
        candidate,
        _ALTIUM / "sample.SchLib",
        _ALTIUM / "sample.PcbLib",
        kicad_origin=None,
        altium_origin=None,
        now_iso="2026-07-29T00:00:00Z",
        kicad_active_variant=kicad_pointer,
        altium_active_variant=altium_pointer,
    )

    assert pipeline.repo.count_commits(before, pipeline.repo.head()) == 1
    assert record.cad_variants.selection_for("kicad") == kicad_pointer
    assert record.cad_variants.selection_for("altium") == altium_pointer
    persisted = pipeline.ops.load_record("pair")
    assert persisted.cad_variants == record.cad_variants
    assert pipeline.repo.is_clean(
        [
            pipeline.profile.library.parts_dir / "pair.json",
            pipeline.profile.library.symbol_lib_path("ICs"),
            pipeline.profile.library.footprint_lib_path("ICs") / "S1M.kicad_mod",
            pipeline.profile.library.models_dir / "S1M.step",
            pipeline.profile.library.parts_dir.parent / "altium" / "pair.SchLib",
            pipeline.profile.library.parts_dir.parent / "altium" / "pair.PcbLib",
        ]
    )


def test_coherent_pair_rolls_back_kicad_when_altium_copy_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fixtures_dir: Path,
) -> None:
    pipeline, candidate, kicad_pointer, altium_pointer, record_path = _setup(
        tmp_path,
        fixtures_dir,
    )
    before = pipeline.repo.head()
    record_before = record_path.read_bytes()
    real_copy = shutil.copyfile

    def fail_pcblib(source, destination):
        if Path(destination).suffix.casefold() == ".pcblib":
            raise OSError("simulated Altium write failure")
        return real_copy(source, destination)

    monkeypatch.setattr(shutil, "copyfile", fail_pcblib)
    with pytest.raises(OSError, match="simulated Altium write failure"):
        pipeline.attach_coherent_cad_assets(
            "pair",
            candidate,
            _ALTIUM / "sample.SchLib",
            _ALTIUM / "sample.PcbLib",
            kicad_origin=None,
            altium_origin=None,
            now_iso="2026-07-29T00:00:00Z",
            kicad_active_variant=kicad_pointer,
            altium_active_variant=altium_pointer,
        )

    assert pipeline.repo.head() == before
    assert record_path.read_bytes() == record_before
    assert not (pipeline.profile.library.footprint_lib_path("ICs") / "S1M.kicad_mod").exists()
    assert not (pipeline.profile.library.models_dir / "S1M.step").exists()
    assert not (pipeline.profile.library.parts_dir.parent / "altium").exists()
    assert pipeline.repo.status_porcelain() == []


def test_coherent_pair_refuses_and_preserves_dirty_exact_target(
    tmp_path: Path,
    fixtures_dir: Path,
) -> None:
    pipeline, candidate, kicad_pointer, altium_pointer, record_path = _setup(
        tmp_path,
        fixtures_dir,
    )
    before = pipeline.repo.head()
    dirty = record_path.read_text(encoding="utf-8") + "\n"
    record_path.write_text(dirty, encoding="utf-8")

    with pytest.raises(IngestError, match="exact target has uncommitted changes"):
        pipeline.attach_coherent_cad_assets(
            "pair",
            candidate,
            _ALTIUM / "sample.SchLib",
            _ALTIUM / "sample.PcbLib",
            kicad_origin=None,
            altium_origin=None,
            now_iso="2026-07-29T00:00:00Z",
            kicad_active_variant=kicad_pointer,
            altium_active_variant=altium_pointer,
        )

    assert pipeline.repo.head() == before
    assert record_path.read_text(encoding="utf-8") == dirty
    assert pipeline.repo.dirty_paths() == [record_path]
