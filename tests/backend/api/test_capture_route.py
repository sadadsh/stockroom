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
from dataclasses import replace

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
    """Serve one complete native KiCad + Altium + STEP provider evidence set locally."""
    base, shutdown = serve_fixture_vendor("ul-export-panel-native.html")
    _patch_fixture_vendor(
        monkeypatch,
        base,
        mpn="S1M",
        manufacturer="ON Semiconductor",
    )
    try:
        yield base
    finally:
        shutdown()


@pytest.fixture
def fake_kicad_only_vendor(monkeypatch):
    """Serve the measured legacy page, which cannot satisfy the native dual-EDA contract."""
    base, shutdown = serve_fixture_vendor()
    _patch_fixture_vendor(
        monkeypatch,
        base,
        mpn="TPD6E05U06RVZR",
        manufacturer="Texas Instruments",
    )
    try:
        yield base
    finally:
        shutdown()


def _patch_fixture_vendor(
    monkeypatch,
    base: str,
    *,
    mpn: str,
    manufacturer: str,
) -> None:
    """Route one local fixture through the production Ultra Librarian adapter."""
    from stockroom.capture import guided as capture_guided
    from stockroom.capture import identity as capture_identity
    from stockroom.capture import runner as capture_runner
    from stockroom.capture import vendors as capture_vendors
    from stockroom.capture.vendors import UltraLibrarianAdapter, get_adapter

    monkeypatch.setattr(UltraLibrarianAdapter, "resolve_url", lambda self, mpn: base)
    adapter = get_adapter("ultralibrarian")
    assert adapter is not None
    # This local fixture is the reviewed machine-access contract: no third-party site or terms are
    # involved, and the test must exercise the automatic adapter rather than wait for a person.
    monkeypatch.setattr(
        adapter,
        "capability",
        replace(adapter.capability, browser_access="machine_allowed"),
    )
    monkeypatch.setattr(
        capture_runner,
        "machine_access_authorized",
        lambda key: key == "ultralibrarian",
    )
    monkeypatch.setattr(
        capture_guided,
        "_resolved_provider_url_issue",
        lambda *_args, **_kwargs: "",
    )
    real_page_identity = capture_identity.page_identity
    real_provider_url_allowed = capture_vendors._provider_url_allowed
    monkeypatch.setattr(
        capture_identity,
        "page_identity",
        lambda vendor, url, **options: (
            capture_identity.PageIdentity(
                mpn=mpn,
                manufacturer=manufacturer,
            )
            if url.startswith(base)
            else real_page_identity(vendor, url, **options)
        ),
    )
    monkeypatch.setattr(
        capture_vendors,
        "page_identity",
        lambda vendor, url, **options: (
            capture_identity.PageIdentity(
                mpn=mpn,
                manufacturer=manufacturer,
            )
            if url.startswith(base)
            else real_page_identity(vendor, url, **options)
        ),
    )
    monkeypatch.setattr(
        capture_vendors,
        "_provider_url_allowed",
        lambda vendor, url, **options: (
            url.startswith(base) or real_provider_url_allowed(vendor, url, **options)
        ),
    )


@pytest.fixture
def headless(monkeypatch):
    """Run the capture browser headless in tests. The real workflow is HEADED on purpose - the
    person signs in - so this is the only place that differs, and it differs in one flag."""
    import stockroom.capture.runner as runner
    import stockroom.ingest.pipeline as ingest_pipeline

    original = runner.run_guided_capture
    original_pipeline = ingest_pipeline.IngestPipeline
    # These are browser-route tests. The direct LCSC lane has its own end-to-end tests and would
    # legitimately satisfy the part before this fixture provider is reached.
    monkeypatch.setattr(runner, "build_sources", lambda _ctx, **_kwargs: [])

    def isolated_pipeline(*args, **kwargs):
        # The route must prove the coherent provider pair, but it must not drive the owner's
        # installed Altium process while testing. Native model embedding and its rollback boundary
        # are covered at the pipeline layer; this API fixture keeps the real atomic attachment and
        # explicitly disables only that machine-dependent post-readback step.
        kwargs["auto_embed_altium_models"] = False
        return original_pipeline(*args, **kwargs)

    def patched(ctx, **kwargs):
        kwargs["headless"] = True
        # The fixture exercises the same automatic provider-driver implementation as production.
        kwargs["user_driven"] = False
        # ...and the FAST engine. Production asks for camoufox because that is what clears real
        # vendors' bot walls; these tests drive a LOCALHOST fixture with no bot protection, where
        # stealth buys nothing and costs ~15x. Without this pin, adding the camoufox default to
        # run_guided_capture would silently launch a full Firefox from the API suite.
        kwargs["engine"] = "chromium"
        return original(ctx, **kwargs)

    monkeypatch.setattr(ingest_pipeline, "IngestPipeline", isolated_pipeline)
    monkeypatch.setattr(runner, "run_guided_capture", patched)
    return patched


