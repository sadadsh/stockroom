from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from stockroom.capture import runner


def test_automatic_capture_is_the_runner_default():
    parameter = inspect.signature(runner.run_guided_capture).parameters["user_driven"]
    authorized = inspect.signature(runner.run_guided_capture).parameters["operator_authorized"]

    assert parameter.default is False
    assert authorized.default is False


@pytest.mark.parametrize(
    ("part_ids", "vendor", "limit", "message"),
    [
        (None, "snapmagic", None, "exactly one selected part"),
        ([], "snapmagic", None, "exactly one selected part"),
        (["part-a", "part-b"], "snapmagic", None, "exactly one selected part"),
        (["part-a"], None, None, "one selected provider"),
        (["part-a"], "snapmagic", 1, "does not accept a batch limit"),
    ],
)
def test_user_driven_runner_rejects_batch_or_implicit_provider_scope(
    part_ids,
    vendor,
    limit,
    message,
):
    with pytest.raises(ValueError, match=message):
        runner.run_guided_capture(
            object(),
            part_ids=part_ids,
            vendor=vendor,
            limit=limit,
            user_driven=True,
        )


def test_runner_uses_permitted_automatic_sources_and_keeps_provider_capture_explicit(
    monkeypatch,
    tmp_path,
):
    import stockroom.evidence as evidence_module
    from stockroom.capture import browser as browser_module
    from stockroom.capture import guided as guided_module
    from stockroom.ingest import pipeline as pipeline_module

    constructed: list[dict] = []
    pipeline_factories = []
    pipeline_options: list[dict] = []
    source_batches: list[list[object]] = []
    runtimes = []

    class Pipeline:
        def __init__(self, *_args, **options):
            pipeline_options.append(options)

    class Source:
        key = "guided"

        def __init__(self, make_pipeline, **options):
            self.options = options
            self.closed = False
            pipeline_factories.append(make_pipeline)
            constructed.append(options)

        def close(self):
            self.closed = True

    class Runtime:
        def __init__(self):
            self.closed = False
            runtimes.append(self)

        def close(self):
            self.closed = True

    class Report:
        def of(self, *_statuses):
            return False

        def to_dict(self):
            return {"items": [], "summary": {}}

    def complete(work, *, sources, **_options):
        assert list(work) == ["part-a"]
        source_batches.append(list(sources))
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

    stop = lambda: False
    ctx = SimpleNamespace(
        ops=SimpleNamespace(load_record=lambda _part_id: None),
        jobs=SimpleNamespace(run_write=lambda fn: fn()),
        rebuild_index=lambda: None,
        auto_push=lambda: None,
        profile=object(),
        repo=object(),
        cli=object(),
        config=SimpleNamespace(ul_private_evaluation_automation=False),
    )

    result = runner.run_guided_capture(
        ctx,
        part_ids=["part-a"],
        vendor="snapmagic",
        should_stop=stop,
    )

    assert result == {"items": [], "summary": {}}
    assert [source.key for source in source_batches[0]] == [
        "verified-cache",
        "snapmagic-human-required",
        "digikey-human-required",
        "ultralibrarian-human-required",
        "samacsys-human-required",
    ]
    assert constructed == []
    assert runtimes == []

    runner.run_guided_capture(
        ctx,
        part_ids=["part-a"],
        vendor="snapmagic",
        operator_authorized=True,
        should_stop=stop,
    )

    assisted = constructed
    assert [source.key for source in source_batches[1]] == [
        "guided",
    ]
    assert [options["vendor"] for options in assisted] == ["snapmagic"]
    assert [options["engine"] for options in assisted] == ["camoufox"]
    assert all(options["user_driven"] is False for options in assisted)
    assert all(options["operator_authorized"] is True for options in assisted)
    assert all(options["collect_variants"] is True for options in assisted)
    cancel_checks = [options["user_cancelled"] for options in assisted]
    assert cancel_checks[0]() is False
    assisted[0]["cancel_workflow"]()
    assert cancel_checks[0]() is True
    assert all(options["credentials"] is runner._saved_credentials for options in assisted)
    assert all(source.closed for source in source_batches[1] if hasattr(source, "closed"))
    assert runtimes == []

    runner.run_guided_capture(
        ctx,
        part_ids=["part-a"],
        vendor="digikey",
        operator_authorized=True,
        should_stop=stop,
    )

    digikey = constructed[-1]
    assert digikey["vendor"] == "digikey"
    assert digikey["engine"] == "camoufox"
    assert digikey["convert_altium"] is runner._convert_ul_altium_package
    assert digikey["user_driven"] is False
    assert digikey["operator_authorized"] is True
    assert digikey["credentials"] is runner._saved_credentials
    assert digikey["collect_variants"] is True
    pipeline_factories[-1]()
    assert pipeline_options[-1] == {"auto_embed_altium_models": True}


