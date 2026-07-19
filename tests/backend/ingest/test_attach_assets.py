import shutil
import zipfile

import pytest

from stockroom.ingest.pipeline import IngestPipeline
from stockroom.kicad.footprint import Footprint
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.model.part import Datasheet, PartRecord, Purchase
from stockroom.store.profile import ProfileStore
from stockroom.vcs.repo import GitRepo
from tests.backend.conftest import requires_kicad_cli

pytestmark = [
    pytest.mark.skipif(shutil.which("git") is None, reason="git not installed"),
    requires_kicad_cli,
]


def _pipeline(tmp_path):
    from stockroom.kicad.cli import KiCadCli

    repo = GitRepo(tmp_path / "repo")
    repo.init()
    (repo.root / "seed").write_text("x")
    repo.commit("seed", [repo.root / "seed"])
    store = ProfileStore(repo.root / "libraries", repo)
    profile = store.create("Main")
    return IngestPipeline(profile, repo, KiCadCli())


def _snapeda_zip(tmp_path, fixtures_dir, name="part.zip", with_datasheet=False):
    z = tmp_path / name
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(fixtures_dir / "one_symbol.kicad_sym", "MyPart.kicad_sym")
        zf.write(fixtures_dir / "one_footprint.kicad_mod", "MyPart.kicad_mod")
        zf.writestr("MyPart.step", "ISO-10303-21;\n")
        if with_datasheet:
            zf.writestr("MyPart.pdf", "%PDF-1.4\n%%EOF\n")
    return z


def _add_bare_part(pipe, category="ICs") -> PartRecord:
    """Land an existing part with NO symbol/footprint/model, the way a whole-BOM
    import (add_reference_part) lands identity + sourcing only, so its CAD assets
    can be attached afterward (spec section 5, owner 2026-07-16 optional-assets gate)."""
    record = PartRecord(
        id="",
        display_name="TESTPART",
        category=category,
        description="a test part",
        mpn="TESTPART",
        manufacturer="Acme",
        datasheet=Datasheet(source_url="https://example.com/testpart.pdf"),
        purchase=[Purchase(vendor="Mouser", url="https://mouser.com/p/1")],
    )
    landed = pipe.ops.add_reference_part(record)
    assert landed.symbol is None and landed.footprint is None and landed.model is None
    return landed


def test_attach_assets_lands_symbol_footprint_and_model_on_a_bare_part(tmp_path, fixtures_dir):
    pipe = _pipeline(tmp_path)
    bare = _add_bare_part(pipe)
    z = _snapeda_zip(tmp_path, fixtures_dir)
    [c] = pipe.inspect(inputs=[z], workdir=tmp_path / "work")
    c.entry_name = "TESTPART"

    head_before = pipe.repo.head()
    rec = pipe.attach_assets(bare.id, c)

    assert rec.symbol is not None and rec.symbol.name == "TESTPART"
    assert rec.footprint is not None and rec.footprint.name == "TESTPART"
    assert rec.model is not None  # the snapeda fixture zip carries a .step file

    sym_lib = SymbolLib.load(pipe.profile.library.symbol_lib_path("ICs"))
    assert "TESTPART" in sym_lib.symbol_names
    fp_path = pipe.profile.library.footprint_lib_path("ICs") / "TESTPART.kicad_mod"
    assert fp_path.exists()
    assert "models/" in (Footprint.load(fp_path).model_path or "")
    model_path = pipe.profile.library.root / rec.model.file
    assert model_path.exists()

    # the record's identity mirrored onto the freshly-placed symbol
    sym = sym_lib.get_symbol("TESTPART")
    assert sym.get_property("MPN") == "TESTPART"
    assert sym.get_property("Manufacturer") == "Acme"
    assert sym.get_property("Footprint") == "SR-ICs:TESTPART"

    # persisted to the JSON record too
    json_path = pipe.profile.library.parts_dir / f"{bare.id}.json"
    saved = PartRecord.loads(json_path.read_text(encoding="utf-8"))
    assert saved.symbol.name == "TESTPART" and saved.footprint.name == "TESTPART"
    assert saved.model is not None

    # one atomic commit, zero trace of the staging tempdir
    assert pipe.repo.head() != head_before
    assert pipe.repo.is_clean()


def test_attach_assets_only_touches_what_the_candidate_carries(tmp_path, fixtures_dir):
    """A 3D-model-only candidate (attach_model's shape) must set ONLY .model, never
    invent a symbol/footprint the candidate did not offer."""
    from stockroom.ingest.staging import StagingCandidate

    pipe = _pipeline(tmp_path)
    bare = _add_bare_part(pipe)
    z = _snapeda_zip(tmp_path, fixtures_dir)
    [c] = pipe.inspect(inputs=[z], workdir=tmp_path / "work")
    c.entry_name = "TESTPART"
    # first attach symbol + footprint only (no model)
    model_path = c.model_path
    c.model_path = None
    rec = pipe.attach_assets(bare.id, c)
    assert rec.symbol is not None and rec.footprint is not None
    assert rec.model is None

    # now attach the 3D model on its own, mirroring attach_model's contract
    partial = StagingCandidate(
        vendor="partial", symbol_lib_path=None, symbol_name="",
        footprint_variants=[], model_path=model_path,
    )
    updated = pipe.attach_assets(bare.id, partial)
    assert updated.model is not None
    assert updated.symbol.name == "TESTPART"  # untouched, not re-merged
    assert updated.footprint.name == "TESTPART"


def test_attach_assets_rejects_a_candidate_with_nothing_to_attach(tmp_path, fixtures_dir):
    from stockroom.ingest.errors import IngestError
    from stockroom.ingest.staging import StagingCandidate

    pipe = _pipeline(tmp_path)
    bare = _add_bare_part(pipe)
    empty = StagingCandidate(
        vendor="partial", symbol_lib_path=None, symbol_name="", footprint_variants=[],
    )
    with pytest.raises(IngestError):
        pipe.attach_assets(bare.id, empty)


def test_attach_assets_leaves_zero_trace_on_a_failed_symbol_merge(tmp_path, fixtures_dir):
    """A forced failure mid-transaction (a corrupted symbol source) must restore the
    record + repo to exactly the pre-attach state: no commit, no stray files, a
    clean working tree (spec sections 5, 9: never a half-attached part)."""
    pipe = _pipeline(tmp_path)
    bare = _add_bare_part(pipe)
    z = _snapeda_zip(tmp_path, fixtures_dir)
    [c] = pipe.inspect(inputs=[z], workdir=tmp_path / "work")
    c.entry_name = "TESTPART"
    # corrupt the symbol source so merge_symbol_into_lib fails INSIDE the transaction
    c.symbol_lib_path.write_text("(kicad_symbol_lib (this is broken")

    head_before = pipe.repo.head()
    json_before = (pipe.profile.library.parts_dir / f"{bare.id}.json").read_text(encoding="utf-8")
    with pytest.raises(Exception):
        pipe.attach_assets(bare.id, c)

    assert pipe.repo.head() == head_before
    saved = PartRecord.loads(
        (pipe.profile.library.parts_dir / f"{bare.id}.json").read_text(encoding="utf-8")
    )
    assert saved.symbol is None and saved.footprint is None and saved.model is None
    assert (pipe.profile.library.parts_dir / f"{bare.id}.json").read_text(encoding="utf-8") == json_before
    assert pipe.repo.status_porcelain() == []
