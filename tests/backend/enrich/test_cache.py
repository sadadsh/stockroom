import threading

from stockroom.enrich.cache import TtlCache
from stockroom.enrich.schema import normalize_mpn


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_put_then_get_roundtrips(tmp_path):
    clk = _Clock()
    c = TtlCache(tmp_path, ttl=100.0, clock=clk)
    c.put("TPS62130RGTR", {"manufacturer": "TI"})
    assert c.get("TPS62130RGTR") == {"manufacturer": "TI"}


def test_get_is_normalized_mpn_insensitive(tmp_path):
    c = TtlCache(tmp_path, ttl=100.0, clock=_Clock())
    c.put("tps62130rgtr", {"x": 1})
    assert c.get("TPS62130RGTR") == {"x": 1}  # same normalized key


def test_expired_entry_returns_none_and_is_pruned(tmp_path):
    clk = _Clock(t=1000.0)
    c = TtlCache(tmp_path, ttl=100.0, clock=clk)
    c.put("ABC", {"v": 1})
    clk.t = 1000.0 + 101.0  # past the ttl
    assert c.get("ABC") is None
    assert list(tmp_path.glob("*.json")) == []  # pruned on read


def test_put_replaces_a_prior_entry_for_the_same_key(tmp_path):
    c = TtlCache(tmp_path, ttl=100.0, clock=_Clock())
    c.put("ABC", {"v": 1})
    c.put("ABC", {"v": 2})
    assert c.get("ABC") == {"v": 2}
    assert len(list(tmp_path.glob("*ABC*.json"))) == 1  # no stale duplicate


def test_prefix_keeps_sku_and_mpn_entries_apart(tmp_path):
    mpn_cache = TtlCache(tmp_path, ttl=100.0, prefix="mpn", clock=_Clock())
    sku_cache = TtlCache(tmp_path, ttl=100.0, prefix="sku", clock=_Clock())
    mpn_cache.put("X", {"kind": "mpn"})
    sku_cache.put("X", {"kind": "sku"})
    assert mpn_cache.get("X") == {"kind": "mpn"}
    assert sku_cache.get("X") == {"kind": "sku"}


def test_get_treats_a_torn_body_as_a_miss_and_removes_it(tmp_path):
    # A crash mid-write (or, before the atomic-write fix, two concurrent puts) can leave a
    # half-written JSON body. get() must treat it as a miss and drop the file so a fresh scrape
    # repopulates the key - never raise (the engine never raises) and never stay poisoned.
    c = TtlCache(tmp_path, ttl=100.0, clock=_Clock())
    key = normalize_mpn("STM32F103")
    torn = tmp_path / f"mpn___{key}___1000.json"
    torn.write_text('{"mpn": "STM32', encoding="utf-8")  # truncated -> JSONDecodeError
    assert c.get("STM32F103") is None
    assert not torn.exists()


def test_get_retries_a_transient_sharing_violation_instead_of_raising(tmp_path, monkeypatch):
    # On Windows NTFS, reading a cache file a concurrent writer is mid-os.replace-ing raises a
    # transient PermissionError (an OSError, NOT FileNotFoundError/ValueError). get() must retry
    # through it and return the value - never raise, and never drop the still-valid entry.
    import pathlib

    c = TtlCache(tmp_path, ttl=100.0, clock=_Clock())
    c.put("ABC", {"v": 1})
    real_read = pathlib.Path.read_text
    calls = {"n": 0}

    def flaky_read(self, *a, **k):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(13, "sharing violation")
        return real_read(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", flaky_read)
    assert c.get("ABC") == {"v": 1}  # retried past the two transient failures
    assert len(list(tmp_path.glob("*ABC*.json"))) == 1  # the valid entry was NOT dropped


def test_put_retries_a_transient_replace_violation_instead_of_raising(tmp_path, monkeypatch):
    # On Windows, os.replace onto a destination a concurrent reader holds open raises a transient
    # PermissionError. put() must retry through it so the entry still lands, never raising.
    import os as _os

    c = TtlCache(tmp_path, ttl=100.0, clock=_Clock())
    real_replace = _os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst, *a, **k):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(5, "access is denied")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(_os, "replace", flaky_replace)
    c.put("ABC", {"v": 9})
    assert c.get("ABC") == {"v": 9}
    assert list(tmp_path.glob(".mpn*.tmp")) == []  # temp cleaned up, none left behind


