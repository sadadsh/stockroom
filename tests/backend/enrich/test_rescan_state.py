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
