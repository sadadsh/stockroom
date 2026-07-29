"""The completion surface: "is my library complete", and "make it complete".

Both of these were things only a script outside the app could do, which by the owner's
standing rule (*"everything u do manually the app should do by itself"*) made them missing
features rather than tooling. These tests drive the REAL routes on the real app.
"""

import json

import pytest


def _sse(client, job_id):
    """Drain a job's SSE stream into (kind, payload) pairs."""
    out = []
    with client.stream("GET", f"/api/jobs/{job_id}/events") as resp:
        assert resp.status_code == 200
        kind = None
        for line in resp.iter_lines():
            if line.startswith("event:"):
                kind = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                out.append((kind, json.loads(line.split(":", 1)[1].strip())))
    return out


# --- coverage ------------------------------------------------------------------------------


def test_coverage_answers_whether_the_library_is_complete(client):
    body = client.get("/api/library/completion").json()
    # The fixture library holds one part with a symbol+footprint and one without.
    assert body["total"] == 2
    assert set(body) >= {
        "total", "complete", "needs_files", "needs_assistance", "unsourced",
        "by_requirement", "sources", "can_provide", "assisted_sources",
        "assisted_can_provide",
    }


def test_coverage_breaks_the_gap_down_by_what_is_actually_missing(client):
    body = client.get("/api/library/completion").json()
    # Named per requirement, not one anonymous "incomplete" number: "3 parts need a 3D model"
    # is actionable and "3 parts are incomplete" is not.
    assert body["by_requirement"], body
    assert all(k.count("_") >= 1 for k in body["by_requirement"])


def test_coverage_separates_a_gap_with_a_source_from_a_gap_with_none(client):
    """The distinction that keeps the number honest. Altium gaps have no registered source
    yet, so they are `unsourced` -- real, reported, and NOT presented as pending work a run
    would clear. Collapsing the two would either hide them or promise a run that cannot
    deliver."""
    body = client.get("/api/library/completion").json()
    assert body["needs_files"] + body["unsourced"] + body["complete"] <= body["total"]
    assert "altium_symbol" in body["by_requirement"]
    assert "altium_symbol" not in body["can_provide"]
    assert "altium_symbol" in body["assisted_can_provide"]
    assert body["needs_assistance"] > 0


def test_coverage_needs_a_token(anon_client):
    assert anon_client.get("/api/library/completion").status_code == 401


# --- running -------------------------------------------------------------------------------


def test_a_run_streams_progress_and_finishes(client, monkeypatch):
    """Drives the real route end to end with the network source stubbed out. The point is the
    JOB: it starts, streams named progress, and lands a terminal result."""
    from stockroom.capture.complete import SourceOutcome
    from stockroom.capture.requirements import Requirement

    class Nothing:
        key = "stub"

        def provides(self):
            return frozenset({Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT})

        def supply(self, record):
            return SourceOutcome(skipped="stubbed")

    monkeypatch.setattr(
        "stockroom.capture.runner.build_sources", lambda ctx, **kw: [Nothing()]
    )
    job_id = client.post("/api/library/completion/run", json={}).json()["job_id"]
    events = _sse(client, job_id)
    kinds = [k for k, _ in events]
    assert "result" in kinds
    assert "error" not in kinds
    result = [p for k, p in events if k == "result"][0]["result"]
    assert "counts" in result and "items" in result


def test_a_run_can_be_limited_so_a_huge_library_is_previewable(client, monkeypatch):
    # Starting a 21-hour run to find out whether it works is not a reasonable first step.
    from stockroom.capture.complete import SourceOutcome
    from stockroom.capture.requirements import Requirement

    seen = []

    class Counting:
        key = "stub"

        def provides(self):
            # KICAD_MODEL is the asset the fixture library genuinely lacks (both parts carry
            # a symbol and a footprint), so this source has real work to be limited.
            return frozenset({Requirement.KICAD_MODEL})

        def supply(self, record):
            seen.append(record.id)
            return SourceOutcome(skipped="stubbed")

    monkeypatch.setattr(
        "stockroom.capture.runner.build_sources", lambda ctx, **kw: [Counting()]
    )
    job_id = client.post("/api/library/completion/run", json={"limit": 1}).json()["job_id"]
    _sse(client, job_id)
    assert len(seen) == 1


def test_a_run_over_a_chosen_part_touches_only_that_part(client, monkeypatch):
    from stockroom.capture.complete import SourceOutcome
    from stockroom.capture.requirements import Requirement

    seen = []

    class Counting:
        key = "stub"

        def provides(self):
            return frozenset({Requirement.KICAD_MODEL})

        def supply(self, record):
            seen.append(record.id)
            return SourceOutcome(skipped="stubbed")

    monkeypatch.setattr(
        "stockroom.capture.runner.build_sources", lambda ctx, **kw: [Counting()]
    )
    job_id = client.post(
        "/api/library/completion/run", json={"part_ids": ["mystery"]}
    ).json()["job_id"]
    _sse(client, job_id)
    assert seen == ["mystery"]


def test_a_run_needs_a_token(anon_client):
    assert anon_client.post("/api/library/completion/run", json={}).status_code == 401


# --- stopping ------------------------------------------------------------------------------


def test_stopping_an_unknown_job_is_a_404_not_a_silent_success(client):
    # A stop that quietly succeeds against a job that does not exist is a lie the UI would
    # render as "stopping...", forever.
    assert client.post("/api/jobs/does-not-exist/stop").status_code == 404


def test_stop_marks_a_real_job(client, app_ctx):
    import threading

    gate = threading.Event()

    def work(progress, should_stop):
        gate.wait(5)
        return {"stopped": should_stop()}

    job_id = app_ctx.jobs.submit_cancellable(work)
    body = client.post(f"/api/jobs/{job_id}/stop").json()
    assert body == {"job_id": job_id, "stopping": True}
    gate.set()
    assert [p for k, p in _sse(client, job_id) if k == "result"][0]["result"] == {
        "stopped": True
    }


def test_stop_needs_a_token(anon_client, app_ctx):
    job_id = app_ctx.jobs.submit_cancellable(lambda progress, should_stop: None)
    assert anon_client.post(f"/api/jobs/{job_id}/stop").status_code == 401


# --- the wiring layer's own promises ---------------------------------------------------------


def test_the_paced_source_is_what_a_real_run_uses(app_ctx):
    """A limiter that is built but not wired protects nothing. This asserts the real factory
    hands back a PACED source, because the measured 20-calls-per-minute ceiling is the only
    thing standing between a 10,000-part run and a WAF block."""
    from stockroom.capture.pacing import PacedSource
    from stockroom.capture.runner import build_sources

    sources = build_sources(app_ctx)
    assert sources and all(isinstance(s, PacedSource) for s in sources)
    # ...and the wrapper is transparent: the engine still sees a normal source.
    assert sources[0].key == "lcsc"


def test_a_single_part_run_is_not_rate_limited(app_ctx):
    # Making one part wait behind a library-wide limiter would be a pointless delay.
    from stockroom.capture.pacing import PacedSource
    from stockroom.capture.runner import build_sources

    assert not any(isinstance(s, PacedSource) for s in build_sources(app_ctx, paced=False))


@pytest.mark.parametrize("key", ["kicad_symbol", "kicad_footprint", "kicad_model"])
def test_the_registered_sources_cover_every_kicad_asset_kind(app_ctx, key):
    from stockroom.capture.runner import build_sources

    provided = {r.value for s in build_sources(app_ctx) for r in s.provides()}
    assert key in provided
