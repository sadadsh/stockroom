/**
 * The sourcing DEPTH a distributor lookup pulled, rendered the SAME way in both Add-a-Part
 * branches (passive and non-passive) so the two flows feel and read identically (A2 + the
 * "consistency of feel AND logic" rule). It surfaces the live stock, factory lead time,
 * manufacturing lifecycle, best unit price, and the FULL price-break ladder the enrich layer
 * now pulls (which the UI previously dropped even though the record held it). Renders nothing
 * when a lookup carried none of it, so an empty or blocked fetch shows no hollow panel.
 */
import type { EnrichmentResult } from "../api/types";
import { Eyebrow } from "./primitives";

function sv(s: { value: unknown } | null | undefined): string {
  return s == null ? "" : String(s.value ?? "");
}

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
      <span className="text-2xs uppercase tracking-wide text-t3">{label}</span>
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

  const stats: [string, string][] = [];
  if (stockNum != null) stats.push(["Stock", `${stockNum.toLocaleString()} in stock`]);
  if (lead) stats.push(["Lead Time", lead]);
  if (lifecycle) stats.push(["Lifecycle", lifecycle]);
  if (best) stats.push(["Best Price", `${money(best.price, best.currency)}/ea`]);

  if (stats.length === 0 && breaks.length === 0) return null;

  return (
    <div className="flex flex-col gap-3">
      <Eyebrow>Sourcing</Eyebrow>
      {stats.length > 0 ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {stats.map(([label, value]) => (
            <Stat key={label} label={label} value={value} />
          ))}
        </div>
      ) : null}
      {breaks.length > 0 ? (
        <div className="rounded-card border border-line2 bg-raise2 p-3">
          <div className="mb-2 grid grid-cols-3 text-2xs uppercase tracking-wide text-t3">
            <span>Order Size</span>
            <span className="text-right">Unit Price</span>
            <span className="text-right">Order Total</span>
          </div>
          <div className="flex max-h-44 flex-col gap-1 overflow-y-auto">
            {breaks.map((b) => (
              <div
                key={b.qty}
                className="grid grid-cols-3 border-b border-line pb-1 text-sm last:border-0 last:pb-0"
              >
                <span className="tabular-nums text-t2">{b.qty.toLocaleString()}</span>
                <span className="text-right tabular-nums text-t2">
                  {money(b.price, b.currency)}
                </span>
                <span className="text-right tabular-nums text-t1">
                  {money(b.qty * b.price, b.currency)}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
