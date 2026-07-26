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


# --- The bulk path. -----------------------------------------------------------------------------
# Owner's deadline, 2026-07-26: "tomorrow i wanna build my full altium library ... literally
# everything i'd want fully done, no work on my end." One click per part is work, so a whole
# library's worth of 3D bodies has to be one action.
#
# This deliberately LOOPS the proven single-part embed rather than generalising the DelphiScript to
# take many jobs in one Altium boot. That script cost nine ruled-out hypotheses to get right, every
# iteration on it costs an Altium boot and a license seat, and an already-embedded model is skipped
# in 0.055s WITHOUT starting Altium - so a re-run is nearly free and only genuinely new work costs a
# boot. The one-boot-many-jobs version is a later optimisation, not a prerequisite.


def _payload_streams_per_library(monkeypatch):
    """EMPTY the first time each `.PcbLib` is inspected, FULL afterwards.

    The single-part helper walks ONE global sequence, which is right for one container and wrong
    for a bulk run: it would report the second part's library as already embedded before anything
    touched it. Every part in a Stockroom library has its own `.PcbLib`, so the state is per path.
    """
    seen: set[str] = set()

    def streams(path):
        key = str(path)
        if key in seen:
            return FULL
        seen.add(key)
        return EMPTY

    monkeypatch.setattr("stockroom.altium.embed3d.ole_streams", streams)


def test_bulk_embed_covers_every_part_that_needs_one(library_ops, tmp_path, monkeypatch):
    ops = library_ops
    _seed(ops, "d")
    _seed(ops, "e")
    _payload_streams_per_library(monkeypatch)
    monkeypatch.setattr("stockroom.altium.embed3d.read_model_index", lambda _p: ())

    report = ops.embed_altium_models(driver=FakeDriver(tmp_path, writes=b"XX"))

    assert report["embedded"] == 2, report
    assert report["failed"] == 0
    assert {r["part_id"] for r in report["results"]} == {"d", "e"}
    for pid in ("d", "e"):
        assert ops.load_record(pid).assets_for("altium").model is not None


def test_bulk_embed_skips_a_part_that_cannot_have_one_instead_of_failing(
    library_ops, tmp_path, monkeypatch
):
    """A library is mixed: KiCad-only parts, parts with no STEP yet, parts with no Altium
    footprint. None of those is an ERROR the owner should have to read - they are simply not
    candidates, and saying so is how the count stays honest."""
    ops = library_ops
    _seed(ops, "d")
    _seed(ops, "nomodel", model=None)
    _seed(ops, "nofootprint", footprint=False)
    _payload_streams(monkeypatch, EMPTY, FULL)
    monkeypatch.setattr("stockroom.altium.embed3d.read_model_index", lambda _p: ())

    report = ops.embed_altium_models(driver=FakeDriver(tmp_path, writes=b"XX"))

    assert report["embedded"] == 1
    assert report["failed"] == 0
    assert sorted(report["skipped"]) == ["nofootprint", "nomodel"]


def test_one_part_failing_never_abandons_the_rest(library_ops, tmp_path, monkeypatch):
    """The whole point of a bulk action is that the owner walks away. A single bad .PcbLib must
    not decide that the other forty parts go un-embedded, and its reason must survive to the
    report rather than being swallowed."""
    ops = library_ops
    _seed(ops, "d")
    _seed(ops, "e")
    _payload_streams_per_library(monkeypatch)
    monkeypatch.setattr("stockroom.altium.embed3d.read_model_index", lambda _p: ())
    real = ops.embed_altium_model
    seen: list[str] = []

    def flaky(part_id, **kw):
        seen.append(part_id)
        if part_id == "d":
            raise ValueError("Altium said no")
        return real(part_id, **kw)

    monkeypatch.setattr(ops, "embed_altium_model", flaky)
    report = ops.embed_altium_models(driver=FakeDriver(tmp_path, writes=b"XX"))

    assert sorted(seen) == ["d", "e"]  # it kept going
    assert report["embedded"] == 1
    assert report["failed"] == 1
    failure = next(r for r in report["results"] if r["status"] == "failed")
    assert failure["part_id"] == "d"
    assert "Altium said no" in failure["detail"]


def test_bulk_embed_reports_progress_per_part(library_ops, tmp_path, monkeypatch):
    """It runs as a job because it can take minutes, so it must say which part it is on - a
    silent multi-minute bar is the thing the owner cannot tell apart from a hang."""
    ops = library_ops
    _seed(ops, "d")
    _seed(ops, "e")
    _payload_streams_per_library(monkeypatch)
    monkeypatch.setattr("stockroom.altium.embed3d.read_model_index", lambda _p: ())
    seen: list[tuple[int, int, str]] = []

    ops.embed_altium_models(
        driver=FakeDriver(tmp_path, writes=b"XX"),
        on_progress=lambda done, total, pid: seen.append((done, total, pid)),
    )

    assert [s[2] for s in seen] == ["d", "e"] or [s[2] for s in seen] == ["e", "d"]
    assert seen[-1][0] == 2 and seen[-1][1] == 2


def test_bulk_embed_can_be_scoped_to_named_parts(library_ops, tmp_path, monkeypatch):
    ops = library_ops
    _seed(ops, "d")
    _seed(ops, "e")
    _payload_streams(monkeypatch, EMPTY, FULL)
    monkeypatch.setattr("stockroom.altium.embed3d.read_model_index", lambda _p: ())

    report = ops.embed_altium_models(part_ids=["e"], driver=FakeDriver(tmp_path, writes=b"XX"))

    assert report["embedded"] == 1
    assert [r["part_id"] for r in report["results"]] == ["e"]
    assert ops.load_record("d").assets_for("altium").model is None


def test_the_pending_count_is_what_the_button_can_promise(library_ops, tmp_path, monkeypatch):
    """The count beside the action must be the number of parts it will actually work on, so a
    button never offers work it cannot do (or hides work it will)."""
    ops = library_ops
    _seed(ops, "d")
    _seed(ops, "nomodel", model=None)
    _payload_streams(monkeypatch, EMPTY, FULL)
    monkeypatch.setattr("stockroom.altium.embed3d.read_model_index", lambda _p: ())

    assert ops.altium_models_pending() == ["d"]

    # After the embed the record carries the model, so the same part stops being offered. The
    # count is read from the records, not by parsing every .PcbLib, or asking "how many are
    # pending" would cost the whole library in disk reads on every status poll.
    ops.embed_altium_models(driver=FakeDriver(tmp_path, writes=b"XX"))
    assert ops.altium_models_pending() == []
