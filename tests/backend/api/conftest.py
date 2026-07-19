from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from stockroom.api.app import create_app
from stockroom.api.context import build_context
from stockroom.store.machine_config import MachineConfig
from stockroom.vcs.repo import GitRepo


def _drain_job(client, job_id):
    """Consume a job's SSE stream and return the terminal payload (event: <kind> + data: <json>)
    as {"status": "done"|"error"|"none", "result": ...}. Shared by every test that submits a
    job and waits for it to finish, so both the rescan and refresh API tests drain the same
    way instead of carrying their own copy of this loop."""
    kind = None
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        for line in s.iter_lines():
            if line.startswith("event:"):
                kind = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1].strip() or "{}")
                if kind == "result":
                    return {"status": "done", "result": data["result"]}
                if kind == "error":
                    return {"status": "error", "result": data}
    return {"status": "none", "result": None}


@pytest.fixture(autouse=True)
def _isolate_machine_config(tmp_path, monkeypatch):
    """Keep every config.save() (a profile switch, a settings write) inside the
    test's own tmp dir so the API suite never writes to the developer's real
    ~/.config/stockroom (or %APPDATA%/Stockroom). config_dir() reads this env on
    every call, so it governs load() and save() alike. XDG_CONFIG_HOME and APPDATA
    are pinned too, so no code path (kicad_config_dir + the auto-wire that WRITES
    there) can ever reach the developer's real ~/.config/kicad: the review caught
    the suite doing exactly that through apply_kicad_settings."""
    monkeypatch.setenv("STOCKROOM_CONFIG_DIR", str(tmp_path / "sr-config"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))


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
    lib = profile.library
    lib.parts_dir.mkdir(parents=True, exist_ok=True)
    # one complete-ish and one incomplete part, written as canonical PartRecord JSON
    _write_part(lib.parts_dir, "tps62130", complete=True)
    _write_part(lib.parts_dir, "mystery", complete=False)
    # real (kicad-cli-free) category libraries so mutations run the actual engine:
    # the SR-ICs symbol lib holds both parts' symbols, each part has a footprint
    # file keyed on its symbol name (what move/delete address on disk), and the
    # SR-Modules destination is pre-created so a move can append into it.
    _write_category_libs(lib)
    repo.commit("seed fixture parts and category libraries", [root])
    return root


# a symbol node named <NAME>, carrying the same properties move_category re-mirrors
_SYMBOL_NODE = (
    '\t(symbol "{name}"\n'
    '\t\t(property "Reference" "U" (at 0 0 0))\n'
    '\t\t(property "Value" "{name}" (at 0 0 0))\n'
    '\t\t(property "Footprint" "SR-ICs:{name}" (at 0 0 0))\n'
    '\t\t(property "Datasheet" "" (at 0 0 0))\n'
    "\t)\n"
)
_SYMBOL_LIB_HEADER = (
    "(kicad_symbol_lib\n"
    "\t(version 20251024)\n"
    '\t(generator "kicad_symbol_editor")\n'
    '\t(generator_version "10.0")\n'
)
_FOOTPRINT = (
    '(footprint "{name}"\n'
    "\t(version 20240108)\n"
    '\t(generator "pcbnew")\n'
    '\t(layer "F.Cu")\n'
    '\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))\n'
    ")\n"
)


def _write_category_libs(lib) -> None:
    """Materialise the SR-ICs symbol lib + footprints holding both fixture parts,
    plus the empty SR-Modules destination, so move_category and delete_part run the
    real transaction path without kicad-cli."""
    lib.symbols_dir.mkdir(parents=True, exist_ok=True)
    names = ["TPS62130", "MYSTERY"]
    ics_sym = _SYMBOL_LIB_HEADER + "".join(_SYMBOL_NODE.format(name=n) for n in names) + ")\n"
    lib.symbol_lib_path("ICs").write_text(ics_sym, encoding="utf-8", newline="")
    ics_pretty = lib.footprint_lib_path("ICs")
    ics_pretty.mkdir(parents=True, exist_ok=True)
    for n in names:
        (ics_pretty / f"{n}.kicad_mod").write_text(
            _FOOTPRINT.format(name=n), encoding="utf-8", newline=""
        )
    # empty destination category for the move test
    lib.symbol_lib_path("Modules").write_text(
        _SYMBOL_LIB_HEADER + ")\n", encoding="utf-8", newline=""
    )
    lib.footprint_lib_path("Modules").mkdir(parents=True, exist_ok=True)
    # every remaining category as a valid empty lib, so the auto KiCad wiring that
    # now runs on switch/boot never needs kicad-cli inside the API suite
    from stockroom.model.category import CATEGORIES

    for cat in CATEGORIES:
        sym = lib.symbol_lib_path(cat)
        if not sym.exists():
            sym.write_text(_SYMBOL_LIB_HEADER + ")\n", encoding="utf-8", newline="")


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
    # every fixture part has a real symbol + footprint on disk (see _write_category_libs);
    # completeness is still driven by the passport fields below, so mystery stays incomplete.
    rec.symbol = LibRef(lib="SR-ICs", name=part_id.upper())
    rec.footprint = LibRef(lib="SR-ICs", name=part_id.upper())
    if complete:
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