def test_put_degrades_to_no_cache_when_a_write_persistently_fails(tmp_path, monkeypatch):
    # A persistently unwritable cache (or contention past the retries) must degrade to no-cache
    # (the next lookup re-scrapes), never raise into the enrich job.
    import os as _os

    c = TtlCache(tmp_path, ttl=100.0, clock=_Clock())

    def always_denied(*a, **k):
        raise PermissionError(5, "access is denied")

    monkeypatch.setattr(_os, "replace", always_denied)
    c.put("ABC", {"v": 1})  # must NOT raise
    assert c.get("ABC") is None  # nothing was cached
    assert list(tmp_path.glob(".mpn*.tmp")) == []  # temp cleaned up


def test_get_treats_a_non_utf8_body_as_a_miss_and_removes_it(tmp_path):
    # A corrupt/legacy file with invalid UTF-8 bytes raises UnicodeDecodeError (a ValueError, NOT
    # an OSError) from read_text. get() must treat it as a miss and drop it, never raise it out
    # (which would poison the key for the whole TTL, since pipeline.enrich() calls get() unguarded).
    c = TtlCache(tmp_path, ttl=100.0, clock=_Clock())
    key = normalize_mpn("ABC")
    bad = tmp_path / f"mpn___{key}___1000.json"
    bad.write_bytes(b"\xff\xfe\x00garbage")
    assert c.get("ABC") is None
    assert not bad.exists()


def test_put_degrades_to_no_cache_when_the_temp_cannot_be_created(tmp_path, monkeypatch):
    # An unwritable/full cache dir makes mkstemp raise BEFORE the write. put() must still degrade
    # to no-cache (its docstring promises exactly this for an unwritable dir), never raise into
    # the enrich job.
    import tempfile as _tf

    c = TtlCache(tmp_path, ttl=100.0, clock=_Clock())

    def denied(*a, **k):
        raise PermissionError(13, "read-only cache dir")

    monkeypatch.setattr(_tf, "mkstemp", denied)
    c.put("ABC", {"v": 1})  # must NOT raise
    assert c.get("ABC") is None


def test_get_treats_a_non_dict_body_as_a_miss_and_removes_it(tmp_path):
    # A valid-JSON but non-dict body (external tampering / a legacy record) must be a miss+drop,
    # not returned: the caller does cached.get(...) and would AttributeError on a list/str. get()'s
    # contract is "a dict or None", never something that makes the enrich pipeline raise.
    c = TtlCache(tmp_path, ttl=100.0, clock=_Clock())
    key = normalize_mpn("ABC")
    bad = tmp_path / f"mpn___{key}___1000.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")
    assert c.get("ABC") is None
    assert not bad.exists()


def test_get_returns_the_newest_entry_when_an_old_one_lingers(tmp_path):
    # If _clear cannot remove an old entry (a persistent Windows lock, now swallowed), a newer put
    # still wins: get() must return the NEWEST stamp, never let a stale older file shadow it.
    c = TtlCache(tmp_path, ttl=1e9, clock=_Clock())
    key = normalize_mpn("ABC")
    (tmp_path / f"mpn___{key}___1000.json").write_text('{"v": 1}', encoding="utf-8")
    (tmp_path / f"mpn___{key}___1005.json").write_text('{"v": 2}', encoding="utf-8")
    assert c.get("ABC") == {"v": 2}  # the newest entry, not the older (1000) one


def test_get_and_put_never_raise_or_poison_under_concurrency(tmp_path):
    # The parallel read lane runs two enrich jobs for the SAME normalized MPN at once (a bulk
    # import overlapping an Add-A-Part lookup). Unguarded unlinks and a non-atomic write would
    # raise (a spurious lookup error) or interleave into a torn JSON that poisons the key for a
    # full TTL. get()/put() must stay raise-free and never leave the key un-loadable.
    c = TtlCache(tmp_path, prefix="mpn")  # real wall-clock
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            for _ in range(40):
                c.put("SAME-MPN", {"n": i, "specs": list(range(30))})
                c.get("SAME-MPN")
        except Exception as e:  # noqa: BLE001 - catching a spurious raise is the whole point
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [], f"cache raised under concurrency: {errors[:3]}"
    # the key is not poisoned: a final read returns a complete dict (or a clean miss), never raises
    final = c.get("SAME-MPN")
    assert final is None or isinstance(final, dict)
