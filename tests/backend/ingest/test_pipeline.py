import shutil
import zipfile

import pytest

from stockroom.ingest.pipeline import IngestPipeline
from stockroom.ingest.staging import StagingCandidate
from stockroom.kicad.footprint import Footprint
from stockroom.kicad.symbol_lib import SymbolLib
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


def _complete(candidate):
    """Fill the identity + sourcing fields a raw ingest lacks so the candidate
    passes the strict complete-to-add gate (spec section 6). Assets (symbol,
    footprint, model, datasheet) come from the package; this adds the rest, the
    way M4 enrichment or a manual review edit would."""
    from stockroom.model.part import Purchase

    candidate.mpn = candidate.mpn or "TPS62130RGTR"
    candidate.manufacturer = candidate.manufacturer or "Texas Instruments"
    candidate.description = candidate.description or "3A step-down converter"
    candidate.purchase = [Purchase(vendor="Mouser", url="https://mouser.com/p/1")]
    return candidate


def test_inspect_a_snapeda_zip(tmp_path, fixtures_dir):
    pipe = _pipeline(tmp_path)
    z = _snapeda_zip(tmp_path, fixtures_dir)
    cands = pipe.inspect(inputs=[z], workdir=tmp_path / "work")
    assert len(cands) == 1
    c = cands[0]
    assert c.vendor == "snapeda"
    assert c.symbol_name == "TESTPART"
    assert c.provenance.original_zip_sha256  # recorded


def test_inspect_multiple_zips_at_once(tmp_path, fixtures_dir):
    pipe = _pipeline(tmp_path)
    z1 = _snapeda_zip(tmp_path, fixtures_dir, "a.zip")
    z2 = _snapeda_zip(tmp_path, fixtures_dir, "b.zip")
    cands = pipe.inspect(inputs=[z1, z2], workdir=tmp_path / "work")
    assert len(cands) == 2


def test_commit_lands_the_part_in_the_category_lib(tmp_path, fixtures_dir):
    pipe = _pipeline(tmp_path)
    z = _snapeda_zip(tmp_path, fixtures_dir, with_datasheet=True)
    [c] = pipe.inspect(inputs=[z], workdir=tmp_path / "work")
    c.category = "ICs"
    c.entry_name = "TESTPART"
    _complete(c)
    record = pipe.commit(c)
    assert record.category == "ICs"
    assert record.is_complete()  # a landed part is always complete
    sym_lib = SymbolLib.load(pipe.profile.library.symbol_lib_path("ICs"))
    assert "TESTPART" in sym_lib.symbol_names
    fp = pipe.profile.library.footprint_lib_path("ICs") / "TESTPART.kicad_mod"
    assert fp.exists()
    json_path = pipe.profile.library.parts_dir / f"{record.id}.json"
    assert json_path.exists()


def test_commit_rejects_an_incomplete_part_into_the_primary_library(tmp_path, fixtures_dir):
    """The primary library is complete-only (spec section 6): a raw ingest lacking
    MPN, manufacturer, datasheet, and a purchase link is REFUSED, and the error
    surfaces exactly which passport fields are missing. No silent partial add."""
    from stockroom.mutation.library_ops import IncompleteError

    pipe = _pipeline(tmp_path)
    z = _snapeda_zip(tmp_path, fixtures_dir)  # no datasheet, no sourcing
    [c] = pipe.inspect(inputs=[z], workdir=tmp_path / "work")
    c.category = "ICs"
    c.entry_name = "TESTPART"
    head_before = pipe.repo.head()
    with pytest.raises(IncompleteError) as exc:
        pipe.commit(c)
    missing = exc.value.missing
    assert "MPN" in missing
    assert "manufacturer" in missing
    assert "datasheet" in missing
    assert "purchase link" in missing
    # rejected BEFORE any write: no commit, nothing on disk
    assert pipe.repo.head() == head_before
    assert not (pipe.profile.library.symbol_lib_path("ICs")).exists()
    assert not (pipe.profile.library.footprint_lib_path("ICs")).exists()
    assert list(pipe.profile.library.parts_dir.glob("*.json")) == []


