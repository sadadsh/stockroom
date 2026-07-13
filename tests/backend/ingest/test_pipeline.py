import shutil
import zipfile

import pytest

from stockroom.ingest.pipeline import IngestPipeline
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
