/**
 * Enrich-to-fill: look a part up by its MPN through the enrichment pipeline
 * (scrape-first, spec section 6.1) and let the user apply the sourced identity
 * fields into the record. Only the fields the edit-field mutation can set cleanly
 * (manufacturer, description, both mirror to a symbol property and take a plain
 * string) get an Apply action. The datasheet URL, package, and stock are shown
 * honestly as "also found" but are not applied here: the datasheet needs the
 * PDF-fetch flow to fill the gate, and package/stock are not identity fields.
 * A scrape miss surfaces as "nothing found", never a fabricated value.
 */
import { useEnrichLookup } from "../api/queries";
import type { EnrichmentResult, SourcedField } from "../api/types";
import { Badge, Button, Card, Eyebrow } from "./primitives";
import { EnrichStages } from "./EnrichStages";
import { ExternalIcon } from "./icons";

interface Props {
  mpn: string;
  category: string;
  // The record's current identity values, so an already-set field shows
  // "Already Set" instead of a redundant Apply that would commit a no-op.
  current: { manufacturer: string; description: string };
  onApply: (field: string, value: string) => void;
  // The pinout persists through a different seam than editField (specs, not an
  // identity field), so it applies through its own callback. Omit it and no
  // pinout Apply is offered. hasPinout gates it to "Already Set".
  onApplyPinout?: (sourced: SourcedField) => void;
  hasPinout?: boolean;
  busy?: boolean;
}

// The identity fields enrichment can fill through editField.
const APPLIABLE: Array<{ field: "manufacturer" | "description"; label: string }> = [
  { field: "manufacturer", label: "Manufacturer" },
  { field: "description", label: "Description" },
];

function confidenceTone(confidence: string): "ok" | "neutral" | "warn" {
  if (confidence === "high") return "ok";
  if (confidence === "low") return "warn";
  return "neutral";
}

function hasAnyData(r: EnrichmentResult): boolean {
  return Boolean(
    r.manufacturer ||
      r.description ||
      r.datasheet_url ||
      r.stock ||
      r.package ||
      r.price_breaks.length ||
      Object.keys(r.specs).length,
  );
}

// The enriched pinout as a Sourced field with a non-empty pin list, or null.
function pinoutOf(r: EnrichmentResult): SourcedField | null {
  const p = r.specs.pinout;
  if (p && Array.isArray(p.value) && p.value.length > 0) return p;
  return null;
}

export function EnrichPanel({
  mpn,
  category,
  current,
  onApply,
  onApplyPinout,
  hasPinout = false,
  busy = false,
}: Props) {
  const enrich = useEnrichLookup();
  const result = enrich.result;
  const running = enrich.status === "running";

  return (
    <div>
      <Eyebrow className="mb-2.5 mt-6">Enrich</Eyebrow>
      <Card className="px-4 py-3.5">
        <div className="flex items-center gap-3">
          <span className="text-sm text-t2">
            Look up this part's manufacturer, description, and datasheet from its part number.
          </span>
          <Button
            variant="accent"
            small
            className="ml-auto flex-none"
            disabled={running}
            onClick={() => enrich.runPart(mpn, category)}
          >
            {running ? "Looking Up..." : "Enrich From Distributor"}
          </Button>
        </div>

        {running ? <EnrichStages progress={enrich.progress} className="mt-3.5" /> : null}

        {enrich.status === "error" ? (
          <div className="mt-3 text-sm text-err">
            Lookup failed. {enrich.error ?? "Unknown error."}
          </div>
        ) : null}

        {result && !running ? (
          hasAnyData(result) ? (
            <div className="mt-3.5 flex flex-col gap-1">
              {APPLIABLE.map(({ field, label }) => (
                <CandidateRow
                  key={field}
                  label={label}
                  sourced={result[field]}
                  current={current[field]}
                  onApply={(v) => onApply(field, v)}
                  busy={busy}
                />
              ))}
              {onApplyPinout && pinoutOf(result) ? (
                <PinoutRow
                  sourced={pinoutOf(result) as SourcedField}
                  already={hasPinout}
                  onApply={onApplyPinout}
                  busy={busy}
                />
              ) : null}
              <AlsoFound result={result} />
            </div>
          ) : (
            <div className="mt-3 text-sm text-t3">
              No new data found for this part number.
            </div>
          )
        ) : null}
      </Card>
    </div>
  );
}

function CandidateRow({
  label,
  sourced,
  current,
  onApply,
  busy,
}: {
  label: string;
  sourced: SourcedField | null;
  current: string;
  onApply: (value: string) => void;
  busy?: boolean;
}) {
  const value = sourced ? String(sourced.value) : "";
  const already = value.trim() !== "" && value.trim() === current.trim();
  return (
    <div className="flex items-center gap-3 border-b border-line py-2 last:border-b-0">
      <span className="w-[116px] flex-none text-xs text-t3">{label}</span>
      {sourced ? (
        <>
          <span className="min-w-0 flex-1 break-words text-base text-t1">{value}</span>
          <Badge tone={confidenceTone(sourced.confidence)}>
            {sourced.source} · {sourced.confidence}
          </Badge>
          {already ? (
            <span className="flex-none text-xs text-t3">Already Set</span>
          ) : (
            <Button small disabled={busy} onClick={() => onApply(value)}>
              Apply
            </Button>
          )}
        </>
      ) : (
        <span className="flex-1 text-sm text-t3">Not Found</span>
      )}
    </div>
  );
}

function PinoutRow({
  sourced,
  already,
  onApply,
  busy,
}: {
  sourced: SourcedField;
  already: boolean;
  onApply: (sourced: SourcedField) => void;
  busy?: boolean;
}) {
  const count = Array.isArray(sourced.value) ? sourced.value.length : 0;
  return (
    <div className="flex items-center gap-3 border-b border-line py-2 last:border-b-0">
      <span className="w-[116px] flex-none text-xs text-t3">Pinout</span>
      <span className="min-w-0 flex-1 break-words text-base text-t1">
        {count} {count === 1 ? "pin" : "pins"}
      </span>
      <Badge tone={confidenceTone(sourced.confidence)}>
        {sourced.source} · {sourced.confidence}
      </Badge>
      {already ? (
        <span className="flex-none text-xs text-t3">Already Set</span>
      ) : (
        <Button small disabled={busy} onClick={() => onApply(sourced)}>
          Apply Pinout
        </Button>
      )}
    </div>
  );
}

function AlsoFound({ result }: { result: EnrichmentResult }) {
  const ds = result.datasheet_url;
  const pkg = result.package;
  const stock = result.stock;
  if (!ds && !pkg && !stock) return null;
  return (
    <div className="flex flex-wrap items-center gap-3 pt-2.5 text-xs text-t3">
      <span>Also Found:</span>
      {ds ? (
        <a
          href={String(ds.value)}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-t2 underline decoration-line2 underline-offset-2 hover:decoration-current"
        >
          Datasheet
          <ExternalIcon />
        </a>
      ) : null}
      {pkg ? <span className="text-t2">Package {String(pkg.value)}</span> : null}
      {stock ? <span className="text-t2">Stock {String(stock.value)}</span> : null}
    </div>
  );
}