def test_archive_profile_grandfathers_an_incomplete_ingest(tmp_path, fixtures_dir):
    """An archive profile is exempt from the gate (spec section 7): a legacy import
    of an incomplete part still lands so nothing is lost on migration."""
    from stockroom.kicad.cli import KiCadCli

    repo = GitRepo(tmp_path / "repo")
    repo.init()
    (repo.root / "seed").write_text("x")
    repo.commit("seed", [repo.root / "seed"])
    store = ProfileStore(repo.root / "libraries", repo)
    archive = store.create("Archive", archive=True)
    assert archive.is_archive
    pipe = IngestPipeline(archive, repo, KiCadCli())
    z = _snapeda_zip(tmp_path, fixtures_dir)  # incomplete on purpose
    [c] = pipe.inspect(inputs=[z], workdir=tmp_path / "work")
    c.category = "ICs"
    c.entry_name = "TESTPART"
    record = pipe.commit(c)  # must NOT raise
    assert not record.is_complete()  # honestly incomplete, but grandfathered in
    sym_lib = SymbolLib.load(archive.library.symbol_lib_path("ICs"))
    assert "TESTPART" in sym_lib.symbol_names


def test_failed_commit_into_new_category_leaves_zero_trace(tmp_path, fixtures_dir):
    """A failure mid-transaction while adding into a brand-new category must leave
    no stray files AND no stray empty .pretty directory (git does not track empty
    dirs, so the transaction must dispose of it itself)."""
    pipe = _pipeline(tmp_path)
    z = _snapeda_zip(tmp_path, fixtures_dir, with_datasheet=True)
    [c] = pipe.inspect(inputs=[z], workdir=tmp_path / "work")
    # Transistors has no pre-existing symbol lib or .pretty in a fresh profile.
    c.category = "Transistors"
    c.entry_name = "TESTPART"
    _complete(c)  # pass the gate so the transaction actually opens and writes
    head_before = pipe.repo.head()
    # Corrupt the symbol source so add_part's merge fails INSIDE the transaction,
    # after ensure_footprint_lib created the .pretty and the empty symbol lib.
    c.symbol_lib_path.write_text("(kicad_symbol_lib (this is broken")
    with pytest.raises(Exception):
        pipe.commit(c)
    assert pipe.repo.head() == head_before  # no commit
    pretty = pipe.profile.library.footprint_lib_path("Transistors")
    assert not pretty.exists(), "stray empty .pretty left behind after rollback"
    assert not pipe.profile.library.symbol_lib_path("Transistors").exists()
    assert pipe.repo.status_porcelain() == []  # working tree clean


def test_inspect_owns_and_cleans_its_temp_workdir(tmp_path, fixtures_dir):
    """When no workdir is supplied, inspect() creates one under the system temp dir
    and owns it; cleanup() (and __exit__) remove it so nothing is orphaned."""
    pipe = _pipeline(tmp_path)
    z = _snapeda_zip(tmp_path, fixtures_dir)
    cands = pipe.inspect(inputs=[z])  # no workdir -> owned tempdir
    assert len(pipe._owned_workdirs) == 1
    owned = pipe._owned_workdirs[0]
    assert owned.exists()
    # candidate paths point INTO the owned workdir and are live until cleanup
    assert str(owned) in str(cands[0].symbol_lib_path)
    pipe.cleanup()
    assert not owned.exists()
    assert pipe._owned_workdirs == []
    pipe.cleanup()  # idempotent


def test_pipeline_context_manager_cleans_owned_workdirs(tmp_path, fixtures_dir):
    from stockroom.kicad.cli import KiCadCli

    repo = GitRepo(tmp_path / "repo")
    repo.init()
    (repo.root / "seed").write_text("x")
    repo.commit("seed", [repo.root / "seed"])
    store = ProfileStore(repo.root / "libraries", repo)
    profile = store.create("Main")
    z = _snapeda_zip(tmp_path, fixtures_dir)
    with IngestPipeline(profile, repo, KiCadCli()) as pipe:
        pipe.inspect(inputs=[z])
        owned = pipe._owned_workdirs[0]
        assert owned.exists()
    assert not owned.exists()


