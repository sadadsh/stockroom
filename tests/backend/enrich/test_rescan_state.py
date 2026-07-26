import os

from stockroom.enrich.rescan_state import RescanState


def test_records_and_reloads_from_disk(tmp_path):
    p = tmp_path / "rescan-state.json"
    s = RescanState(p)
    assert s.last_checked("x") == "" and s.is_fresh("x", "2026-01-01T00:00:00+00:00") is False
    s.record("x", "updated", "2026-07-18T10:00:00+00:00")
    # a fresh instance sees the persisted entry (resume across process restarts)
    s2 = RescanState(p)
    assert s2.last_checked("x") == "2026-07-18T10:00:00+00:00"
    assert s2.outcome("x") == "updated"


def test_is_fresh_is_a_lexical_cutoff_compare(tmp_path):
    s = RescanState(tmp_path / "st.json")
    s.record("x", "unchanged", "2026-07-18T10:00:00+00:00")
    assert s.is_fresh("x", "2026-07-11T10:00:00+00:00") is True     # checked after cutoff -> fresh
    assert s.is_fresh("x", "2026-07-18T10:00:00+00:00") is True     # exactly at cutoff -> fresh
    assert s.is_fresh("x", "2026-07-19T10:00:00+00:00") is False    # checked before cutoff -> stale


def test_a_failed_part_is_never_fresh_so_it_is_retried(tmp_path):
    s = RescanState(tmp_path / "st.json")
    checked_at = "2026-07-18T10:00:00+00:00"
    earlier_cutoff = "2026-07-11T10:00:00+00:00"          # checked_at is AFTER this cutoff
    s.record("failed-part", "failed", checked_at)
    s.record("updated-part", "updated", checked_at)
    # failed is never fresh, even though its timestamp is after the cutoff -> retried incrementally
    assert s.is_fresh("failed-part", earlier_cutoff) is False
    # same timestamp, "updated" outcome -> IS fresh (proves only "failed" is excluded)
    assert s.is_fresh("updated-part", earlier_cutoff) is True


def test_clear_removes_the_file_and_entries(tmp_path):
    p = tmp_path / "st.json"
    s = RescanState(p)
    s.record("x", "updated", "T")
    s.clear()
    assert s.last_checked("x") == "" and not p.exists()


def test_corrupt_file_is_treated_as_empty_never_raises(tmp_path):
    p = tmp_path / "st.json"
    p.write_text("{not json", encoding="utf-8")
    s = RescanState(p)                                  # must not raise
    assert s.last_checked("x") == ""
    s.record("x", "updated", "T")                       # overwrites the garbage cleanly
    assert RescanState(p).outcome("x") == "updated"


def test_a_transient_replace_failure_is_retried_and_the_record_persists(tmp_path, monkeypatch):
    p = tmp_path / "st.json"
    s = RescanState(p)
    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("transient sharing violation")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    s.record("x", "updated", "2026-07-18T10:00:00+00:00")
    assert calls["n"] == 2  # first call failed transiently, second (the retry) succeeded
    # a fresh instance (reading with the real os.replace restored) sees the persisted entry
    s2 = RescanState(p)
    assert s2.last_checked("x") == "2026-07-18T10:00:00+00:00"
    assert s2.outcome("x") == "updated"


def test_a_persistent_write_failure_leaves_prior_history_intact_and_never_raises(
    tmp_path, monkeypatch
):
    p = tmp_path / "st.json"
    s = RescanState(p)
    s.record("x", "updated", "2026-07-18T10:00:00+00:00")  # this one succeeds and persists

    def always_fail_replace(src, dst):
        raise PermissionError("persistent sharing violation")

    monkeypatch.setattr(os, "replace", always_fail_replace)
    s.record("y", "unchanged", "2026-07-18T11:00:00+00:00")  # must not raise despite total failure

    # the previously-persisted entry survives on disk untouched (history not wiped)
    s3 = RescanState(p)
    assert s3.last_checked("x") == "2026-07-18T10:00:00+00:00"
    assert s3.outcome("x") == "updated"
    # the failed write never made it to disk
    assert s3.last_checked("y") == ""
