"""`LibraryOps.embed_altium_model`: the atomic, verified 3D embed.

Altium is FAKED here, deliberately. The DelphiScript and the container verification are proven
against the real tool elsewhere (`tests/backend/altium/test_embed3d.py` plus a driven run on a real
`.PcbLib`); what these tests own is the part nothing else can check without a Windows machine and a
license seat: that the mutation is atomic, that a failure leaves ZERO trace in a git-tracked binary,
and that the record only claims a 3D model once the container really has one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stockroom.model.part import AssetRef, PartRecord

FIX = Path(__file__).parent / "fixtures"


def _seed(ops, pid="d", *, model: str | None = "models/d.step", footprint=True):
    ops.lib.parts_dir.mkdir(parents=True, exist_ok=True)
    record = PartRecord(id=pid, display_name=pid, category="Diodes", mpn="S1M")
    if model:
        (ops.lib.root / model).parent.mkdir(parents=True, exist_ok=True)
        (ops.lib.root / model).write_text("ISO-10303-21;", encoding="utf-8")
        record.assets_for("kicad").model = AssetRef(file=model)
    (ops.lib.parts_dir / f"{pid}.json").write_text(record.dumps(), encoding="utf-8")
    if footprint:
        ops.attach_altium_assets(pid, FIX / "sample.SchLib", FIX / "sample.PcbLib")
    return pid


class FakeDriver:
    """An Altium that does exactly what the test says, including lying about success.

    `writes` is what it appends to the .PcbLib, so a test can distinguish "the file was modified"
    from "the file was restored".
    """

    def __init__(self, tmp: Path, marker_text="DONE added=1 removed=0", writes=b"", ok=True):
        self.host = _FakeHost(tmp)
        self.marker_text = marker_text
        self.writes = writes
        self.ok = ok
        self.runs = 0

    def run_script(self, *, project, proc, marker, timeout, **_kw):
        self.runs += 1
        if self.writes:
            # The library path is in the generated script; find it rather than being told, so the
            # fake exercises the same wiring the real driver does.
            text = Path(project).with_suffix(".pas").read_text(encoding="utf-8")
            lib = text.split("LibPath  := '", 1)[1].split("'", 1)[0]
            target = Path(lib)
            with target.open("ab") as fh:
                fh.write(self.writes)
        from stockroom.altium.driver import RunOutcome

        return RunOutcome("ok" if self.ok else "busy", "faked", self.marker_text)


class _FakeHost:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp

    def to_windows_path(self, path: str) -> str:
        return str(path)

    def windows_temp(self) -> Path:
        return self.tmp


def _payload_streams(monkeypatch, *sequence):
    """Script what `ole_streams` reports on each successive read, so a test states what the
    container looks like before and after without needing Altium to make it so."""
    calls = list(sequence)
    monkeypatch.setattr(
        "stockroom.altium.embed3d.ole_streams",
        lambda _p: calls.pop(0) if len(calls) > 1 else calls[0],
    )


EMPTY = {"Library/Models/Data": 0}
FULL = {"Library/Models/Data": 162, "Library/Models/0": 65536}


def test_a_successful_embed_records_the_model_and_commits_once(library_ops, tmp_path, monkeypatch):
    ops = library_ops
    _seed(ops)
    _payload_streams(monkeypatch, EMPTY, FULL)
    monkeypatch.setattr("stockroom.altium.embed3d.read_model_index", lambda _p: ())
    before = ops.repo.head()

    result = ops.embed_altium_model("d", driver=FakeDriver(tmp_path, writes=b"XX"))

    assert result["status"] == "ok"
    assert result["embedded"] == 1 and result["payload_bytes"] == 65536
    record = ops.load_record("d")
    model = record.assets_for("altium").model
    assert model is not None
    assert model.file == "models/d.step"
    # The Altium model ref also names its CONTAINER, unlike KiCad's: the payload lives inside the
    # footprint library rather than beside it.
    assert model.lib == "d.PcbLib" and model.name == "DIOM5227X270N"
    # ONE scoped commit, and the modified binary is in it.
    assert ops.repo.head() != before
    assert result["commit"] == ops.repo.head()
    # Scoped to the .PcbLib and the record, NOT the whole tree: the seed writes fixture files it
    # never commits, so a whole-tree check here would be asserting the seed rather than the op.
    pcblib = ops.lib.parts_dir.parent / "altium" / "d.PcbLib"
    assert ops.repo.is_clean([pcblib]), "the .PcbLib edit must be committed, not left dirty"
    assert ops.repo.is_clean([ops.lib.parts_dir / "d.json"])
    assert "3D model" not in record.missing_assets("altium")


def test_a_failed_embed_restores_the_pcblib_and_leaves_zero_trace(
    library_ops, tmp_path, monkeypatch
):
    # The reason this is one transaction: a half-written OLE container is not something a peer
    # could repair by hand, and the .PcbLib is a tracked binary.
    ops = library_ops
    _seed(ops)
    pcblib = ops.lib.parts_dir.parent / "altium" / "d.PcbLib"
    original = pcblib.read_bytes()
    _payload_streams(monkeypatch, EMPTY)
    monkeypatch.setattr("stockroom.altium.embed3d.read_model_index", lambda _p: ())
    before = ops.repo.head()

    with pytest.raises(ValueError):
        ops.embed_altium_model("d", driver=FakeDriver(tmp_path, writes=b"CORRUPT"))

    assert pcblib.read_bytes() == original, "the pre-edit bytes must come back"
    assert ops.repo.head() == before
    assert ops.repo.is_clean([pcblib]), "a rolled-back edit must leave the binary clean"
    assert ops.load_record("d").assets_for("altium").model is None


def test_altium_claiming_success_with_no_payload_is_a_failure(library_ops, tmp_path, monkeypatch):
    # Altium said OK, DoFileSave returned TRUE, and the container gained nothing. Believing the
    # tool's own word here is what hid this feature's real failure for ten Altium boots.
    ops = library_ops
    _seed(ops)
    _payload_streams(monkeypatch, EMPTY, EMPTY)
    monkeypatch.setattr("stockroom.altium.embed3d.read_model_index", lambda _p: ())

    with pytest.raises(ValueError, match="no 3D model payload"):
        ops.embed_altium_model("d", driver=FakeDriver(tmp_path, writes=b"XX"))

    assert ops.load_record("d").assets_for("altium").model is None


def test_the_failure_message_carries_altiums_own_words(library_ops, tmp_path, monkeypatch):
    ops = library_ops
    _seed(ops)
    _payload_streams(monkeypatch, EMPTY, EMPTY)
    monkeypatch.setattr("stockroom.altium.embed3d.read_model_index", lambda _p: ())
    driver = FakeDriver(tmp_path, marker_text="FAIL: Altium could not load d.step", writes=b"XX")

    with pytest.raises(ValueError, match="could not load"):
        ops.embed_altium_model("d", driver=driver)


def test_a_part_with_no_altium_footprint_is_refused_with_the_reason(library_ops, tmp_path):
    ops = library_ops
    _seed(ops, footprint=False)
    with pytest.raises(ValueError, match="no Altium footprint"):
        ops.embed_altium_model("d", driver=FakeDriver(tmp_path))


def test_a_part_with_no_model_file_is_refused_with_the_reason(library_ops, tmp_path):
    ops = library_ops
    _seed(ops, model=None)
    with pytest.raises(ValueError, match="no 3D model file"):
        ops.embed_altium_model("d", driver=FakeDriver(tmp_path))


def test_a_dangling_model_reference_is_refused_rather_than_embedding_nothing(library_ops, tmp_path):
    ops = library_ops
    _seed(ops)
    (ops.lib.root / "models/d.step").unlink()
    with pytest.raises(ValueError, match="model file is missing"):
        ops.embed_altium_model("d", driver=FakeDriver(tmp_path))


def test_the_model_source_is_the_file_the_part_already_holds_for_any_tool(
    library_ops, tmp_path, monkeypatch
):
    # A STEP file is tool-agnostic, so an embed consumes the model the part ALREADY has. That is
    # why the registry lists Altium's model as embeddable but never capturable: asking a vendor for
    # a second, tool-specific copy would be busywork.
    ops = library_ops
    _seed(ops)
    record = ops.load_record("d")
    assert record.assets_for("altium").model is None
    assert ops._model_source(record).file == "models/d.step"  # taken from the KiCad bundle


def test_an_already_embedded_model_is_a_no_op_that_never_starts_altium(
    library_ops, tmp_path, monkeypatch
):
    ops = library_ops
    _seed(ops)
    _payload_streams(monkeypatch, FULL)
    monkeypatch.setattr(
        "stockroom.altium.embed3d.read_model_index", lambda _p: ({"NAME": "d.step"},)
    )
    driver = FakeDriver(tmp_path, writes=b"XX")

    result = ops.embed_altium_model("d", driver=driver)

    assert result["status"] == "ok" and "already" in result["detail"].lower()
    assert driver.runs == 0, "an Altium boot costs ~15s and the license seat"
