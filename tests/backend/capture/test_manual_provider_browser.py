from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from stockroom.capture.manual_provider_browser import (
    ManualProviderBrowserBroker,
    _apply_complete_proposal,
)
from stockroom.host.window import InAppProviderDownloadEvent
from stockroom.ingest.manual_files import propose_manual_cad_files
from stockroom.ingest.staging import StagingCandidate
from stockroom.model.part import PartRecord


class _Lease:
    def __init__(self) -> None:
        self.url = ""
        self.visible = False
        self.events: list[InAppProviderDownloadEvent] = []

    def navigate(self, url: str) -> None:
        self.url = url

    def show(self) -> None:
        self.visible = True

    def download_events(self, *, after_sequence: int = 0):
        return tuple(event for event in self.events if event.sequence > after_sequence)


class _Surface:
    def __init__(self) -> None:
        self.leases: list[_Lease] = []
        self.calls: list[dict[str, str]] = []
        self.released = 0

    @contextmanager
    def __call__(self, **identity: str):
        lease = _Lease()
        self.leases.append(lease)
        self.calls.append(identity)
        try:
            yield lease
        finally:
            self.released += 1


class _SlowSurface(_Surface):
    @contextmanager
    def __call__(self, **identity: str):
        time.sleep(0.08)
        with super().__call__(**identity) as lease:
            yield lease


