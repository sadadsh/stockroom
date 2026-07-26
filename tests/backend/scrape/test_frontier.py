import asyncio

from stockroom.scrape.crawl.frontier import Frontier, Scope, canonical_url


def test_canonical_drops_fragment_tracking_and_lowercases_host():
    assert (canonical_url("HTTPS://WWW.Ex.com/Path?utm_source=x&b=2&a=1#frag")
            == "https://www.ex.com/Path?a=1&b=2")
    assert canonical_url("http://ex.com:80/p") == "http://ex.com/p"
    assert canonical_url("https://ex.com:443/p") == "https://ex.com/p"


def test_add_dedups_canonical_and_respects_scope_and_depth():
    f = Frontier(Scope(host="ex.com", max_depth=1, max_pages=10))
    assert f.add("https://ex.com/a", 0) is True
    assert f.add("https://ex.com/a?utm_source=x", 0) is False   # same canonical
    assert f.add("https://other.com/a", 0) is False             # off-host
    assert f.add("https://ex.com/b", 2) is False               # depth > max
    assert f.add("https://ex.com/b", 1) is True


def test_max_pages_caps_adds():
    f = Frontier(Scope(host="ex.com", max_depth=5, max_pages=2))
    assert f.add("https://ex.com/1", 0) is True
    assert f.add("https://ex.com/2", 0) is True
    assert f.add("https://ex.com/3", 0) is False               # capped at max_pages


def test_path_prefix_scope():
    f = Frontier(Scope(host="ex.com", path_prefix="/docs", max_pages=10))
    assert f.add("https://ex.com/docs/intro", 0) is True
    assert f.add("https://ex.com/blog/x", 0) is False


def test_content_hash_dedup():
    f = Frontier(Scope(host="ex.com"))
    assert f.seen_content("abc") is False
    assert f.seen_content("abc") is True                        # identical body already seen


def test_get_returns_added_items():
    f = Frontier(Scope(host="ex.com"))
    f.add("https://ex.com/x", 0)

    async def run():
        return await f.get()

    url, depth = asyncio.run(run())
    assert url == "https://ex.com/x" and depth == 0
