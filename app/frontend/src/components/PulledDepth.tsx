/**
 * The sourcing DEPTH a distributor lookup pulled, rendered the SAME way in both Add-a-Part
 * branches (passive and non-passive) so the two flows feel and read identically (A2 + the
 * "consistency of feel AND logic" rule). It surfaces the live stock, factory lead time,
 * manufacturing lifecycle, best unit price, and the FULL price-break ladder the enrich layer
 * now pulls (which the UI previously dropped even though the record held it). Renders nothing
 * when a lookup carried none of it, so an empty or blocked fetch shows no hollow panel.
 */
import type { CatalogProductData, EnrichmentResult } from "../api/types";
import { Text, useCopyFormatter, useText } from "../lib/copy";
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

function availability(value: boolean | null): string {
  if (value === true) return "Available";
  if (value === false) return "Not Listed";
  return "Unknown";
}

function productCount(value: unknown): number {
  if (Array.isArray(value)) {
    return value.filter(
      (item) => item != null && typeof item === "object" && "ManufacturerProductNumber" in item,
    ).length + value.reduce((sum, item) => sum + productCount(item), 0);
  }
  if (value != null && typeof value === "object") {
    return Object.values(value).reduce((sum, item) => sum + productCount(item), 0);
  }
  return 0;
}

interface RelatedProduct {
  mpn: string;
  productNumber: string;
  manufacturer: string;
  description: string;
  url: string;
}

function objectText(value: unknown, nestedKey = ""): string {
  if (typeof value === "string" || typeof value === "number") return String(value).trim();
  if (value && typeof value === "object" && nestedKey) {
    return objectText((value as Record<string, unknown>)[nestedKey]);
  }
  return "";
}

function relatedProducts(value: unknown): RelatedProduct[] {
  const found: RelatedProduct[] = [];
  const seen = new Set<string>();
  function visit(item: unknown) {
    if (Array.isArray(item)) {
      item.forEach(visit);
      return;
    }
    if (!item || typeof item !== "object") return;
    const record = item as Record<string, unknown>;
    const mpn = objectText(record.ManufacturerProductNumber);
    const productNumber = objectText(record.DigiKeyProductNumber);
    if (mpn || productNumber) {
      const key = `${mpn}\u0000${productNumber}`;
      if (!seen.has(key)) {
        seen.add(key);
        found.push({
          mpn,
          productNumber,
          manufacturer: objectText(record.Manufacturer, "Name"),
          description:
            objectText(record.Description, "ProductDescription") ||
            objectText(record.DetailedDescription),
          url: objectText(record.ProductUrl),
        });
      }
    }
    Object.values(record).forEach(visit);
  }
  visit(value);
  return found;
}

