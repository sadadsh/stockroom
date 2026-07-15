/**
 * Merge a pulled product-page result (the pasted purchase link) onto a staging
 * candidate produced by inspecting a vendor ZIP. The link is the authority for the
 * part's DATA (identity, specs, price, buy link); the ZIP is the authority for its
 * ASSETS (symbol, footprint, 3D). So a non-passive part the user pastes a link for and
 * then drops a SnapEDA ZIP into carries everything the page gave without re-typing it.
 */
import type { EnrichmentResult, StagingCandidate } from "../api/types";

function sv(s: { value: unknown } | null | undefined): string {
  return s == null ? "" : String(s.value ?? "");
}

export function vendorFromUrl(url: string): string {
  let host = "";
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch {
    return "manual";
  }
  if (host.includes("mouser")) return "Mouser";
  if (host.includes("lcsc")) return "LCSC";
  if (host.includes("digikey")) return "DigiKey";
  return host.replace(/^www\./, "") || "manual";
}

export function mergeResultIntoCandidate(
  candidate: StagingCandidate,
  result: EnrichmentResult,
  url: string,
): StagingCandidate {
  const mpn = sv(result.mpn);
  const manufacturer = sv(result.manufacturer);
  const description = sv(result.description);
  const pkg = sv(result.package);

  // The pulled parametric specs win for their keys (the distributor data is
  // authoritative); the internal product_url marker never becomes a spec row.
  const specs: Record<string, unknown> = { ...candidate.specs };
  for (const [k, v] of Object.entries(result.specs)) {
    if (k === "product_url" || v == null) continue;
    specs[k] = String(v.value ?? "");
  }
  if (pkg && specs.Package == null) specs.Package = pkg;

  const stockNum =
    result.stock != null && Number.isFinite(Number(result.stock.value))
      ? Number(result.stock.value)
      : null;
  const purchase = url
    ? [
        {
          vendor: vendorFromUrl(url),
          url,
          price_breaks: result.price_breaks.map((b) => ({ qty: b.qty, price: b.price })),
          stock: stockNum,
        },
      ]
    : candidate.purchase;

  return {
    ...candidate,
    mpn: mpn || candidate.mpn,
    manufacturer: manufacturer || candidate.manufacturer,
    description: description || candidate.description,
    display_name: candidate.display_name || mpn,
    category: candidate.category || result.category,
    specs,
    purchase,
  };
}
