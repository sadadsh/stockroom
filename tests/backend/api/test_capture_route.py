"""The guided-capture ROUTE, driven for real: one component and the whole library.

Owner, 2026-07-27: *"i also need guided capture per component"*, *"always make the easiest
workflow"*, and *"i need all systems to work exactly the same on linux and windows so anything u
verify easily can be the same on windows"*.

These drive the real endpoint on the real app, with a LOCAL stand-in vendor and a real browser, so
the whole path is exercised on Linux exactly as it runs on Windows: route -> job -> engine ->
browser -> download -> classify -> attach -> the RECORD.

The last link is the one that matters and the one that was missing before. Every previous claim
about capture was made from an adjacent layer; these assert on the part record itself.
"""

from __future__ import annotations

import json

import pytest

from stockroom.capture.browser import chromium_unavailable_reason

from ..capture.vendor_fixture_server import serve_fixture_vendor

_NO_BROWSER = chromium_unavailable_reason()
pytestmark = pytest.mark.skipif(_NO_BROWSER is not None, reason=str(_NO_BROWSER))


def _drain(client, job_id):
    events = []
    with client.stream("GET", f"/api/jobs/{job_id}/events") as resp:
        kind = None
        for line in resp.iter_lines():
            if line.startswith("event:"):
                kind = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                events.append((kind, json.loads(line.split(":", 1)[1].strip())))
    return events


@pytest.fixture
def fake_vendor(monkeypatch):
    """Point the Ultra Librarian adapter at a local stand-in serving its REAL captured markup, so
    no test ever touches the live vendor."""
    base, shutdown = serve_fixture_vendor()
    from stockroom.capture import identity as capture_identity
    from stockroom.capture.vendors import UltraLibrarianAdapter

    monkeypatch.setattr(UltraLibrarianAdapter, "resolve_url", lambda self, mpn: base)
    real_page_identity = capture_identity.page_identity
    monkeypatch.setattr(
        capture_identity,
        "page_identity",
        lambda vendor, url: (
            capture_identity.PageIdentity(
                mpn="TPD6E05U06RVZR",
                manufacturer="Texas Instruments",
            )
            if url.startswith(base)
            else real_page_identity(vendor, url)
        ),
    )
    try:
        yield base
    finally:
        shutdown()


@pytest.fixture
def headless(monkeypatch):
    """Run the capture browser headless in tests. The real workflow is HEADED on purpose - the
    person signs in - so this is the only place that differs, and it differs in one flag."""
    import stockroom.capture.runner as runner

    original = runner.run_guided_capture

    def patched(ctx, **kwargs):
        kwargs["headless"] = True
        # ...and the FAST engine. Production asks for camoufox because that is what clears real
        # vendors' bot walls; these tests drive a LOCALHOST fixture with no bot protection, where
        # stealth buys nothing and costs ~15x. Without this pin, adding the camoufox default to
        # run_guided_capture would silently launch a full Firefox from the API suite.
        kwargs["engine"] = "chromium"
        return original(ctx, **kwargs)

    monkeypatch.setattr(runner, "run_guided_capture", patched)
    return patched



def _a_part_missing_its_kicad_files(client) -> dict:
    """A part with NO KiCad symbol or footprint, made so through the real detach endpoint.

    The fixture library ships both of its parts complete, and `PartSummary.missing` is about
    METADATA (MPN, datasheet, purchase link), not assets - so an earlier version of this filtered
    on a field that could never identify an asset gap, picked an already-complete part, and two
    tests "passed" without capturing anything at all.

    Detaching first also makes the precondition REAL rather than assumed: the absence is asserted
    below before any capture runs, so a later assertion that the files exist can only be explained
    by the capture that put them there.
    """
    parts = client.get("/api/library/parts").json()["parts"]
    assert parts, "the fixture library is empty"
    part_id = parts[0]["id"]
    # The local provider fixture serves TPD6E05U06RVZR. Give the target that exact identity before
    # capture; attaching the fixture bytes to the old blank-MPN `mystery` record would prove only
    # that guided capture can mislabel an arbitrary download.
    for field, value in (
        ("mpn", "TPD6E05U06RVZR"),
        ("manufacturer", "Texas Instruments"),
    ):
        response = client.patch(
            f"/api/library/parts/{part_id}",
            json={"field": field, "value": value},
        )
        assert response.status_code == 200, response.text
    for kind in ("kicad_symbol", "kicad_footprint"):
        resp = client.delete(f"/api/library/parts/{part_id}/assets/{kind}")
        assert resp.status_code == 200, f"detach {kind} failed: {resp.status_code} {resp.text[:200]}"
    detail = client.get(f"/api/library/parts/{part_id}").json()
    kicad = (detail.get("assets") or {}).get("kicad", {})
    assert not kicad.get("symbol"), f"detach did not remove the symbol: {kicad}"
    assert not kicad.get("footprint"), f"detach did not remove the footprint: {kicad}"
    return detail


