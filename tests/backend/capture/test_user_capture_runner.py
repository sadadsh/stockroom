"""There is ONE capture mode, and it is person-driven.

The runner used to carry a ladder - automatic, assisted, finish-first, collect-all - and each rung
decided how much of a provider page Stockroom would operate itself. That ladder is gone. Stockroom
builds a safe URL, hosts the provider surface, and stages what the person downloads; nothing here
may drive a provider page, and nothing may re-appear behind a flag.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from stockroom.capture import runner


def test_person_driven_is_the_only_mode_and_no_automation_lane_remains():
    parameters = set(inspect.signature(runner.run_guided_capture).parameters)

    assert not parameters & {
        "user_driven",
        "operator_authorized",
        "finish_first",
        "collect_all",
        "sequential_providers",
    }
    # The lane selectors, the authorization seam, and the saved provider logins are gone with the
    # automation they existed to serve.
    for retired in (
        "HumanRequiredSource",
        "_provider_route_plan",
        "_machine_access_detail",
        "_automatic_provider_keys",
        "_automation_first_order",
        "_machine_access_allowed",
        "_saved_credentials",
        "_capture_rate_ledger",
    ):
        assert not hasattr(runner, retired), f"{retired} is an automation seam and must be gone"


def test_provider_capture_requires_exactly_one_selected_part():
    with pytest.raises(ValueError, match="exactly one selected part"):
        runner.run_guided_capture(object(), part_ids=["part-a", "part-b"], vendor="snapmagic")
    with pytest.raises(ValueError, match="exactly one selected part"):
        runner.run_guided_capture(object(), vendor="snapmagic")
    with pytest.raises(ValueError, match="does not accept a batch limit"):
        runner.run_guided_capture(object(), part_ids=["part-a"], vendor="snapmagic", limit=1)


def _runner_context(tmp_path, monkeypatch, *, record=None):
    import stockroom.evidence as evidence_module
    from stockroom.capture import browser as browser_module
    from stockroom.capture import guided as guided_module
    from stockroom.ingest import pipeline as pipeline_module

    constructed: list[dict] = []
    source_batches: list[list[object]] = []
    complete_options: list[dict] = []
    closed: list[bool] = []

    class Pipeline:
        def __init__(self, *_args, **options):
            self.options = options

    class Source:
        key = "guided"

        def __init__(self, make_pipeline, **options):
            self.make_pipeline = make_pipeline
            self.options = options
            constructed.append(options)

        def close(self):
            closed.append(True)

    class Runtime:
        def close(self):
            return None

    class Direct:
        key = "verified-cache"

    class Report:
        items = ()

        def of(self, *_statuses):
            return False

        def to_dict(self):
            return {"items": [], "counts": {}}

    def complete(work, *, sources, **options):
        source_batches.append(list(sources))
        complete_options.append({**options, "work": list(work)})
        return Report()

    monkeypatch.setattr(guided_module, "GuidedCaptureSource", Source)
    monkeypatch.setattr(pipeline_module, "IngestPipeline", Pipeline)
    monkeypatch.setattr(browser_module, "SharedPlaywrightRuntime", Runtime)
    monkeypatch.setattr(evidence_module, "EvidenceStore", lambda _root: object())
    monkeypatch.setattr(runner, "complete_library", complete)
    monkeypatch.setattr(runner, "build_sources", lambda *_args, **_kwargs: [Direct()])
    monkeypatch.setattr(
        runner,
        "_capture_downloads",
        lambda _ctx, key: tmp_path / f"{key}-downloads",
    )
    monkeypatch.setattr(
        runner,
        "_capture_profile",
        lambda _ctx, key: tmp_path / f"{key}-profile",
    )
    monkeypatch.setattr(runner, "_capture_evidence_root", lambda _ctx: tmp_path / "Evidence")

    exact = record or SimpleNamespace(
        id="part-a",
        manufacturer="Texas Instruments",
        mpn="BQ24074",
    )
    ctx = SimpleNamespace(
        ops=SimpleNamespace(load_record=lambda _part_id: exact),
        jobs=SimpleNamespace(run_write=lambda fn: fn()),
        rebuild_index=lambda: None,
        auto_push=lambda: None,
        profile=object(),
        repo=object(),
        cli=object(),
        config=SimpleNamespace(),
    )
    return ctx, constructed, source_batches, complete_options, closed


def test_one_selected_part_visits_every_registered_provider_person_driven(monkeypatch, tmp_path):
    ctx, constructed, source_batches, complete_options, closed = _runner_context(
        tmp_path,
        monkeypatch,
    )

    result = runner.run_guided_capture(ctx, part_ids=["part-a"])

    assert result == {"items": [], "counts": {}}
    assert [source.key for source in source_batches[0]] == [
        "verified-cache",
        "guided",
        "guided",
        "guided",
        "guided",
    ]
    assert [options["vendor"] for options in constructed] == list(runner._VENDOR_CHAIN)
    # Every provider is worked by the person, so every source is built the same way. No option
    # here can grant Stockroom permission to operate a provider control.
    for options in constructed:
        assert options["collect_variants"] is True
        assert options["preserve_active_pair"] is True
        assert options["close_after_supply"] is True
        assert set(options) & {
            "user_driven",
            "operator_authorized",
            "credentials",
            "rate_limiter",
            "machine_access_check",
        } == set()
    assert complete_options[0]["exhaustive"] is True
    assert complete_options[0]["collect_variants"] is True
    assert callable(complete_options[0]["evidence_resolver"])
    assert closed == [True] * len(constructed)


def test_a_preferred_provider_narrows_the_run_to_that_one_surface(monkeypatch, tmp_path):
    ctx, constructed, source_batches, _options, _closed = _runner_context(tmp_path, monkeypatch)

    runner.run_guided_capture(ctx, part_ids=["part-a"], vendor="digikey")

    assert [options["vendor"] for options in constructed] == ["digikey"]
    assert constructed[0]["convert_altium"] is runner._convert_ul_altium_package
    assert [source.key for source in source_batches[0]] == ["verified-cache", "guided"]


def test_an_unknown_provider_choice_fails_honestly(monkeypatch, tmp_path):
    ctx, _constructed, _batches, _options, _closed = _runner_context(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="no network capture adapter"):
        runner.run_guided_capture(ctx, part_ids=["part-a"], vendor="not-a-provider")


def test_a_broader_run_is_the_verified_evidence_lane_and_opens_no_provider_window(
    monkeypatch,
    tmp_path,
):
    """Nobody can stand in front of two parts at once, so no provider surface is constructed."""

    ctx, constructed, source_batches, complete_options, _closed = _runner_context(
        tmp_path,
        monkeypatch,
    )

    runner.run_guided_capture(ctx, part_ids=["part-a", "part-b"])

    assert constructed == []
    assert [source.key for source in source_batches[0]] == ["verified-cache"]
    assert complete_options[0]["exhaustive"] is False


def test_run_completion_never_constructs_a_provider_browser(monkeypatch, tmp_path):
    """Library-wide completion is retained evidence only; it must not open a window."""

    ctx, constructed, source_batches, _options, _closed = _runner_context(tmp_path, monkeypatch)

    def refuse(*_args, **_kwargs):
        raise AssertionError("bulk completion must not build a provider capture source")

    from stockroom.capture import guided as guided_module

    monkeypatch.setattr(guided_module, "GuidedCaptureSource", refuse)

    result = runner.run_completion(ctx, part_ids=["part-a"])

    assert result == {"items": [], "counts": {}}
    assert constructed == []
    assert [source.key for source in source_batches[0]] == ["verified-cache"]


def test_runner_uses_one_immutable_evidence_resolver_for_selection_and_completion(
    monkeypatch,
    tmp_path,
):
    import stockroom.evidence as evidence_module
    from stockroom.capture import verified_cache

    evidence_store = object()
    observed: dict[str, object] = {}

    class Source:
        key = "verified-cache"

    class Report:
        items = ()

        def of(self, *_statuses):
            return False

        def to_dict(self):
            return {"items": [], "counts": {}}

    def select(_parts_dir, *, load_record, sources, evidence_resolver):
        observed["selection_resolver"] = evidence_resolver
        observed["selection_evidence"] = evidence_resolver(load_record("part-a"))
        assert [source.key for source in sources] == ["verified-cache"]
        return iter(("part-a",))

    def complete(work, *, evidence_resolver, **_options):
        observed["completion_resolver"] = evidence_resolver
        observed["completion_evidence"] = evidence_resolver(record)
        assert list(work) == ["part-a"]
        return Report()

    record = SimpleNamespace(id="part-a")
    ctx = SimpleNamespace(
        ops=SimpleNamespace(load_record=lambda _part_id: record),
        jobs=SimpleNamespace(run_write=lambda fn: fn()),
        rebuild_index=lambda: None,
        auto_push=lambda: None,
        profile=SimpleNamespace(
            library=SimpleNamespace(parts_dir=tmp_path / "parts"),
        ),
        repo=object(),
        cli=object(),
        config=SimpleNamespace(),
    )

    monkeypatch.setattr(evidence_module, "EvidenceStore", lambda _root: evidence_store)
    monkeypatch.setattr(
        verified_cache,
        "record_completion_evidence",
        lambda store, current, **_kwargs: ("verified-by", store, current.id),
    )
    monkeypatch.setattr(runner, "_capture_evidence_root", lambda _ctx: tmp_path / "Evidence")
    monkeypatch.setattr(runner, "_vendor_chain", lambda _vendor: [])
    monkeypatch.setattr(runner, "build_sources", lambda *_args, **_kwargs: [Source()])
    monkeypatch.setattr(runner, "iter_incomplete", select)
    monkeypatch.setattr(runner, "complete_library", complete)

    assert runner.run_guided_capture(ctx) == {"items": [], "counts": {}}
    assert observed["selection_resolver"] is observed["completion_resolver"]
    assert observed["selection_evidence"] == (
        "verified-by",
        evidence_store,
        "part-a",
    )
    assert observed["completion_evidence"] == observed["selection_evidence"]


def test_coverage_reports_provider_gaps_as_needing_a_person(monkeypatch, tmp_path):
    from stockroom.capture.requirements import Requirement, split_requirement
    from stockroom.model.part import AssetRef, PartRecord

    record = PartRecord(
        id="bare-cad",
        display_name="Bare CAD",
        category="ICs",
        description="references without immutable evidence",
        manufacturer="Example",
        mpn="EXACT-123",
    )
    for owned in Requirement:
        tool, kind = split_requirement(owned)
        record.assets_for(tool).set(
            kind,
            AssetRef(file="model.step")
            if kind == "model"
            else AssetRef(lib="Present", name=record.mpn),
        )

    parts = tmp_path / "parts"
    parts.mkdir()
    (parts / "bare-cad.json").write_text("{}\n", encoding="utf-8")
    ctx = SimpleNamespace(
        profile=SimpleNamespace(library=SimpleNamespace(parts_dir=parts)),
        ops=SimpleNamespace(load_record=lambda _part_id: record),
        config=SimpleNamespace(),
        repo=object(),
        cli=object(),
    )

    monkeypatch.setattr(runner, "_capture_evidence_root", lambda _ctx: tmp_path / "Evidence")

    report = runner.coverage(ctx)

    assert report["total"] == 1
    assert report["complete"] == 0
    # No provider finishes a part without a person any more, so every provider-fillable gap is
    # reported as needing one rather than as something the bulk pass will handle.
    assert report["needs_assistance"] == 1
    assert report["unsourced"] == 0
    assert sorted(report["assisted_sources"]) == sorted(runner._VENDOR_CHAIN)
    assert set(report["by_requirement"]) == {requirement.value for requirement in Requirement}


def test_the_person_can_finish_a_route_and_skip_the_part_while_the_run_is_live(
    monkeypatch,
    tmp_path,
):
    """The Finish / Skip seam, end to end, on the run that is actually executing.

    A person-driven route otherwise ends only on cancel, on ~25 s of quiet after a file landed, or
    on the timeout - five times over for DigiKey's five author routes. This asserts the whole
    chain: the run publishes its intent under its one selected part, a signal raised mid-run
    reaches the predicates the running capture polls, and it is unreachable once the run is over.
    """

    import stockroom.evidence as evidence_module
    from stockroom.capture import browser as browser_module
    from stockroom.capture import guided as guided_module
    from stockroom.capture.intent import (
        FINISH_ROUTE,
        SKIP_PART,
        PersonCaptureIntentError,
        running_person_captures,
        signal_person_capture,
    )
    from stockroom.ingest import pipeline as pipeline_module

    constructed: list[dict] = []
    observed: dict[str, object] = {}

    class Pipeline:
        def __init__(self, *_args, **_options):
            pass

    class Source:
        key = "guided"

        def __init__(self, _make_pipeline, **options):
            constructed.append(options)

        def close(self):
            return None

    class Runtime:
        def close(self):
            return None

    class Report:
        items = ()

        def of(self, *_statuses):
            return False

        def to_dict(self):
            return {"items": [], "counts": {}}

    def complete(work, *, should_stop, **_options):
        assert list(work) == ["part-a"]
        finished = constructed[-1]["user_finished"]
        observed["published"] = running_person_captures()
        observed["quiet_finish"] = finished()
        observed["quiet_stop"] = should_stop()

        signal_person_capture("part-a", FINISH_ROUTE)
        # The route that is open takes the answer, and only that route: one click must not close
        # all five of DigiKey's author routes.
        observed["finish_open_route"] = finished()
        observed["finish_next_route"] = finished()
        # Finishing says "no more is coming", never "throw away what landed", so the run itself
        # is not stopped and the route still drains and attaches.
        observed["stop_after_finish"] = should_stop()

        signal_person_capture("part-a", SKIP_PART)
        observed["stop_after_skip"] = should_stop()
        return Report()

    monkeypatch.setattr(guided_module, "GuidedCaptureSource", Source)
    monkeypatch.setattr(pipeline_module, "IngestPipeline", Pipeline)
    monkeypatch.setattr(browser_module, "SharedPlaywrightRuntime", Runtime)
    monkeypatch.setattr(evidence_module, "EvidenceStore", lambda _root: object())
    monkeypatch.setattr(runner, "complete_library", complete)
    monkeypatch.setattr(
        runner,
        "_capture_downloads",
        lambda _ctx, key: tmp_path / f"{key}-downloads",
    )
    monkeypatch.setattr(
        runner,
        "_capture_profile",
        lambda _ctx, key: tmp_path / f"{key}-profile",
    )
    monkeypatch.setattr(runner, "_capture_evidence_root", lambda _ctx: tmp_path / "Evidence")
    record = SimpleNamespace(id="part-a", manufacturer="Texas Instruments", mpn="BQ24074")
    ctx = SimpleNamespace(
        ops=SimpleNamespace(load_record=lambda _part_id: record),
        jobs=SimpleNamespace(run_write=lambda fn: fn()),
        rebuild_index=lambda: None,
        auto_push=lambda: None,
        profile=object(),
        repo=object(),
        cli=object(),
        config=SimpleNamespace(),
    )

    runner.run_guided_capture(ctx, part_ids=["part-a"], vendor="digikey")

    assert observed["published"] == ("part-a",)
    assert observed["quiet_finish"] is False
    assert observed["quiet_stop"] is False
    assert observed["finish_open_route"] is True
    assert observed["finish_next_route"] is False
    assert observed["stop_after_finish"] is False
    assert observed["stop_after_skip"] is True
    # The intent lives exactly as long as the run a person could be standing in front of.
    assert running_person_captures() == ()
    with pytest.raises(PersonCaptureIntentError):
        signal_person_capture("part-a", SKIP_PART)


def test_a_verified_evidence_run_publishes_no_person_control(monkeypatch, tmp_path):
    """Nothing opens a person-driven window, so there is nothing for a person to finish or skip."""

    from stockroom.capture.intent import running_person_captures

    ctx, _constructed, _batches, _options, _closed = _runner_context(tmp_path, monkeypatch)
    published: list[tuple[str, ...]] = []

    def complete(_work, **_options):
        published.append(running_person_captures())

        class Report:
            items = ()

            def of(self, *_statuses):
                return False

            def to_dict(self):
                return {"items": [], "counts": {}}

        return Report()

    monkeypatch.setattr(runner, "complete_library", complete)

    runner.run_guided_capture(ctx, part_ids=["part-a", "part-b"])

    assert published == [()]
