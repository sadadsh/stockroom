/**
 * Shorten a URL for display without hiding what it points at.
 *
 * The owner's note (2026-07-25) was "a bunch of links to stuff that are really long". Plain CSS
 * truncation is the wrong tool for a URL: it always cuts the TAIL, and a URL's tail is the only
 * part that identifies the document. Truncating
 * `https://www.ti.com/lit/ds/symlink/tpd6e05u06.pdf` gives `https://www.ti.com/lit/ds/sy…`,
 * which is indistinguishable from every other datasheet on the same host.
 *
 * So this keeps the two informative ends - the host and the final segment - and elides the middle:
 *
 *     https://www.ti.com/lit/ds/symlink/tpd6e05u06.pdf  ->  ti.com/…/tpd6e05u06.pdf
 *     https://www.mouser.com/ProductDetail/595-TPD6E05  ->  mouser.com/ProductDetail/595-TPD6E05
 *
 * Always pair the result with the full URL in a `title` (and keep the real href), so nothing is
 * actually lost - this shortens the LABEL, never the link.
 *
 * PRIOR ART evaluated before writing this (per the "bring in what already works" rule):
 *   * **`new URL()`** - the platform's own parser, and it IS adopted here. Hand-rolling URL
 *     parsing with a regex is the classic version of this mistake; only the DISPLAY rule below is
 *     ours, and it is ~40 lines rather than a dependency.
 *   * **`smart-truncate`** and **`truncate-middle`** - both truncate at a character INDEX. They
 *     have no notion of a host or a path segment, so they cannot produce `ti.com/…/name.pdf`;
 *     asked to elide the middle of the TI URL they cut mid-segment (`ti.com/lit/d…6e05u06.pdf`),
 *     which is the same unreadable result as CSS truncation with extra steps. REJECTED: they
 *     solve string truncation, and the problem here is URL structure.
 *   * **`autolinker`** - genuinely the closest: its `truncate: {location: "smart"}` strips the
 *     scheme and `www.` before eliding. REJECTED on scope: it is a text-to-anchor linkifier whose
 *     truncation is a side feature, and adopting a whole linkifier (which this app has no use
 *     for - the links are already anchors) to reuse one display rule is a poor trade.
 *   * **`react-middle-ellipsis` / `react-middle-truncate`** - measure the rendered box and cut to
 *     fit. REJECTED: they are components that own their own DOM and re-measure on resize, while
 *     what is needed here is a pure string function usable in a `title`, an `aria-label` and a
 *     test. Also character-based, so the same structural blindness as above.
 */

/** Strip the parts of a host that carry no information for a reader. */
function shortHost(host: string): string {
  return host.replace(/^www\./i, "");
}

export function compactUrl(raw: string, max = 44): string {
  const url = (raw ?? "").trim();
  if (!url) return "";

  // A local file path rather than a URL (a datasheet may be either): keep the file NAME, which is
  // the identifying part, and drop the directory chain.
  if (!/^https?:\/\//i.test(url)) {
    const name = url.split(/[/\\]/).filter(Boolean).pop() ?? url;
    return name.length <= max ? name : `${name.slice(0, max - 1)}…`;
  }

  let host: string;
  let path: string;
  try {
    const parsed = new URL(url);
    host = shortHost(parsed.hostname);
    path = parsed.pathname.replace(/\/+$/, "");
  } catch {
    // Not parseable. Fall back to a plain tail-truncation rather than throwing the string away:
    // a malformed URL is still worth showing, just not worth parsing.
    return url.length <= max ? url : `${url.slice(0, max - 1)}…`;
  }

  const segments = path.split("/").filter(Boolean);
  if (!segments.length) return host;

  const last = segments[segments.length - 1];
  const full = `${host}/${segments.join("/")}`;
  if (full.length <= max) return full;

  // One segment deep already, and still too long: the segment itself is the long part, so there is
  // no middle to elide. Truncate it, keeping the extension where there is one - a trailing `.pdf`
  // tells a reader what they are about to open.
  if (segments.length === 1) {
    const dot = last.lastIndexOf(".");
    const ext = dot > 0 && last.length - dot <= 6 ? last.slice(dot) : "";
    const room = Math.max(4, max - host.length - 2 - ext.length - 1);
    return `${host}/${last.slice(0, room)}…${ext}`;
  }
  return `${host}/…/${last}`;
}
