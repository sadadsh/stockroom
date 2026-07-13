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


def _snapeda_zip(tmp_path, fixtures_dir, name="part.zip"):
    z = tmp_path / name
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(fixtures_dir / "one_symbol.kicad_sym", "MyPart.kicad_sym")
        zf.write(fixtures_dir / "one_footprint.kicad_mod", "MyPart.kicad_mod")
        zf.writestr("MyPart.step", "ISO-10303-21;\n")
    return z


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
    z = _snapeda_zip(tmp_path, fixtures_dir)
    [c] = pipe.inspect(inputs=[z], workdir=tmp_path / "work")
    c.category = "ICs"
    c.entry_name = "TESTPART"
    record = pipe.commit(c)
    assert record.category == "ICs"
    sym_lib = SymbolLib.load(pipe.profile.library.symbol_lib_path("ICs"))
    assert "TESTPART" in sym_lib.symbol_names
    fp = pipe.profile.library.footprint_lib_path("ICs") / "TESTPART.kicad_mod"
    assert fp.exists()
    json_path = pipe.profile.library.parts_dir / f"{record.id}.json"
    assert json_path.exists()


def test_failed_commit_leaves_zero_trace(tmp_path, fixtures_dir):
    pipe = _pipeline(tmp_path)
    z = _snapeda_zip(tmp_path, fixtures_dir)
    [c] = pipe.inspect(inputs=[z], workdir=tmp_path / "work")
    c.category = "ICs"
    c.entry_name = "TESTPART"
    head_before = pipe.repo.head()
    # Corrupt the symbol source so add_part's merge fails mid-transaction.
    c.symbol_lib_path.write_text("(kicad_symbol_lib (this is broken")
    with pytest.raises(Exception):
        pipe.commit(c)
    assert pipe.repo.head() == head_before  # no commit
    # the category lib was never created/left behind
    assert not (pipe.profile.library.parts_dir / f"testpart.json").exists()


def test_attach_model_to_existing_part(tmp_path, fixtures_dir):
    pipe = _pipeline(tmp_path)
    z = _snapeda_zip(tmp_path, fixtures_dir)
    [c] = pipe.inspect(inputs=[z], workdir=tmp_path / "work")
    c.category = "ICs"
    c.entry_name = "TESTPART"
    # Commit WITHOUT a model.
    c.model_path = None
    record = pipe.commit(c)

    model = tmp_path / "late.step"
    model.write_bytes(b"ISO-10303-21;\n")
    partial = StagingCandidate(
        vendor="partial", symbol_lib_path=None, symbol_name="",
        footprint_variants=[], model_path=model,
    )
    updated = pipe.attach_model(record.id, partial)
    assert updated.model is not None
    fp_path = pipe.profile.library.footprint_lib_path("ICs") / "TESTPART.kicad_mod"
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
    record = pipe.commit(c)
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
    c1.category = "ICs"; c1.entry_name = "FIRST"
    pipe.commit(c1)
    sym_path = pipe.profile.library.symbol_lib_path("ICs")
    after_first = sym_path.read_text(encoding="utf-8")

    z2 = make_vendor_zip(tmp_path / "b.zip", "snapeda", fixtures_dir)
    [c2] = pipe.inspect(inputs=[z2], workdir=tmp_path / "w2")
    c2.category = "ICs"; c2.entry_name = "SECOND"
    pipe.commit(c2)
    after_second = sym_path.read_text(encoding="utf-8")

    assert '(symbol "FIRST"' in after_second
    assert '(symbol "SECOND"' in after_second
    diffs = semantic_diff(after_first, after_second)
    assert diffs and all(d.startswith("ADDED") for d in diffs)
