from stockroom.scrape.extract.content import to_markdown


def test_headings_and_paragraphs():
    md = to_markdown("<article><h1>Title</h1><p>Body text here that is long enough.</p></article>")
    assert "# Title" in md
    assert "Body text here that is long enough." in md


def test_lists_and_links_absolutized():
    html = ('<article><p>' + ('pad ' * 60) + '</p><ul><li>one</li><li>two</li></ul>'
            '<p>See <a href="/docs">docs</a>.</p></article>')
    md = to_markdown(html, base_url="https://x/p")
    assert "- one" in md and "- two" in md
    assert "[docs](https://x/docs)" in md


def test_never_raises_on_garbage():
    assert isinstance(to_markdown("<<<not html>>>"), str)
    assert to_markdown("") == ""
