"""selectolax (Lexbor) DOM utilities for the extraction layer. Generic, part-agnostic:
visible text, absolute in-page links, boilerplate stripping, and a readability-lite
main-content pick. Used by content.py (markdown) and available to any consumer."""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit

from selectolax.parser import HTMLParser, Node

_DROP_TAGS = (
    "script", "style", "noscript", "template", "svg", "iframe",
    "nav", "header", "footer", "aside", "form",
)
# Block-ish tags a readability pass scores as candidate content containers.
_BLOCK_TAGS = ("article", "main", "section", "div", "td")


def parse(html: str) -> HTMLParser:
    return HTMLParser(html or "")


def visible_text(html: str) -> str:
    tree = parse(html)
    for node in tree.css("script, style, noscript, template"):
        node.decompose()
    body = tree.body or tree.root
    text = body.text(separator=" ") if body is not None else ""
    return " ".join(text.split())


def extract_links(html: str, base_url: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for a in parse(html).css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href:
            continue
        absolute = urljoin(base_url, href)
        scheme = urlsplit(absolute).scheme.lower()
        if scheme not in ("http", "https"):
            continue
        if absolute not in seen:
            seen.add(absolute)
            out.append(absolute)
    return out


def strip_non_content(tree: HTMLParser) -> None:
    for sel in _DROP_TAGS:
        for node in tree.css(sel):
            node.decompose()


def _text_len(node: Node) -> int:
    try:
        return len(" ".join((node.text() or "").split()))
    except Exception:  # noqa: BLE001 - a detached node must not sink the pass
        return 0


def main_content(tree: HTMLParser) -> Node | None:
    """The block element carrying the most visible text after boilerplate is stripped
    (readability-lite). Prefers <article>/<main> when present; else the densest block."""
    strip_non_content(tree)
    for preferred in ("article", "main"):
        node = tree.css_first(preferred)
        if node is not None and _text_len(node) >= 200:
            return node
    best: Node | None = None
    best_len = 0
    for sel in _BLOCK_TAGS:
        for node in tree.css(sel):
            n = _text_len(node)
            if n > best_len:
                best, best_len = node, n
    return best or (tree.body or tree.root)
