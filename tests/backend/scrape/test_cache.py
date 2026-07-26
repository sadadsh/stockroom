from stockroom.scrape.cache.store import ResponseCache
from stockroom.scrape.model import Page


def _page(url="https://x/p", status=200, text="<html>hi</html>"):
    return Page(url=url, final_url=url, status=status, content=text.encode(),
                text=text, content_type="text/html; charset=utf-8")


def test_put_then_get_roundtrips_and_marks_cache(tmp_path):
    c = ResponseCache(tmp_path)
    c.put(_page())
    hit = c.get("https://x/p")
    assert hit is not None
    assert hit.text == "<html>hi</html>"
    assert hit.content == b"<html>hi</html>"
    assert hit.from_cache is True
    assert hit.render_tier == "cache"


def test_miss_returns_none(tmp_path):
    assert ResponseCache(tmp_path).get("https://nope") is None


def test_expired_entry_is_evicted(tmp_path):
    t = {"now": 1000.0}
    c = ResponseCache(tmp_path, ttl=100.0, clock=lambda: t["now"])
    c.put(_page())
    t["now"] = 1000.0 + 150.0
    assert c.get("https://x/p") is None
    # a second get still None (file was removed, not just filtered)
    assert c.get("https://x/p") is None


def test_corrupt_entry_returns_none(tmp_path):
    c = ResponseCache(tmp_path)
    c.put(_page())
    # clobber the stored file with junk
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    files[0].write_text("not json", encoding="utf-8")
    assert c.get("https://x/p") is None