function RelatedProducts({
  label,
  meaning,
  value,
}: {
  label: string;
  meaning: string;
  value: unknown;
}) {
  const products = relatedProducts(value);
  if (!products.length) return null;
  return (
    <section className="rounded-control border border-line2 bg-field p-2.5">
      <div className="flex items-baseline justify-between gap-3">
        <h4 className="text-xs font-semibold text-t1">{label}</h4>
        <span className="text-2xs tabular-nums text-t3">{products.length}</span>
      </div>
      <p className="mt-0.5 text-2xs text-t3">{meaning}</p>
      <div className="mt-2 max-h-32 space-y-1 overflow-y-auto pr-1">
        {products.map((product) => {
          const title = product.mpn || product.productNumber;
          const detail = [product.manufacturer, product.productNumber, product.description]
            .filter(Boolean)
            .join(" · ");
          return product.url ? (
            <a
              key={`${product.mpn}:${product.productNumber}`}
              href={product.url}
              target="_blank"
              rel="noreferrer"
              className="block rounded-control px-1.5 py-1 hover:bg-raise"
            >
              <span className="block text-xs font-medium text-acc">{title}</span>
              {detail ? <span className="block truncate text-2xs text-t3">{detail}</span> : null}
            </a>
          ) : (
            <div key={`${product.mpn}:${product.productNumber}`} className="px-1.5 py-1">
              <span className="block text-xs font-medium text-t1">{title}</span>
              {detail ? <span className="block truncate text-2xs text-t3">{detail}</span> : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function CatalogProductDataBlock({ data }: { data: CatalogProductData }) {
  return (
    <div className="flex flex-col gap-2 border-t border-line pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <Eyebrow>
          <Text id="depth.product-data">Product Data</Text>
        </Eyebrow>
        {data.availability.providers.map((provider) => (
          <Badge key={provider} tone="neutral">{provider}</Badge>
        ))}
        {data.product_url ? (
          <a href={data.product_url} target="_blank" rel="noreferrer" className="text-xs text-acc hover:underline">
            {data.product_number || data.manufacturer_product_number || "DigiKey Product"}
          </a>
        ) : null}
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="CAD Model" value={availability(data.availability.cad_model)} />
        <Stat label="3D Model" value={availability(data.availability.three_d_model)} />
        <Stat
          label="Alternate Packages"
          value={productCount(data.alternate_packaging).toLocaleString()}
        />
        <Stat
          label="Substitutions"
          value={productCount(data.substitutions).toLocaleString()}
        />
      </div>
      {data.media.length > 0 ? (
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
          {data.media.map((resource) => (
            <a
              key={`${resource.media_type}:${resource.url}`}
              href={resource.url}
              target="_blank"
              rel="noreferrer"
              className="text-acc hover:underline"
            >
              {resource.title || resource.media_type || "DigiKey Resource"}
            </a>
          ))}
        </div>
      ) : null}
      <div className="grid gap-2 sm:grid-cols-2">
        <RelatedProducts
          label="Alternate Packaging"
          meaning="The same component sold in another packaging or order format."
          value={data.alternate_packaging}
        />
        <RelatedProducts
          label="Substitutions"
          meaning="Potential replacements. Verify electrical and mechanical fit."
          value={data.substitutions}
        />
        <RelatedProducts
          label="Recommendations"
          meaning="DigiKey suggestions, kept separate from validated substitutes."
          value={data.recommended_products}
        />
        <RelatedProducts
          label="Associations"
          meaning="Mating connectors, kits, and companion products."
          value={data.associations}
        />
      </div>
    </div>
  );
}

export function PulledDepth({ result }: { result: EnrichmentResult }) {
  const priceLadderLabel = useText("depth.price-ladder", "Price Ladder");
  // The distributor name in the hole is a provider trade name; the verb around it is ours.
  const openOnDistributor = useCopyFormatter("depth.open-on-distributor", "Open on {distributor}");
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
  const digikey = result.catalog?.digikey;

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
  // "Product Status", not "Lifecycle": one concept, one spelling across the app, and this is the
  // distributors' own name for the field the value is read out of. See `interfaceTerms.ts`.
  if (lifecycle) stats.push(["Product Status", lifecycle]);
  if (best) stats.push(["Best Price", `${money(best.price, best.currency)}/ea`]);

  if (stats.length === 0 && breaks.length === 0 && distKeys.length === 0 && !digikey) return null;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <Eyebrow>
          <Text id="depth.sourcing">Sourcing</Text>
        </Eyebrow>
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
                  title={openOnDistributor({ distributor: label })}
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
      {digikey ? (
        <CatalogProductDataBlock data={digikey} />
      ) : null}
      {breaks.length > 0 ? (
        <div
          className="max-h-44 overflow-y-auto border-t border-line pt-3"
          role="region"
          aria-label={priceLadderLabel}
          tabIndex={0}
        >
          <table className="w-full text-sm">
            <thead>
              <tr className="text-2xs font-medium text-t3">
                <th scope="col" className="pb-2 text-left">
                  <Text id="depth.col-order-size">Order Size</Text>
                </th>
                <th scope="col" className="pb-2 text-right">
                  <Text id="depth.col-unit-price">Unit Price</Text>
                </th>
                <th scope="col" className="pb-2 text-right">
                  <Text id="depth.col-order-total">Order Total</Text>
                </th>
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