def test_collect_all_keeps_every_provider_and_closes_each_session_after_supply(
    monkeypatch,
    tmp_path,
):
    import stockroom.evidence as evidence_module
    from stockroom.capture import browser as browser_module
    from stockroom.capture import guided as guided_module
    from stockroom.ingest import pipeline as pipeline_module

    constructed: list[dict] = []
    source_batches: list[list[object]] = []
    complete_options: list[dict] = []

    class Pipeline:
        def __init__(self, *_args, **_options):
            pass

    class Source:
        key = "guided"

        def __init__(self, _make_pipeline, **options):
            self.options = options
            self.closed = False
            constructed.append(options)

        def close(self):
            self.closed = True

    class Runtime:
        def close(self):
            pass

    class Direct:
        key = "verified-cache"

    class Report:
        items = ()

        def of(self, *_statuses):
            return False

        def to_dict(self):
            return {"items": [], "counts": {}, "collection_complete": True}

    def complete(work, *, sources, **options):
        assert list(work) == ["part-a"]
        source_batches.append(list(sources))
        complete_options.append(options)
        return Report()

    monkeypatch.setattr(guided_module, "GuidedCaptureSource", Source)
    monkeypatch.setattr(pipeline_module, "IngestPipeline", Pipeline)
    monkeypatch.setattr(browser_module, "SharedPlaywrightRuntime", Runtime)
    monkeypatch.setattr(evidence_module, "EvidenceStore", lambda _root: object())
    monkeypatch.setattr(runner, "complete_library", complete)
    monkeypatch.setattr(runner, "build_sources", lambda *_args, **_kwargs: [Direct()])
    monkeypatch.setattr(
        runner,
        "_automatic_provider_keys",
        lambda _vendor, *, config=None: ["ultralibrarian"],
    )
    monkeypatch.setattr(
        runner,
        "DurableSlidingWindowLimiter",
        lambda *_args, **_kwargs: object(),
    )
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
    monkeypatch.setattr(
        runner,
        "_capture_rate_ledger",
        lambda _ctx, key: tmp_path / f"{key}-rate.json",
    )
    monkeypatch.setattr(runner, "_capture_evidence_root", lambda _ctx: tmp_path / "Evidence")
    record = SimpleNamespace(
        id="part-a",
        manufacturer="Texas Instruments",
        mpn="BQ24074",
    )
    ctx = SimpleNamespace(
        ops=SimpleNamespace(load_record=lambda _part_id: record),
        jobs=SimpleNamespace(run_write=lambda fn: fn()),
        rebuild_index=lambda: None,
        auto_push=lambda: None,
        profile=object(),
        repo=object(),
        cli=object(),
        config=SimpleNamespace(ul_private_evaluation_automation=True),
    )

    result = runner.run_guided_capture(
        ctx,
        part_ids=["part-a"],
        vendor="snapmagic",
        collect_all=True,
    )

    assert result["collection_complete"] is True
    assert [source.key for source in source_batches[0]] == [
        "verified-cache",
        "guided",
        "guided",
        "guided",
        "guided",
    ]
    assert [options["vendor"] for options in constructed] == [
        "ultralibrarian",
        "snapmagic",
        "digikey",
        "samacsys",
    ]
    assert all(options["collect_variants"] is True for options in constructed)
    assert all(options["preserve_active_pair"] is True for options in constructed)
    assert all(options["close_after_supply"] is True for options in constructed)
    assert [options["user_driven"] for options in constructed] == [
        False,
        False,
        False,
        True,
    ]
    assert [options["operator_authorized"] for options in constructed] == [
        False,
        True,
        True,
        False,
    ]
    assert complete_options[0]["exhaustive"] is True
    assert complete_options[0]["collect_variants"] is True
    assert callable(complete_options[0]["evidence_resolver"])
    assert all(source.closed for source in source_batches[0] if hasattr(source, "closed"))


