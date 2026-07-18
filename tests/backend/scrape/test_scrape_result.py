from stockroom.scrape.model import Page, ScrapeResult


def _page():
    return Page(url="https://x/p", final_url="https://x/p", status=200,
                content=b"<html></html>", text="<html></html>",
                content_type="text/html", render_tier="browser")


def test_scrape_result_defaults_are_independent():
    a = ScrapeResult(page=_page())
    b = ScrapeResult(page=_page())
    a.links.append("https://x/1")
    a.structured["k"] = 1
    assert b.links == [] and b.structured == {}  # no shared mutable default
    assert a.markdown == "" and a.product is None


def test_scrape_result_ok_delegates_to_page():
    assert ScrapeResult(page=_page()).ok is True
