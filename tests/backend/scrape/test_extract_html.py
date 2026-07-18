from stockroom.scrape.extract.html import (
    extract_links, main_content, parse, strip_non_content, visible_text,
)


def test_visible_text_drops_script_and_style_and_collapses_ws():
    html = ("<html><head><style>.a{}</style></head><body><p>Hello   world</p>"
            "<script>var x=1</script></body></html>")
    assert visible_text(html) == "Hello world"


def test_extract_links_absolutizes_dedups_and_filters_scheme():
    html = ('<a href="/a">1</a><a href="https://y/z">2</a>'
            '<a href="/a">dup</a><a href="mailto:x@y">no</a>'
            '<a href="javascript:void(0)">no</a>')
    links = extract_links(html, "https://x/base/page")
    assert links == ["https://x/a", "https://y/z"]


def test_strip_non_content_removes_chrome():
    tree = parse("<body><nav>menu</nav><article>real</article><footer>f</footer></body>")
    strip_non_content(tree)
    body_text = tree.body.text() if tree.body is not None else tree.root.text()
    assert "menu" not in body_text and "real" in body_text


def test_main_content_picks_densest_block():
    tree = parse(
        "<body><nav>home about contact</nav>"
        "<div id='main'><p>" + ("word " * 80) + "</p></div>"
        "<aside>ads ads ads</aside></body>"
    )
    node = main_content(tree)
    assert node is not None and "word" in node.text()
