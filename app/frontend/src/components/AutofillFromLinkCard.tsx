/**
 * Paste a distributor product link (a Mouser URL) and pull EVERY field the page
 * exposes: identity, price, stock, datasheet, package, and the full parametric spec
 * table. The fetch runs through the app's real browser (WebView2) so bot-protected
 * pages that block a plain HTTP client are read anyway. This is the "paste a link and
 * autofill all of it" surface; it previews everything the page yielded.
 */
import { useState } from "react";
import { ApiError, api } from "../api/client";
import type { EnrichmentResult, SourcedField } from "../api/types";
import type { ToastTone } from "../lib/toast";
import { Badge, Button, Card, Eyebrow } from "./primitives";

function val(s: SourcedField | null | undefined): string {
  return s == null ? "" : String(s.value ?? "");
}

export function AutofillFromLinkCard({
  toast,
}: {
  toast: (message: string, tone?: ToastTone) => void;
}) {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<EnrichmentResult | null>(null);

  async function run() {
    const u = url.trim();
    if (!u || loading) return;
    setLoading(true);
    setResult(null);
    try {
      const r = await api.enrichFromUrl(u);
      setResult(r);
      const gotAnything =
        r.mpn || r.manufacturer || r.datasheet_url || Object.keys(r.specs).length > 0;
      if (!gotAnything) {
        toast("Nothing came back. The page may have blocked the fetch.", "neutral");
      }
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Autofill failed.", "err");
    } finally {
      setLoading(false);
    }
  }

  const specEntries = result
    ? Object.entries(result.specs).filter(
        ([k, v]) => k !== "product_url" && v != null,
      )
    : [];
  const identity = result
    ? ([
        ["MPN", val(result.mpn)],
        ["Manufacturer", val(result.manufacturer)],
        ["Description", val(result.description)],
        ["Package", val(result.package)],
        ["Stock", val(result.stock)],
        ["Datasheet", val(result.datasheet_url)],
      ] as [string, string][]).filter(([, v]) => v)
    : [];

  return (
    <Card className="px-4 py-3.5">
      <Eyebrow>Autofill From Link</Eyebrow>
      <p className="mb-3 mt-1 text-xs text-t3">
        Paste a Mouser (or other distributor) product link. The app opens it in its own
        browser and reads every field the page exposes.
      </p>
      <div className="flex items-center gap-3">
        <input
          aria-label="Product URL"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") run();
          }}
          placeholder="https://www.mouser.com/en/ProductDetail/..."
          disabled={loading}
          className="min-w-0 flex-1 rounded-control border border-line2 bg-field px-3 py-2 text-base text-t1 outline-none focus:border-acc disabled:opacity-50"
        />
        <Button
          variant="accent"
          onClick={run}
          disabled={loading || !url.trim()}
          className="flex-none"
        >
          {loading ? "Fetching..." : "Autofill Link"}
        </Button>
      </div>

      {result ? (
        <div className="mt-4 flex flex-col gap-4 rounded-card border border-line2 bg-raise2 p-4">
          {identity.length > 0 ? (
            <div className="grid grid-cols-1 gap-1.5 text-sm sm:grid-cols-[max-content_1fr] sm:gap-x-4">
              {identity.map(([k, v]) => (
                <div key={k} className="contents">
                  <span className="text-t3">{k}</span>
                  <span className="truncate text-t1">{v}</span>
                </div>
              ))}
            </div>
          ) : null}

          {result.price_breaks.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {result.price_breaks.map((b) => (
                <Badge key={b.qty} tone="neutral">
                  {b.qty}+: {b.price} {b.currency}
                </Badge>
              ))}
            </div>
          ) : null}

          {specEntries.length > 0 ? (
            <div>
              <div className="mb-1.5 text-xs text-t3">
                {specEntries.length} Specs
              </div>
              <div className="flex flex-wrap gap-2">
                {specEntries.map(([k, v]) => (
                  <Badge key={k} tone="neutral">
                    {k}: {val(v)}
                  </Badge>
                ))}
              </div>
            </div>
          ) : null}

          {identity.length === 0 && specEntries.length === 0 ? (
            <span className="text-sm text-warn">
              Nothing came back. The page likely blocked the fetch, or the link is not a
              product page.
            </span>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}