def test_collect_all_finishes_every_automated_route_before_asking_a_person(
    monkeypatch,
    tmp_path,
):
    """Person-driven providers run LAST, after every route Stockroom can drive itself.

    Collect All Sources is exhaustive, so DigiKey and SamacSys are still visited.  But a
    person-driven route can be cancelled, and cancelling one cancels the rest of the run
    (`guided.py::_supply_user_driven_route` calls `cancel_workflow`).  With DigiKey ahead of
    SnapMagic in `_VENDOR_CHAIN`, closing DigiKey's window threw away a SnapMagic route that
    needed no person at all.  Automation therefore has to be exhausted before the handoff.
    """

    import stockroom.evidence as evidence_module
    from stockroom.capture import browser as browser_module
    from stockroom.capture import guided as guided_module
    from stockroom.ingest import pipeline as pipeline_module

    constructed: list[dict] = []

    class Pipeline:
        def __init__(self, *_args, **_options):
            pass

    class Source:
        key = "guided"

        def __init__(self, _make_pipeline, **options):
            self.options = options
            constructed.append(options)

        def close(self):
            pass

    class Runtime:
        def close(self):
            pass

    class Direct:
        key = "verified-cache"

    class Report:
        items = ()

        def of(self, *_statuses):
            return False

        def to_dict(self):
            return {"items": [], "counts": {}, "collection_complete": True}

    monkeypatch.setattr(guided_module, "GuidedCaptureSource", Source)
    monkeypatch.setattr(pipeline_module, "IngestPipeline", Pipeline)
    monkeypatch.setattr(browser_module, "SharedPlaywrightRuntime", Runtime)
    monkeypatch.setattr(evidence_module, "EvidenceStore", lambda _root: object())
    monkeypatch.setattr(runner, "complete_library", lambda *_args, **_options: Report())
    monkeypatch.setattr(runner, "build_sources", lambda *_args, **_kwargs: [Direct()])
    monkeypatch.setattr(
        runner,
        "_automatic_provider_keys",
        lambda _vendor, *, config=None: ["ultralibrarian"],
    )
    monkeypatch.setattr(
        runner,
        "DurableSlidingWindowLimiter",
        lambda *_args, **_kwargs: object(),
    )
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
    monkeypatch.setattr(
        runner,
        "_capture_rate_ledger",
        lambda _ctx, key: tmp_path / f"{key}-rate.json",
    )
    monkeypatch.setattr(runner, "_capture_evidence_root", lambda _ctx: tmp_path / "Evidence")
    record = SimpleNamespace(
        id="part-a",
        manufacturer="Texas Instruments",
        mpn="BQ24074",
    )
    ctx = SimpleNamespace(
        ops=SimpleNamespace(load_record=lambda _part_id: record),
        jobs=SimpleNamespace(run_write=lambda fn: fn()),
        rebuild_index=lambda: None,
        auto_push=lambda: None,
        profile=object(),
        repo=object(),
        cli=object(),
        config=SimpleNamespace(ul_private_evaluation_automation=True),
    )

    runner.run_guided_capture(ctx, part_ids=["part-a"], collect_all=True)

    order = [options["vendor"] for options in constructed]
    driven = [options["user_driven"] for options in constructed]

    # Every DigiKey author now stays in the operator-automated lane; only a provider without an
    # implemented ordinary-control adapter needs the raw person-driven fallback.
    assert order == ["ultralibrarian", "digikey", "snapmagic", "samacsys"]
    assert driven == [False, False, False, True]
    assert order.index("digikey") < order.index("samacsys")
    # Stated as the invariant, not as one hard-coded list: no automated route may follow a
    # person-driven one.
    assert driven == sorted(driven)


def test_collect_all_preference_reorders_only_within_the_automation_lane(
    monkeypatch,
    tmp_path,
):
    """A preferred person-driven provider is still not promoted ahead of automation.

    Preference reorders one lane; it never buys a person-driven surface the right to hold up
    routes that need nobody.
    """

    import stockroom.evidence as evidence_module
    from stockroom.capture import browser as browser_module
    from stockroom.capture import guided as guided_module
    from stockroom.ingest import pipeline as pipeline_module

    constructed: list[dict] = []

    class Pipeline:
        def __init__(self, *_args, **_options):
            pass

    class Source:
        key = "guided"

        def __init__(self, _make_pipeline, **options):
            constructed.append(options)

        def close(self):
            pass

    class Runtime:
        def close(self):
            pass

    class Direct:
        key = "verified-cache"

    class Report:
        items = ()

        def of(self, *_statuses):
            return False

        def to_dict(self):
            return {"items": [], "counts": {}, "collection_complete": True}

    monkeypatch.setattr(guided_module, "GuidedCaptureSource", Source)
    monkeypatch.setattr(pipeline_module, "IngestPipeline", Pipeline)
    monkeypatch.setattr(browser_module, "SharedPlaywrightRuntime", Runtime)
    monkeypatch.setattr(evidence_module, "EvidenceStore", lambda _root: object())
    monkeypatch.setattr(runner, "complete_library", lambda *_args, **_options: Report())
    monkeypatch.setattr(runner, "build_sources", lambda *_args, **_kwargs: [Direct()])
    monkeypatch.setattr(
        runner,
        "_automatic_provider_keys",
        lambda _vendor, *, config=None: ["ultralibrarian"],
    )
    monkeypatch.setattr(
        runner,
        "DurableSlidingWindowLimiter",
        lambda *_args, **_kwargs: object(),
    )
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
    monkeypatch.setattr(
        runner,
        "_capture_rate_ledger",
        lambda _ctx, key: tmp_path / f"{key}-rate.json",
    )
    monkeypatch.setattr(runner, "_capture_evidence_root", lambda _ctx: tmp_path / "Evidence")
    record = SimpleNamespace(
        id="part-a",
        manufacturer="Texas Instruments",
        mpn="BQ24074",
    )
    ctx = SimpleNamespace(
        ops=SimpleNamespace(load_record=lambda _part_id: record),
        jobs=SimpleNamespace(run_write=lambda fn: fn()),
        rebuild_index=lambda: None,
        auto_push=lambda: None,
        profile=object(),
        repo=object(),
        cli=object(),
        config=SimpleNamespace(ul_private_evaluation_automation=True),
    )

    runner.run_guided_capture(
        ctx,
        part_ids=["part-a"],
        vendor="digikey",
        collect_all=True,
    )

    order = [options["vendor"] for options in constructed]

    assert order == ["ultralibrarian", "digikey", "snapmagic", "samacsys"]
    # Every registered provider is still visited: preference demotes nobody out of the run.
    assert sorted(order) == sorted(runner._VENDOR_CHAIN)


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
        lambda store, current: ("verified-by", store, current.id),
    )
    monkeypatch.setattr(runner, "_capture_evidence_root", lambda _ctx: tmp_path / "Evidence")
    monkeypatch.setattr(runner, "_automatic_provider_keys", lambda *_args, **_kwargs: [])
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


