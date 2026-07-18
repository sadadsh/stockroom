"""Readability-style main-content -> clean markdown (spec sections 3, 4 extract step).
Picks the densest content block (html.main_content), then walks it to markdown:
headings, paragraphs, lists, links (absolutized), code, and emphasis. Generic and
never raises; a parse failure yields an empty string, not an exception."""

from __future__ import annotations

from urllib.parse import urljoin

from stockroom.scrape.extract.html import main_content, parse

_HEADINGS = {"h1": "# ", "h2": "## ", "h3": "### ",
             "h4": "#### ", "h5": "##### ", "h6": "###### "}


def _inline(node, base_url: str) -> str:
    tag = node.tag
    if tag == "-text":
        return node.text(deep=False) or ""
    if tag == "a":
        href = (node.attributes.get("href") or "").strip()
        text = _children_inline(node, base_url).strip()
        if href and text:
            return f"[{text}]({urljoin(base_url, href)})"
        return text
    if tag in ("strong", "b"):
        return f"**{_children_inline(node, base_url).strip()}**"
    if tag in ("em", "i"):
        return f"*{_children_inline(node, base_url).strip()}*"
    if tag == "code":
        return f"`{(node.text() or '').strip()}`"
    if tag == "br":
        return "\n"
    return _children_inline(node, base_url)


def _children_inline(node, base_url: str) -> str:
    return "".join(_inline(c, base_url) for c in node.iter(include_text=True))


def _block(node, base_url: str, out: list[str]) -> None:
    tag = node.tag
    if tag in _HEADINGS:
        text = _children_inline(node, base_url).strip()
        if text:
            out.append(_HEADINGS[tag] + text)
        return
    if tag == "p":
        text = " ".join(_children_inline(node, base_url).split())
        if text:
            out.append(text)
        return
    if tag in ("ul", "ol"):
        ordered = tag == "ol"
        for i, li in enumerate(node.css("li"), start=1):
            text = " ".join(_children_inline(li, base_url).split())
            if text:
                out.append((f"{i}. " if ordered else "- ") + text)
        return
    if tag == "pre":
        code = (node.text() or "").strip("\n")
        if code:
            out.append("```\n" + code + "\n```")
        return
    # A generic container: recurse into its block children.
    for child in node.iter(include_text=False):
        _block(child, base_url, out)


def to_markdown(html: str, base_url: str = "") -> str:
    try:
        tree = parse(html)
        root = main_content(tree)
        if root is None:
            return ""
        out: list[str] = []
        for child in root.iter(include_text=False):
            _block(child, base_url, out)
        if not out:  # a flat node with only text
            return " ".join((root.text() or "").split())
        return "\n\n".join(part.strip() for part in out if part.strip())
    except Exception:  # noqa: BLE001 - content extraction never raises (spec section 3.1)
        return ""