def test_attach_model_to_existing_part(tmp_path, fixtures_dir):
    # attach_model enriches an EXISTING part with a late 3D model. A primary part
    # already has a model (the gate required it at entry), so the realistic
    # commit-without-model-then-attach flow is an archive part being completed.
    from stockroom.kicad.cli import KiCadCli

    repo = GitRepo(tmp_path / "repo")
    repo.init()
    (repo.root / "seed").write_text("x")
    repo.commit("seed", [repo.root / "seed"])
    store = ProfileStore(repo.root / "libraries", repo)
    archive = store.create("Archive", archive=True)
    pipe = IngestPipeline(archive, repo, KiCadCli())
    z = _snapeda_zip(tmp_path, fixtures_dir)
    [c] = pipe.inspect(inputs=[z], workdir=tmp_path / "work")
    c.category = "ICs"
    c.entry_name = "TESTPART"
    # Commit WITHOUT a model (archive is grandfathered, so this is allowed).
    c.model_path = None
    record = pipe.commit(c)
    assert record.model is None

    model = tmp_path / "late.step"
    model.write_bytes(b"ISO-10303-21;\n")
    partial = StagingCandidate(
        vendor="partial", symbol_lib_path=None, symbol_name="",
        footprint_variants=[], model_path=model,
    )
    updated = pipe.attach_model(record.id, partial)
    assert updated.model is not None
    fp_path = archive.library.footprint_lib_path("ICs") / "TESTPART.kicad_mod"
    assert "models/" in (Footprint.load(fp_path).model_path or "")


from tests.backend.ingest.vendor_fixtures import make_vendor_zip


@pytest.mark.parametrize("vendor", ["octopart", "samacsys", "ultralibrarian", "snapeda"])
def test_end_to_end_ingest_each_vendor_layout(tmp_path, fixtures_dir, vendor):
    pipe = _pipeline(tmp_path)
    z = make_vendor_zip(tmp_path / f"{vendor}.zip", vendor, fixtures_dir)
    cands = pipe.inspect(inputs=[z], workdir=tmp_path / "work")
    assert len(cands) >= 1
    c = cands[0]
    assert c.vendor == vendor
    # UltraLibrarian ships several footprint variants for the user to pick.
    if vendor == "ultralibrarian":
        assert len(c.footprint_variants) == 2
    c.category = "ICs"
    c.entry_name = f"PART_{vendor}"
    _complete(c)  # the package supplies the assets; add identity + sourcing
    record = pipe.commit(c)
    assert record.is_complete()  # a landed part passes the gate
    from stockroom.kicad.symbol_lib import SymbolLib
    sym_lib = SymbolLib.load(pipe.profile.library.symbol_lib_path("ICs"))
    assert f"PART_{vendor}" in sym_lib.symbol_names
    # a real git commit was produced
    assert record.id


def test_second_add_only_adds_to_target_lib(tmp_path, fixtures_dir):
    """Adding a second part must not rewrite the first part's symbol node: the
    target category lib changes only by ADDITION (byte preservation via the M1
    span layer + semantic-diff gate)."""
    from stockroom.verify.semdiff import semantic_diff

    pipe = _pipeline(tmp_path)
    z1 = make_vendor_zip(tmp_path / "a.zip", "snapeda", fixtures_dir)
    [c1] = pipe.inspect(inputs=[z1], workdir=tmp_path / "w1")
    c1.category = "ICs"; c1.entry_name = "FIRST"; _complete(c1)
    pipe.commit(c1)
    sym_path = pipe.profile.library.symbol_lib_path("ICs")
    after_first = sym_path.read_text(encoding="utf-8")

    z2 = make_vendor_zip(tmp_path / "b.zip", "snapeda", fixtures_dir)
    [c2] = pipe.inspect(inputs=[z2], workdir=tmp_path / "w2")
    c2.category = "ICs"; c2.entry_name = "SECOND"; _complete(c2)
    pipe.commit(c2)
    after_second = sym_path.read_text(encoding="utf-8")

    assert '(symbol "FIRST"' in after_second
    assert '(symbol "SECOND"' in after_second
    diffs = semantic_diff(after_first, after_second)
    assert diffs and all(d.startswith("ADDED") for d in diffs)
