from stockroom.enrich.cache import TtlCache


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
