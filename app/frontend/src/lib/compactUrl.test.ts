import { describe, expect, it } from "vitest";
import { compactUrl } from "./compactUrl";

describe("compactUrl", () => {
  it("keeps the host and the identifying last segment, eliding the middle", () => {
    // The case the owner reported: a real TI datasheet URL, in a cell too narrow for it. What
    // matters is that the FILE NAME survives - it is the only part that distinguishes this
    // datasheet from every other one on the same host, and it is exactly what tail-truncation
    // destroys. Compare: a 30-char CSS truncation of the same string yields "ti.com/lit/ds/symlin…".
    expect(compactUrl("https://www.ti.com/lit/ds/symlink/tpd6e05u06.pdf", 30)).toBe(
      "ti.com/…/tpd6e05u06.pdf",
    );
  });

  it("leaves a URL that already fits completely alone", () => {
    // Nothing is elided just because it COULD be: the full path is more informative than the
    // shortened one whenever there is room for it.
    expect(compactUrl("https://www.mouser.com/ProductDetail/595-TPD6E05")).toBe(
      "mouser.com/ProductDetail/595-TPD6E05",
    );
    expect(compactUrl("https://www.ti.com/lit/ds/symlink/tpd6e05u06.pdf")).toBe(
      "ti.com/lit/ds/symlink/tpd6e05u06.pdf",
    );
  });

  it("drops www and the scheme, which carry no information for a reader", () => {
    expect(compactUrl("https://www.digikey.com/short")).toBe("digikey.com/short");
  });

  it("returns the bare host when there is no path to show", () => {
    expect(compactUrl("https://www.ti.com/")).toBe("ti.com");
    expect(compactUrl("https://ti.com")).toBe("ti.com");
  });

  it("keeps the extension when the single segment is itself too long", () => {
    // No middle to elide here, so the segment is cut - but a reader must still be able to see
    // that the link opens a PDF.
    const out = compactUrl("https://ti.com/averyveryverylongsingledatasheetsegmentname.pdf", 30);
    expect(out.startsWith("ti.com/")).toBe(true);
    expect(out.endsWith(".pdf")).toBe(true);
    expect(out).toContain("…");
  });

  it("shows a local datasheet FILE by its name, not its directory chain", () => {
    // A datasheet may be a stored file rather than a URL. The folder chain is machine-specific
    // noise; the file name is the part a person recognises.
    expect(compactUrl("/home/sadad/libraries/Stockroom/datasheets/tpd6e05u06.pdf")).toBe(
      "tpd6e05u06.pdf",
    );
    expect(compactUrl("C:\\stockroom\\datasheets\\tpd6e05u06.pdf")).toBe("tpd6e05u06.pdf");
  });

  it("still shows something for a string it cannot parse", () => {
    // A malformed value is worth showing; throwing it away would leave a blank cell that reads
    // as "no datasheet" when one is actually recorded.
    expect(compactUrl("not a url at all")).toBe("not a url at all");
  });

  it("is empty only for genuinely empty input", () => {
    expect(compactUrl("")).toBe("");
    expect(compactUrl("   ")).toBe("");
  });

  it("never returns more than the caller's budget plus the ellipsis it inserted", () => {
    // A guard on the whole point of the function: a "compact" URL that is still 200 characters
    // would silently reintroduce the overflow this exists to stop.
    const long =
      "https://www.example.com/a/very/deep/path/with/many/segments/and/a/final/document-name.pdf";
    expect(compactUrl(long, 40).length).toBeLessThanOrEqual(41);
  });
});