class _Clock:
    def __init__(self) -> None:
        self.value = 1_000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _wait_for(predicate, timeout: float = 1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("condition did not become true")


def test_partial_direct_provider_downloads_publish_a_proposal_with_exact_remaining_roles(tmp_path):
    surface = _Surface()
    proposals: list[tuple[str, tuple[Path, ...], tuple[str, ...]]] = []

    def propose(_ctx, part_id, paths, *, edas):
        proposals.append((part_id, paths, edas))
        return {
            "proposal_token": "proposal-1",
            "part_id": part_id,
            "provider": "manual",
            "primary_tool": "both",
            "attachments": [{
                "role": "KiCad Symbol",
                "file_name": paths[0].name,
                "target": "Active KiCad Symbol",
            }],
            "inactive_evidence": [],
            "ignored": [],
            "selected_files": len(paths),
            "landed_files": [path.name for path in paths],
            "remaining_roles": ["KiCad Footprint", "3D Model"],
            "automatic_apply_ready": False,
        }

    broker = ManualProviderBrowserBroker(
        SimpleNamespace(),
        surface,
        proposal_factory=propose,
        root=tmp_path / "Manual Provider Downloads",
        poll_interval=0.01,
    )
    session = broker.start(
        session_id="7ed4d06c-66b0-4dbe-88ef-35edce7a373f",
        part_id="part-1",
        manufacturer="Texas Instruments",
        mpn="LM358DR",
        provider_id="mouser",
        url="https://www.mouser.com/c/?q=LM358DR",
        edas=("kicad", "altium"),
        browser_owner_id="part-1:mouser:route-1:session-1",
    )

    _wait_for(lambda: surface.leases and surface.leases[0].visible)
    landed = Path(surface.calls[0]["staging_root"]) / "download-LM358DR.zip"
    landed.write_bytes(b"cad")
    surface.leases[0].events.append(
        InAppProviderDownloadEvent(
            sequence=1,
            operation_id="download",
            phase="terminal",
            state="completed",
            uri="https://www.mouser.com/model.zip",
            suggested_file_name="LM358DR.zip",
            result_file_path=str(landed),
            total_bytes=3,
            bytes_received=3,
        )
    )

    snapshot = _wait_for(
        lambda: (
            value
            if (value := broker.status(session.session_id)).proposal is not None
            else None
        )
    )
    assert snapshot.state == "active"
    assert snapshot.proposal["landed_files"] == ["download-LM358DR.zip"]
    assert snapshot.proposal["remaining_roles"] == ["KiCad Footprint", "3D Model"]
    assert proposals == [("part-1", (landed,), ("kicad", "altium"))]
    assert surface.calls[0]["component_id"] == "part-1:mouser:route-1:session-1"

    broker.stop(session.session_id)
    _wait_for(lambda: surface.released == 1)


def test_complete_unambiguous_download_auto_applies_and_publishes_durable_cad_ready(tmp_path):
    surface = _Surface()
    applied: list[tuple[str, str]] = []

    def propose(_ctx, part_id, paths, *, edas):
        return {
            "proposal_token": "proposal-complete",
            "part_id": part_id,
            "provider": "manual",
            "primary_tool": "kicad",
            "attachments": [
                {"role": "KiCad Symbol", "file_name": "part.kicad_sym", "target": "Active KiCad Symbol"},
                {"role": "KiCad Footprint", "file_name": "part.kicad_mod", "target": "Active KiCad Footprint"},
                {"role": "3D Model", "file_name": "part.step", "target": "Shared 3D Model"},
            ],
            "inactive_evidence": [],
            "ignored": [],
            "selected_files": len(paths),
            "landed_files": [path.name for path in paths],
            "remaining_roles": [],
            "automatic_apply_ready": True,
        }

    def apply(_ctx, part_id, proposal_token):
        applied.append((part_id, proposal_token))
        return {
            "part_id": part_id,
            "attached": ["kicad_symbol", "kicad_footprint", "kicad_model"],
            "remaining": ["altium_symbol", "altium_footprint"],
            "complete": False,
        }

    broker = ManualProviderBrowserBroker(
        SimpleNamespace(),
        surface,
        proposal_factory=propose,
        apply_factory=apply,
        root=tmp_path,
        poll_interval=0.01,
    )
    session = broker.start(
        session_id="7ed4d06c-66b0-4dbe-88ef-35edce7a373f",
        part_id="part-1",
        manufacturer="Texas Instruments",
        mpn="LM358DR",
        provider_id="mouser",
        url="https://www.mouser.com/c/?q=LM358DR",
        edas=("kicad",),
        browser_owner_id="part-1:mouser:route-1:session-1",
    )
    _wait_for(lambda: surface.leases and surface.leases[0].visible)
    landed = Path(surface.calls[0]["staging_root"]) / "complete.zip"
    landed.write_bytes(b"cad")
    surface.leases[0].events.append(
        InAppProviderDownloadEvent(
            sequence=1,
            operation_id="download",
            phase="terminal",
            state="completed",
            uri="https://www.mouser.com/complete.zip",
            suggested_file_name="complete.zip",
            result_file_path=str(landed),
            total_bytes=3,
            bytes_received=3,
        )
    )

    snapshot = _wait_for(
        lambda: value if (value := broker.status(session.session_id)).state == "ready" else None
    )
    assert applied == [("part-1", "proposal-complete")]
    assert snapshot.proposal is None
    assert snapshot.cad_ready == {
        "attached": ["kicad_symbol", "kicad_footprint", "kicad_model"],
        "edas": ["kicad"],
        "landed_files": ["complete.zip"],
        "part_complete": False,
        "provider_id": "mouser",
        "remaining_roles": [],
    }
    _wait_for(lambda: surface.released == 1)


def test_auto_apply_that_still_lacks_a_selected_role_never_reports_cad_ready(tmp_path):
    surface = _Surface()
    proposal_calls = 0

    def propose(_ctx, part_id, paths, *, edas):
        nonlocal proposal_calls
        proposal_calls += 1
        return {
            "proposal_token": f"proposal-{proposal_calls}",
            "part_id": part_id,
            "provider": "manual",
            "primary_tool": "kicad",
            "attachments": [{
                "role": "KiCad Symbol",
                "file_name": "part.kicad_sym",
                "target": "Active KiCad Symbol",
            }],
            "inactive_evidence": [],
            "ignored": [],
            "landed_files": [path.name for path in paths],
            "remaining_roles": [] if proposal_calls == 1 else ["KiCad Footprint"],
            "automatic_apply_ready": proposal_calls == 1,
        }

    broker = ManualProviderBrowserBroker(
        SimpleNamespace(),
        surface,
        proposal_factory=propose,
        apply_factory=lambda *_args: {
            "attached": ["kicad_symbol", "kicad_model"],
            "remaining": ["kicad_footprint", "altium_symbol", "altium_footprint"],
            "complete": False,
        },
        root=tmp_path,
        poll_interval=0.01,
    )
    session = broker.start(
        session_id="7ed4d06c-66b0-4dbe-88ef-35edce7a373f",
        part_id="part-1",
        manufacturer="Texas Instruments",
        mpn="LM358DR",
        provider_id="mouser",
        url="https://www.mouser.com/c/?q=LM358DR",
        edas=("kicad",),
        browser_owner_id="part-1:mouser:route-1:session-1",
    )
    _wait_for(lambda: surface.leases and surface.leases[0].visible)
    landed = Path(surface.calls[0]["staging_root"]) / "partial.zip"
    landed.write_bytes(b"cad")
    surface.leases[0].events.append(
        InAppProviderDownloadEvent(
            sequence=1,
            operation_id="download",
            phase="terminal",
            state="completed",
            uri="https://www.mouser.com/partial.zip",
            suggested_file_name="partial.zip",
            result_file_path=str(landed),
            total_bytes=3,
            bytes_received=3,
        )
    )

    snapshot = _wait_for(
        lambda: value if (value := broker.status(session.session_id)).proposal is not None else None
    )
    assert snapshot.state == "active"
    assert snapshot.cad_ready is None
    assert snapshot.proposal["remaining_roles"] == ["KiCad Footprint"]
    assert "still needs KiCad Footprint" in snapshot.error
    broker.stop(session.session_id)


def test_durable_apply_survives_a_followup_index_refresh_failure(monkeypatch):
    class Jobs:
        def run_write(self, action):
            return action()

    ctx = SimpleNamespace(
        jobs=Jobs(),
        rebuild_index=lambda: (_ for _ in ()).throw(RuntimeError("index unavailable")),
        auto_push=lambda: None,
    )
    monkeypatch.setattr(
        "stockroom.capture.manual_provider_browser.apply_manual_cad_proposal",
        lambda *_args: {
            "attached": ["kicad_symbol"],
            "remaining": [],
            "complete": True,
        },
    )

    result = _apply_complete_proposal(ctx, "part-1", "proposal-1")

    assert result["attached"] == ["kicad_symbol"]
    assert "index refresh" in result["warning"]


def test_download_progress_stalls_with_a_bounded_recovery_state(tmp_path):
    surface = _Surface()
    broker = ManualProviderBrowserBroker(
        SimpleNamespace(),
        surface,
        proposal_factory=lambda *_args, **_kwargs: {},
        root=tmp_path,
        poll_interval=0.005,
        stall_timeout=0.03,
    )
    session = broker.start(
        session_id="7ed4d06c-66b0-4dbe-88ef-35edce7a373f",
        part_id="part-1",
        manufacturer="Texas Instruments",
        mpn="LM358DR",
        provider_id="mouser",
        url="https://www.mouser.com/c/?q=LM358DR",
        edas=("kicad",),
        browser_owner_id="part-1:mouser:route-1:session-1",
    )
    _wait_for(lambda: surface.leases and surface.leases[0].visible)
    surface.leases[0].events.append(
        InAppProviderDownloadEvent(
            sequence=1,
            operation_id="download",
            phase="started",
            state="in_progress",
            uri="https://www.mouser.com/complete.zip",
            suggested_file_name="complete.zip",
            result_file_path="",
            total_bytes=100,
            bytes_received=10,
        )
    )

    snapshot = _wait_for(
        lambda: value if (value := broker.status(session.session_id)).state == "stalled" else None
    )
    assert snapshot.download_progress == {
        "active": 1,
        "completed": 0,
        "bytes_received": 10,
        "total_bytes": 100,
        "files": [{
            "name": "complete.zip",
            "state": "in_progress",
            "bytes_received": 10,
            "total_bytes": 100,
        }],
    }
    assert "stalled" in snapshot.error.lower()
    broker.stop(session.session_id)


def test_provider_surface_startup_has_a_bounded_stall_state(tmp_path):
    surface = _SlowSurface()
    broker = ManualProviderBrowserBroker(
        SimpleNamespace(),
        surface,
        proposal_factory=lambda *_args, **_kwargs: {},
        root=tmp_path,
        poll_interval=0.005,
        stall_timeout=0.03,
    )

    snapshot = broker.start(
        session_id="7ed4d06c-66b0-4dbe-88ef-35edce7a373f",
        part_id="part-1",
        manufacturer="Texas Instruments",
        mpn="LM358DR",
        provider_id="mouser",
        url="https://www.mouser.com/c/?q=LM358DR",
        edas=("kicad",),
        browser_owner_id="part-1:mouser:route-1:session-1",
    )

    assert snapshot.state == "stalled"
    assert "opening stalled" in snapshot.error.lower()
    _wait_for(lambda: surface.leases)
    _wait_for(lambda: broker.status(snapshot.session_id).state == "active")
    broker.stop(snapshot.session_id)


def test_replacing_a_provider_session_releases_the_old_lease_before_new_navigation(tmp_path):
    surface = _Surface()
    broker = ManualProviderBrowserBroker(
        SimpleNamespace(),
        surface,
        proposal_factory=lambda *_args, **_kwargs: {},
        root=tmp_path,
        poll_interval=0.01,
    )

    first = broker.start(
        session_id="c4f1076f-c20c-470f-b8e8-8e11baa4ebcc",
        part_id="part-1",
        manufacturer="Texas Instruments",
        mpn="LM358DR",
        provider_id="mouser",
        url="https://www.mouser.com/c/?q=LM358DR",
        edas=("kicad",),
        browser_owner_id="part-1:mouser:route-1:session-1",
    )
    _wait_for(lambda: len(surface.leases) == 1 and surface.leases[0].visible)

    second = broker.start(
        session_id="acbd2a03-e41f-488c-8112-5da8c63c981e",
        part_id="part-1",
        manufacturer="Texas Instruments",
        mpn="LM358DR",
        provider_id="lcsc",
        url="https://www.lcsc.com/product-detail/C12345.html",
        edas=("kicad",),
        browser_owner_id="part-1:lcsc:route-2:session-2",
    )

    _wait_for(lambda: surface.released == 1 and len(surface.leases) == 2)
    assert broker.status(first.session_id).state == "replaced"
    assert surface.leases[1].url == "https://www.lcsc.com/product-detail/C12345.html"
    assert broker.status(second.session_id).state == "active"

    broker.stop(second.session_id)
    _wait_for(lambda: surface.released == 2)


def test_complete_wrong_mpn_download_stays_review_only_and_never_auto_applies(
    tmp_path: Path, monkeypatch
) -> None:
    surface = _Surface()
    selected_root = tmp_path / "candidate"
    selected_root.mkdir()
    symbol = selected_root / "wrong.kicad_sym"
    footprint = selected_root / "wrong.kicad_mod"
    model = selected_root / "wrong.step"
    for path in (symbol, footprint, model):
        path.write_bytes(path.name.encode())
    record = PartRecord(
        id="part-1",
        display_name="Example",
        category="ICs",
        mpn="ABM13W-32.0000MHZ-5-DH7G-T5",
        manufacturer="Abracon",
    )

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def inspect(self, *, inputs):
            assert len(inputs) == 1
            return [
                StagingCandidate(
                    vendor="manual",
                    symbol_lib_path=symbol,
                    symbol_name="ABM13W-32-0000MHZ-5-DH7G-T5",
                    footprint_variants=[footprint],
                    model_path=model,
                    mpn="ABM13W-32-0000MHZ-5-DH7G-T5",
                )
            ]

    monkeypatch.setattr("stockroom.ingest.manual_files.IngestPipeline", Pipeline)
    monkeypatch.setattr("stockroom.ingest.manual_files._discover_native_altium", lambda *_: [])
    applied: list[tuple[str, str]] = []
    ctx = SimpleNamespace(
        ops=SimpleNamespace(load_record=lambda _part_id: record),
        profile=object(),
        repo=object(),
        cli=object(),
    )
    broker = ManualProviderBrowserBroker(
        ctx,
        surface,
        proposal_factory=propose_manual_cad_files,
        apply_factory=lambda _ctx, part_id, token: applied.append((part_id, token)) or {},
        root=tmp_path / "Manual Provider Downloads",
        poll_interval=0.01,
    )
    session = broker.start(
        session_id="7ed4d06c-66b0-4dbe-88ef-35edce7a373f",
        part_id=record.id,
        manufacturer=record.manufacturer,
        mpn=record.mpn,
        provider_id="mouser",
        url="https://www.mouser.com/c/?q=ABM13W",
        edas=("kicad",),
        browser_owner_id="part-1:mouser:route-1:session-1",
    )
    _wait_for(lambda: surface.leases and surface.leases[0].visible)
    landed = Path(surface.calls[0]["staging_root"]) / "complete-wrong-part.zip"
    landed.write_bytes(b"cad")
    surface.leases[0].events.append(
        InAppProviderDownloadEvent(
            sequence=1,
            operation_id="download",
            phase="terminal",
            state="completed",
            uri="https://www.mouser.com/complete-wrong-part.zip",
            suggested_file_name=landed.name,
            result_file_path=str(landed),
            total_bytes=3,
            bytes_received=3,
        )
    )

    snapshot = _wait_for(
        lambda: value if (value := broker.status(session.session_id)).proposal is not None else None
    )
    assert applied == []
    assert snapshot.state == "active"
    assert snapshot.cad_ready is None
    assert snapshot.proposal["remaining_roles"] == ["Exact MPN Identity"]
    assert snapshot.proposal["remaining_status"] == ["Exact MPN Identity"]
    assert snapshot.proposal["automatic_apply_ready"] is False
    assert "Review" in snapshot.proposal["review_required_reason"]
    assert snapshot.error == ""
    broker.stop(session.session_id)


def test_discard_releases_lease_proposal_and_exact_session_staging_root(tmp_path):
    surface = _Surface()
    discarded: list[tuple[str, str]] = []

    def propose(_ctx, part_id, paths, *, edas):
        return {
            "proposal_token": "proposal-1",
            "part_id": part_id,
            "landed_files": [path.name for path in paths],
            "remaining_roles": ["KiCad Footprint"],
            "automatic_apply_ready": False,
        }

    broker = ManualProviderBrowserBroker(
        SimpleNamespace(),
        surface,
        proposal_factory=propose,
        proposal_discarder=lambda part_id, token: discarded.append((part_id, token)) or True,
        root=tmp_path / "Manual Provider Downloads",
        poll_interval=0.01,
    )
    session = broker.start(
        session_id="7ed4d06c-66b0-4dbe-88ef-35edce7a373f",
        part_id="part-1",
        manufacturer="Texas Instruments",
        mpn="LM358DR",
        provider_id="mouser",
        url="https://www.mouser.com/c/?q=LM358DR",
        edas=("kicad",),
        browser_owner_id="part-1:mouser:route-1:session-1",
    )
    _wait_for(lambda: surface.leases and surface.leases[0].visible)
    staging_root = Path(surface.calls[0]["staging_root"])
    landed = staging_root / "partial.zip"
    landed.write_bytes(b"cad")
    surface.leases[0].events.append(
        InAppProviderDownloadEvent(
            sequence=1,
            operation_id="download",
            phase="terminal",
            state="completed",
            uri="https://www.mouser.com/partial.zip",
            suggested_file_name=landed.name,
            result_file_path=str(landed),
            total_bytes=3,
            bytes_received=3,
        )
    )
    _wait_for(lambda: broker.status(session.session_id).proposal is not None)

    assert broker.stop(session.session_id) is True

    assert surface.released == 1
    assert discarded == [("part-1", "proposal-1")]
    assert not staging_root.exists()
    assert broker.status(session.session_id).state == "closed"


def test_expiry_bounds_active_download_and_prunes_terminal_session_metadata(tmp_path):
    surface = _Surface()
    clock = _Clock()
    broker = ManualProviderBrowserBroker(
        SimpleNamespace(),
        surface,
        proposal_factory=lambda *_args, **_kwargs: {},
        root=tmp_path / "Manual Provider Downloads",
        poll_interval=0.005,
        maximum_lifetime=10.0,
        session_retention=5.0,
        clock=clock,
    )
    session = broker.start(
        session_id="7ed4d06c-66b0-4dbe-88ef-35edce7a373f",
        part_id="part-1",
        manufacturer="Texas Instruments",
        mpn="LM358DR",
        provider_id="mouser",
        url="https://www.mouser.com/c/?q=LM358DR",
        edas=("kicad",),
        browser_owner_id="part-1:mouser:route-1:session-1",
    )
    _wait_for(lambda: surface.leases and surface.leases[0].visible)
    staging_root = Path(surface.calls[0]["staging_root"])
    surface.leases[0].events.append(
        InAppProviderDownloadEvent(
            sequence=1,
            operation_id="download",
            phase="started",
            state="in_progress",
            uri="https://www.mouser.com/complete.zip",
            suggested_file_name="complete.zip",
            result_file_path="",
            total_bytes=100,
            bytes_received=10,
        )
    )

    clock.advance(11.0)
    broker.cleanup_expired()
    _wait_for(lambda: surface.released == 1)

    assert broker.status(session.session_id).state == "expired"
    assert not staging_root.exists()
    clock.advance(6.0)
    assert broker.cleanup_expired() == 1
    try:
        broker.status(session.session_id)
    except KeyError:
        pass
    else:
        raise AssertionError("expired session metadata outlived its retention TTL")


def test_shutdown_releases_all_leases_and_owned_staging_without_deleting_attached_assets(tmp_path):
    surface = _Surface()
    attached_root = tmp_path / "Library Assets"
    attached_root.mkdir()

    def propose(_ctx, part_id, paths, *, edas):
        return {
            "proposal_token": f"proposal-{part_id}",
            "part_id": part_id,
            "landed_files": [path.name for path in paths],
            "remaining_roles": [],
            "automatic_apply_ready": True,
        }

    def apply(_ctx, part_id, _token):
        (attached_root / f"{part_id}.kicad_sym").write_bytes(b"attached")
        return {
            "attached": ["kicad_symbol"],
            "remaining": [],
            "complete": True,
        }

    broker = ManualProviderBrowserBroker(
        SimpleNamespace(),
        surface,
        proposal_factory=propose,
        apply_factory=apply,
        root=tmp_path / "Manual Provider Downloads",
        poll_interval=0.01,
    )
    first = broker.start(
        session_id="7ed4d06c-66b0-4dbe-88ef-35edce7a373f",
        part_id="part-1",
        manufacturer="Texas Instruments",
        mpn="LM358DR",
        provider_id="mouser",
        url="https://www.mouser.com/c/?q=LM358DR",
        edas=("kicad",),
        browser_owner_id="part-1:mouser:route-1:session-1",
    )
    broker.start(
        session_id="acbd2a03-e41f-488c-8112-5da8c63c981e",
        part_id="part-2",
        manufacturer="Texas Instruments",
        mpn="NE555DR",
        provider_id="mouser",
        url="https://www.mouser.com/c/?q=NE555DR",
        edas=("kicad",),
        browser_owner_id="part-2:mouser:route-1:session-2",
    )
    _wait_for(lambda: len(surface.leases) == 2 and all(lease.visible for lease in surface.leases))
    first_root = Path(surface.calls[0]["staging_root"])
    landed = first_root / "complete.zip"
    landed.write_bytes(b"cad")
    surface.leases[0].events.append(
        InAppProviderDownloadEvent(
            sequence=1,
            operation_id="download",
            phase="terminal",
            state="completed",
            uri="https://www.mouser.com/complete.zip",
            suggested_file_name=landed.name,
            result_file_path=str(landed),
            total_bytes=3,
            bytes_received=3,
        )
    )
    _wait_for(lambda: broker.status(first.session_id).state == "ready")
    second_root = Path(surface.calls[1]["staging_root"])

    broker.shutdown()

    assert surface.released == 2
    assert not first_root.exists()
    assert not second_root.exists()
    assert (attached_root / "part-1.kicad_sym").read_bytes() == b"attached"
    try:
        broker.start(
            session_id="9fc55bcc-8267-471c-849a-8694c9ad6146",
            part_id="part-3",
            manufacturer="Texas Instruments",
            mpn="TPS62130RGTR",
            provider_id="mouser",
            url="https://www.mouser.com/c/?q=TPS62130RGTR",
            edas=("kicad",),
            browser_owner_id="part-3:mouser:route-1:session-3",
        )
    except RuntimeError as exc:
        assert "shut down" in str(exc)
    else:
        raise AssertionError("a shut-down broker accepted a new session")
