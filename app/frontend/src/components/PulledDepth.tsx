/**
 * The sourcing DEPTH a distributor lookup pulled, rendered the SAME way in both Add-a-Part
 * branches (passive and non-passive) so the two flows feel and read identically (A2 + the
 * "consistency of feel AND logic" rule). It surfaces the live stock, factory lead time,
 * manufacturing lifecycle, best unit price, and the FULL price-break ladder the enrich layer
 * now pulls (which the UI previously dropped even though the record held it). Renders nothing
 * when a lookup carried none of it, so an empty or blocked fetch shows no hollow panel.
 */
import type { EnrichmentResult } from "../api/types";
import { distributorLabel, sv } from "../lib/sourced";
import { Badge, Eyebrow } from "./primitives";

const CURRENCY_SYMBOL: Record<string, string> = { USD: "$", EUR: "€", GBP: "£" };

function money(value: number, currency: string): string {
  const sym = CURRENCY_SYMBOL[currency] ?? "";
  // A sub-dollar UNIT price keeps its precision and trims trailing zeros ($0.043, $0.31); a
  // dollar amount (an order total like $1,075.00) reads as conventional currency, grouped with
  // thousands separators and two decimals so ordering many shows its real total.
  const opts =
    Math.abs(value) < 1 && value !== 0
      ? { minimumFractionDigits: 0, maximumFractionDigits: 4 }
      : { minimumFractionDigits: 2, maximumFractionDigits: 2 };
  return `${sym}${value.toLocaleString("en-US", opts)}`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-control border border-line2 bg-field px-3 py-2">
      <span className="text-2xs font-medium text-t3">{label}</span>
      <span className="text-sm font-medium text-t1">{value}</span>
    </div>
  );
}

export function PulledDepth({ result }: { result: EnrichmentResult }) {
  const stockNum =
    result.stock != null && Number.isFinite(Number(result.stock.value))
      ? Number(result.stock.value)
      : null;
  const lifecycle = sv(result.lifecycle);
  const lead = sv(result.lead_time);
  const breaks = result.price_breaks ?? [];
  const best =
    breaks.length > 0
      ? breaks.reduce((a, b) => (b.price < a.price ? b : a))
      : null;

  // The union of every distributor we captured a link OR an order number for, so BOTH the Mouser
  // and DigiKey buy links show when both APIs answered (the owner's "store + display both links").
  const distUrls = result.dist_urls ?? {};
  const distPns = result.dist_pns ?? {};
  const distKeys = Array.from(new Set([...Object.keys(distPns), ...Object.keys(distUrls)])).filter(
    (k) => distPns[k] || distUrls[k],
  );

  const stats: [string, string][] = [];
  if (stockNum != null) stats.push(["Stock", `${stockNum.toLocaleString()} in stock`]);
  if (lead) stats.push(["Lead Time", lead]);
  if (lifecycle) stats.push(["Lifecycle", lifecycle]);
  if (best) stats.push(["Best Price", `${money(best.price, best.currency)}/ea`]);

  if (stats.length === 0 && breaks.length === 0 && distKeys.length === 0) return null;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <Eyebrow>Sourcing</Eyebrow>
        {/* each distributor as a clickable buy link (when we have its url) + its own order number,
            together as the source identity; both Mouser and DigiKey show when both APIs answered */}
        {distKeys.map((key) => {
          const pn = distPns[key] ?? "";
          const href = distUrls[key] ?? "";
          const label = distributorLabel(key);
          return (
            <span key={key} className="inline-flex items-center gap-1.5">
              {href ? (
                <a
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-control outline-none hover:brightness-110 focus-visible:ring-2 focus-visible:ring-acc"
                  title={`Open on ${label}`}
                >
                  <Badge tone="ok">{label}</Badge>
                </a>
              ) : (
                <Badge tone="neutral">{label}</Badge>
              )}
              {pn ? <span className="text-xs text-t2">{pn}</span> : null}
            </span>
          );
        })}
      </div>
      {stats.length > 0 ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {stats.map(([label, value]) => (
            <Stat key={label} label={label} value={value} />
          ))}
        </div>
      ) : null}
      {breaks.length > 0 ? (
        <div
          className="max-h-44 overflow-y-auto border-t border-line pt-3"
          role="region"
          aria-label="Price Ladder"
          tabIndex={0}
        >
          <table className="w-full text-sm">
            <thead>
              <tr className="text-2xs font-medium text-t3">
                <th scope="col" className="pb-2 text-left">Order Size</th>
                <th scope="col" className="pb-2 text-right">Unit Price</th>
                <th scope="col" className="pb-2 text-right">Order Total</th>
              </tr>
            </thead>
            <tbody>
              {breaks.map((b) => (
                <tr key={b.qty} className="border-t border-line">
                  <td className="py-1 tabular-nums text-t2">{b.qty.toLocaleString()}</td>
                  <td className="py-1 text-right tabular-nums text-t2">
                    {money(b.price, b.currency)}
                  </td>
                  <td className="py-1 text-right tabular-nums text-t1">
                    {money(b.qty * b.price, b.currency)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
