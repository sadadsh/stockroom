from stockroom.scrape.model import Page, FetchError, FetchOutcome


def test_page_ok_true_for_2xx():
    p = Page(url="u", final_url="u", status=200, content=b"x", text="x",
             content_type="text/html")
    assert p.ok is True
    assert p.render_tier == "http"
    assert p.from_cache is False


def test_page_ok_false_for_403():
    p = Page(url="u", final_url="u", status=403, content=b"", text="",
             content_type="text/html")
    assert p.ok is False


def test_fetch_error_never_ok_and_carries_kind():
    e = FetchError(url="u", reason="blocked by WAF", kind="blocked", status=403)
    assert e.ok is False
    assert e.kind == "blocked"
    assert e.status == 403


def test_fetch_outcome_is_page_or_error():
    outcomes: list[FetchOutcome] = [
        Page(url="u", final_url="u", status=200, content=b"", text="",
             content_type=""),
        FetchError(url="u", reason="x", kind="timeout"),
    ]
    assert outcomes[0].ok is True and outcomes[1].ok is False
