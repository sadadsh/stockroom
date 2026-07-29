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

    constructed: list[dict] = []
    source_batches: list[list[object]] = []
    runtimes = []

    class Source:
        def __init__(self, _make_pipeline, **options):
            self.options = options
            self.closed = False
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
        ops=SimpleNamespace(
            attach_altium_assets=lambda *_args, **_kwargs: None,
            load_record=lambda _part_id: None,
        ),
        jobs=SimpleNamespace(run_write=lambda fn: fn()),
        rebuild_index=lambda: None,
        auto_push=lambda: None,
    )

    result = runner.run_guided_capture(
        ctx,
        part_ids=["part-a"],
        vendor="snapmagic",
        should_stop=stop,
    )

    assert result == {"items": [], "summary": {}}
    assert len(source_batches[0]) == 1
    assert source_batches[0][0].key == "lcsc"
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
    assert len(source_batches[1]) == 1
    assert [options["vendor"] for options in assisted] == ["snapmagic"]
    assert [options["engine"] for options in assisted] == ["camoufox"]
    assert all(options["user_driven"] is False for options in assisted)
    assert all(options["operator_authorized"] is True for options in assisted)
    cancel_checks = [options["user_cancelled"] for options in assisted]
    assert cancel_checks[0]() is False
    assisted[0]["cancel_workflow"]()
    assert cancel_checks[0]() is True
    assert all(options["credentials"] is runner._saved_credentials for options in assisted)
    assert all(source.closed for source in source_batches[1])
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
    assert digikey["user_driven"] is False
    assert digikey["operator_authorized"] is True
