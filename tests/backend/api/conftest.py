from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from stockroom.api.app import create_app
from stockroom.api.context import build_context
from stockroom.store.machine_config import MachineConfig
from stockroom.vcs.repo import GitRepo


@pytest.fixture
def library_root(tmp_path):
    """A git-backed libraries root with one Main profile holding a couple of parts,
    reusing the same PartRecord JSON shape the index reads. Kept tiny and pure so
    the API tests never need kicad-cli or the network."""
    root = tmp_path / "libraries"
    root.mkdir()
    repo = GitRepo(root)
    repo.init()
    from stockroom.store.profile import ProfileStore

    store = ProfileStore(root, repo)
    profile = store.create("Main")
    parts = profile.library.parts_dir
    parts.mkdir(parents=True, exist_ok=True)
    # one complete-ish and one incomplete part, written as canonical PartRecord JSON
    _write_part(parts, "tps62130", complete=True)
    _write_part(parts, "mystery", complete=False)
    repo.commit("seed fixture parts", [parts])
    return root


def _write_part(parts_dir: Path, part_id: str, complete: bool) -> None:
    from stockroom.model.part import (
        Datasheet,
        LibRef,
        ModelRef,
        PartRecord,
        Purchase,
    )

    rec = PartRecord(
        id=part_id,
        display_name=part_id.upper(),
        category="ICs",
        description="a part" if complete else "",
        mpn=part_id.upper() if complete else "",
        manufacturer="TI" if complete else "",
    )
    if complete:
        rec.symbol = LibRef(lib="SR-ics", name=part_id.upper())
        rec.footprint = LibRef(lib="SR-ics", name="VQFN-16")
        rec.model = ModelRef(file="models/x.step")
        rec.datasheet = Datasheet(file="datasheets/x.pdf")
        rec.purchase = [Purchase(vendor="LCSC", url="https://x/p")]
    (parts_dir / f"{part_id}.json").write_text(rec.dumps(), encoding="utf-8")


@pytest.fixture
def app_ctx(library_root, tmp_path):
    kicad_dir = tmp_path / "kicad"
    kicad_dir.mkdir()
    config = MachineConfig(active_profile="Main")
    return build_context(library_root, kicad_dir=kicad_dir, config=config, token="testtoken")


@pytest.fixture
def client(app_ctx):
    from fastapi.testclient import TestClient

    app = create_app(app_ctx)
    with TestClient(app, base_url="http://test", raise_server_exceptions=False,
                    headers={"X-Stockroom-Token": "testtoken"}) as c:
        yield c


@pytest.fixture
def anon_client(app_ctx):
    from fastapi.testclient import TestClient

    app = create_app(app_ctx)
    with TestClient(app, base_url="http://test", raise_server_exceptions=False) as c:
        yield c
