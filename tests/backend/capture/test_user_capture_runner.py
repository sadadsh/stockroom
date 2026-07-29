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
    assert digikey["engine"] == "cloak"
    assert digikey["convert_altium"] is runner._convert_ul_altium_package
    assert digikey["user_driven"] is True
    assert digikey["operator_authorized"] is False
    assert digikey["credentials"] is None
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
        True,
        True,
    ]
    assert [options["operator_authorized"] for options in constructed] == [
        False,
        True,
        False,
        False,
    ]
    assert complete_options[0]["exhaustive"] is True
    assert complete_options[0]["collect_variants"] is True
    assert all(source.closed for source in source_batches[0] if hasattr(source, "closed"))
