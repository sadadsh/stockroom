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


# --- adversarial-review fixes (S3 Task 9) ---

def test_loose_text_and_inline_children_of_a_container_are_emitted():
    # finding [1]: a link / bold / bare text that is a DIRECT child of a container
    # (not wrapped in <p>) must still reach the markdown, not vanish.
    html = ('<article><p>' + ('pad ' * 60) + '</p>'
            '<a href="/datasheet.pdf">Download datasheet</a> loose words '
            '<strong>bold bit</strong></article>')
    md = to_markdown(html, base_url="https://ex.com/page")
    assert "[Download datasheet](https://ex.com/datasheet.pdf)" in md
    assert "loose words" in md
    assert "bold bit" in md


def test_nested_list_is_not_duplicated_and_ordered_numbering_is_sequential():
    # finding [3]: node.css('li') grabbed ALL descendant <li>, duplicating the nested
    # item and mis-numbering the ordered list.
    html = ('<article><p>' + ('pad ' * 60) + '</p>'
            '<ol><li>first</li><li>second<ul><li>subA</li></ul></li></ol></article>')
    md = to_markdown(html)
    assert "1. first" in md and "2. second" in md
    assert md.count("subA") == 1  # nested item emitted exactly once, not duplicated


def test_deeply_nested_dom_does_not_silently_return_empty():
    # finding [4]: a RecursionError in the walker was swallowed, losing the whole page.
    html = "<article>" + "<div>" * 700 + "deep real content here" + "</div>" * 700 + "</article>"
    md = to_markdown(html)
    assert "deep real content here" in md