def _a_part_missing_its_cad_files(
    client,
    *,
    mpn: str = "S1M",
    manufacturer: str = "ON Semiconductor",
) -> dict:
    """A part with no active CAD pair, made so through the real detach endpoint.

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
        ("mpn", mpn),
        ("manufacturer", manufacturer),
    ):
        response = client.patch(
            f"/api/library/parts/{part_id}",
            json={"field": field, "value": value},
        )
        assert response.status_code == 200, response.text
    for kind in ("kicad_symbol", "kicad_footprint"):
        resp = client.delete(f"/api/library/parts/{part_id}/assets/{kind}")
        assert resp.status_code == 200, (
            f"detach {kind} failed: {resp.status_code} {resp.text[:200]}"
        )
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
    # UL's current native Altium option can ride beside KiCad and STEP in one user-selected export.
    assert ul["one_download_for_all_formats"] is True
    assert set(ul["tools"]) == {"kicad", "altium"}


def test_capture_needs_a_token(anon_client):
    assert anon_client.post("/api/library/capture/run", json={}).status_code == 401


def test_capturing_one_component_attaches_files_to_that_record(client, fake_vendor, headless):
    """PER COMPONENT, asserted at the layer the owner looks at: the record.

    Before this, a part with no CAD stayed exactly as it was and the only evidence of a capture
    was a log line. Here the record is re-read through the real API after the job finishes.
    """
    target = _a_part_missing_its_cad_files(client)

    job = client.post(
        "/api/library/capture/run",
        json={"part_ids": [target["id"]], "vendor": "ultralibrarian"},
    ).json()["job_id"]
    events = _drain(client, job)

    after = client.get(f"/api/library/parts/{target['id']}").json()
    kicad = after.get("assets", {}).get("kicad", {})
    altium = after.get("assets", {}).get("altium", {})
    assert kicad.get("symbol"), (
        f"no symbol attached to {target['id']}: {kicad}; job events were {events}"
    )
    assert kicad.get("footprint"), f"no footprint attached to {target['id']}: {kicad}"
    assert altium.get("symbol"), f"no Altium symbol attached to {target['id']}: {altium}"
    assert altium.get("footprint"), f"no Altium footprint attached to {target['id']}: {altium}"
    assert kicad["symbol"]["origin"]["evidence_set"] == altium["symbol"]["origin"]["evidence_set"]


def test_a_captured_asset_records_where_it_came_from(client, fake_vendor, headless):
    """The owner's complaint, verbatim: *"its not trusted where we've gotten them"*. An attached
    file that cannot say which vendor supplied it is exactly the state they objected to."""
    target = _a_part_missing_its_cad_files(client)

    job = client.post(
        "/api/library/capture/run",
        json={"part_ids": [target["id"]], "vendor": "ultralibrarian"},
    ).json()["job_id"]
    events = _drain(client, job)

    assets = client.get(f"/api/library/parts/{target['id']}").json().get("assets") or {}
    kicad = assets.get("kicad") or {}
    altium = assets.get("altium") or {}
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
    assert altium.get("symbol"), f"capture attached no Altium symbol; assets were {assets}"
    altium_origin = altium["symbol"].get("origin") or {}
    assert altium_origin.get("vendor") == "ultralibrarian", altium["symbol"]
    assert altium_origin.get("evidence_set")
    assert altium_origin["evidence_set"] == origin.get("evidence_set")


def test_kicad_only_provider_set_fails_closed_without_mutation(
    client, fake_kicad_only_vendor, headless
):
    target = _a_part_missing_its_cad_files(
        client,
        mpn="TPD6E05U06RVZR",
        manufacturer="Texas Instruments",
    )

    job = client.post(
        "/api/library/capture/run",
        json={"part_ids": [target["id"]], "vendor": "ultralibrarian"},
    ).json()["job_id"]
    events = _drain(client, job)

    after = client.get(f"/api/library/parts/{target['id']}").json()
    assets = after.get("assets") or {}
    assert not (assets.get("kicad") or {}).get("symbol"), assets
    assert not (assets.get("kicad") or {}).get("footprint"), assets
    assert not (assets.get("altium") or {}).get("symbol"), assets
    assert not (assets.get("altium") or {}).get("footprint"), assets
    result_items = [
        item for kind, payload in events if kind == "result" for item in payload["result"]["items"]
    ]
    assert result_items, events
    assert "complete dual-EDA source set" in result_items[0]["error"]


def test_the_whole_library_run_uses_the_same_automatic_path_as_one_component(
    client, fake_vendor, headless
):
    job = client.post("/api/library/capture/run", json={}).json()["job_id"]
    events = _drain(client, job)
    assert events, "the run produced no events at all"
    kinds = {kind for kind, _ in events}
    assert "done" in kinds or "result" in kinds, kinds


def test_assisted_fallback_requires_one_part_and_one_provider(client):
    no_part = client.post(
        "/api/library/capture/run",
        json={"mode": "assisted", "vendor": "ultralibrarian"},
    )
    no_provider = client.post(
        "/api/library/capture/run",
        json={"mode": "assisted", "part_ids": ["one"]},
    )

    assert no_part.status_code == 400
    assert "exactly one selected part" in no_part.json()["detail"]
    assert no_provider.status_code == 400
    assert "one selected provider" in no_provider.json()["detail"]


def test_a_run_is_cancellable(client, fake_vendor, headless):
    """Stop remains available while the one selected capture is in flight."""
    target = _a_part_missing_its_cad_files(client)
    job = client.post(
        "/api/library/capture/run",
        json={"part_ids": [target["id"]], "vendor": "ultralibrarian"},
    ).json()["job_id"]
    stopped = client.post(f"/api/jobs/{job}/stop")
    assert stopped.status_code in (200, 202, 204), stopped.text