def test_coverage_does_not_bless_populated_bare_cad_references(
    monkeypatch,
    tmp_path,
):
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
    monkeypatch.setattr(runner, "_automatic_provider_keys", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(runner, "_vendor_chain", lambda _vendor: [])

    report = runner.coverage(ctx)

    assert report["total"] == 1
    assert report["complete"] == 0
    assert report["needs_files"] == 1
    assert report["unsourced"] == 0
    assert set(report["by_requirement"]) == {requirement.value for requirement in Requirement}


def test_the_person_can_finish_a_route_and_skip_the_part_while_the_run_is_live(
    monkeypatch,
    tmp_path,
):
    """The Finish / Skip seam, end to end, on the run that is actually executing.

    `capture_user_downloads(..., should_finish=...)` and `GuidedCaptureSource(user_finished=...)`
    both existed and were simply never passed, so a person-driven route ended only on cancel, on
    ~25 s of quiet after a file landed, or on the 600 s timeout. This asserts the whole chain: the
    run publishes its intent under its one selected part, a signal raised mid-run reaches the
    predicates the running capture polls, and it is unreachable once the run is over.
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
    ctx = SimpleNamespace(
        ops=SimpleNamespace(load_record=lambda _part_id: None),
        jobs=SimpleNamespace(run_write=lambda fn: fn()),
        rebuild_index=lambda: None,
        auto_push=lambda: None,
        profile=object(),
        repo=object(),
        cli=object(),
        config=SimpleNamespace(ul_private_evaluation_automation=False),
    )

    runner.run_guided_capture(
        ctx,
        part_ids=["part-a"],
        vendor="digikey",
        operator_authorized=True,
    )

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


def test_a_library_wide_automatic_run_publishes_no_person_control(monkeypatch, tmp_path):
    """Nothing opens a person-driven window, so there is nothing for a person to finish or skip."""

    import stockroom.evidence as evidence_module
    from stockroom.capture import browser as browser_module
    from stockroom.capture import guided as guided_module
    from stockroom.capture.intent import running_person_captures
    from stockroom.ingest import pipeline as pipeline_module

    published: list[tuple[str, ...]] = []

    class Pipeline:
        def __init__(self, *_args, **_options):
            pass

    class Source:
        key = "guided"

        def __init__(self, _make_pipeline, **_options):
            pass

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

    def complete(_work, **_options):
        published.append(running_person_captures())
        return Report()

    monkeypatch.setattr(guided_module, "GuidedCaptureSource", Source)
    monkeypatch.setattr(pipeline_module, "IngestPipeline", Pipeline)
    monkeypatch.setattr(browser_module, "SharedPlaywrightRuntime", Runtime)
    monkeypatch.setattr(evidence_module, "EvidenceStore", lambda _root: object())
    monkeypatch.setattr(runner, "complete_library", complete)
    monkeypatch.setattr(runner, "build_sources", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(runner, "_capture_evidence_root", lambda _ctx: tmp_path / "Evidence")
    ctx = SimpleNamespace(
        ops=SimpleNamespace(load_record=lambda _part_id: None),
        jobs=SimpleNamespace(run_write=lambda fn: fn()),
        rebuild_index=lambda: None,
        auto_push=lambda: None,
        profile=object(),
        repo=object(),
        cli=object(),
        config=SimpleNamespace(ul_private_evaluation_automation=False),
    )

    runner.run_guided_capture(ctx, part_ids=["part-a", "part-b"])

    assert published == [()]