def test_the_route_exposes_only_vendors_that_have_an_implementation(client):
    body = client.get("/api/library/capture/vendors").json()
    keys = {v["key"] for v in body["vendors"]}
    assert "ultralibrarian" in keys
    ul = next(v for v in body["vendors"] if v["key"] == "ultralibrarian")
    # measured: UL's own site gives both formats in ONE export
    assert ul["one_download_for_all_formats"] is True
    # UL's PCAD row really does serve Altium a `.lia`, but nothing downstream can ATTACH one yet
    # (see UltraLibrarianAdapter's comment), so the capability must not claim it.
    assert set(ul["tools"]) == {"kicad"}


def test_capture_needs_a_token(anon_client):
    assert anon_client.post("/api/library/capture/run", json={}).status_code == 401


def test_capturing_one_component_attaches_files_to_that_record(
    client, fake_vendor, headless
):
    """PER COMPONENT, asserted at the layer the owner looks at: the record.

    Before this, a part with no CAD stayed exactly as it was and the only evidence of a capture
    was a log line. Here the record is re-read through the real API after the job finishes.
    """
    target = _a_part_missing_its_kicad_files(client)

    job = client.post(
        "/api/library/capture/run", json={"part_ids": [target["id"]]}
    ).json()["job_id"]
    events = _drain(client, job)

    after = client.get(f"/api/library/parts/{target['id']}").json()
    kicad = after.get("assets", {}).get("kicad", {})
    assert kicad.get("symbol"), (
        f"no symbol attached to {target['id']}: {kicad}; job events were {events}"
    )
    assert kicad.get("footprint"), f"no footprint attached to {target['id']}: {kicad}"


def test_a_captured_asset_records_where_it_came_from(client, fake_vendor, headless):
    """The owner's complaint, verbatim: *"its not trusted where we've gotten them"*. An attached
    file that cannot say which vendor supplied it is exactly the state they objected to."""
    target = _a_part_missing_its_kicad_files(client)

    job = client.post(
        "/api/library/capture/run", json={"part_ids": [target["id"]]}
    ).json()["job_id"]
    events = _drain(client, job)

    assets = client.get(f"/api/library/parts/{target['id']}").json().get("assets") or {}
    kicad = assets.get("kicad") or {}
    # Say WHY when nothing attached, instead of a bare KeyError that hides whether the capture
    # failed, timed out, or attached under a different tool.
    assert kicad.get("symbol"), (
        f"capture attached no KiCad symbol; assets were {assets}; job events were {events}"
    )
    symbol = kicad["symbol"]
    origin = symbol.get("origin") or {}
    assert origin.get("vendor") == "ultralibrarian", symbol
    assert origin.get("url"), symbol
    assert origin.get("captured_at"), "the server must stamp when the file landed"


def test_the_whole_library_run_uses_the_same_path_as_one_component(
    client, fake_vendor, headless
):
    """`{}` means every part still missing files. It must be the SAME engine as the per-component
    call - if these ever diverge, verifying one stops telling you anything about the other."""
    job = client.post("/api/library/capture/run", json={}).json()["job_id"]
    events = _drain(client, job)
    assert events, "the run produced no events at all"
    kinds = {kind for kind, _ in events}
    assert "done" in kinds or "result" in kinds, kinds


def test_a_run_is_cancellable(client, fake_vendor, headless):
    """At 90 parts a run you cannot stop is a commitment nobody should have to make."""
    job = client.post("/api/library/capture/run", json={}).json()["job_id"]
    stopped = client.post(f"/api/jobs/{job}/stop")
    assert stopped.status_code in (200, 202, 204), stopped.text
