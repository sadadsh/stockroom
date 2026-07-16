/**
 * The part detail panel (the mockup's renderDetail). Reads the full record from
 * GET /api/library/parts/{id} and lays it out as: identity header with the
 * completeness passport ring, a missing/complete block, the Files section
 * (3D model, symbol, footprint), read-only identity fields, and Sourcing driven
 * by the real purchase records. Everything degrades honestly when a field is
 * absent, and no data is fabricated.
 */
import { useState, type ReactNode } from "react";
import type { PartDetail, PurchaseRef, SourcedField } from "../api/types";
import { Badge, Button, Card, Dot, Eyebrow } from "./primitives";
import { EditableText } from "./EditableText";
import { EnrichPanel } from "./EnrichPanel";
import { PinoutViewer, parsePinout } from "./PinoutViewer";
import { PartTimeline } from "./PartTimeline";
import { ConfirmDialog } from "./ConfirmDialog";
import { CompletenessRing } from "./CompletenessRing";
import { PreviewImage } from "./PreviewImage";
import { PreviewModal, type PreviewKind } from "./PreviewModal";
import {
  CubeArt,
  ExternalIcon,
  FootprintArt,
  SymbolArt,
  UploadIcon,
  WarnIcon,
} from "./icons";

// The passport has ten required fields (stockroom.model.part.REQUIRED_FIELDS).
const PASSPORT_TOTAL = 10;

const _KNOWN_VENDORS: Record<string, string> = {
  lcsc: "LCSC",
  mouser: "Mouser",
  digikey: "DigiKey",
  arrow: "Arrow",
  newark: "Newark",
  farnell: "Farnell",
};

// A human vendor label for the Sourcing card: map a known distributor host to its
// proper name, otherwise Title Case the stored vendor. A generic stored vendor
// ("manual", "scrape") is replaced by the distributor derived from the URL, so a
// pasted Mouser link never shows a lowercase "manual".
function vendorLabel(vendor: string, url: string): string {
  let host = "";
  try {
    host = url ? new URL(url).hostname.toLowerCase() : "";
  } catch {
    host = "";
  }
  for (const [token, name] of Object.entries(_KNOWN_VENDORS)) {
    if (host.includes(token)) return name;
  }
  const v = (vendor || "").trim();
  if (!v || v.toLowerCase() === "manual" || v.toLowerCase() === "scrape") {
    if (host) return host.replace(/^www\./, "");
    return "Vendor";
  }
  return v.charAt(0).toUpperCase() + v.slice(1);
}

interface Props {
  detail: PartDetail | undefined;
  isLoading: boolean;
  error: Error | null;
  missing: string[];
  isComplete: boolean;
  // When provided, the identity fields become inline-editable and each save
  // routes through here (field name + new value). Omit it for a read-only panel.
  onEditField?: (field: string, value: unknown) => void;
  // Category is not an inline edit (it relocates the symbol + footprint), so it
  // moves through onMoveCategory, offered as a select over the known categories.
  onMoveCategory?: (category: string) => void;
  categories?: string[];
  // Deleting confirms in-window, then routes here.
  onDelete?: () => void;
  // Applying an enriched pinout persists through the specs seam (not editField);
  // omit it and the enrich panel offers no pinout Apply.
  onApplyPinout?: (sourced: SourcedField) => void;
  busy?: boolean;
}

export function DetailPanel({
  detail,
  isLoading,
  error,
  missing,
  isComplete,
  onEditField,
  onMoveCategory,
  categories,
  onDelete,
  onApplyPinout,
  busy = false,
}: Props) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  // Which preview is expanded in the in-window modal (null = closed). The modal has
  // tabs, so this is only the tab it opens on.
  const [preview, setPreview] = useState<PreviewKind | null>(null);
  // A passive owns no 3D-model file: it inherits the KiCad stock footprint's built-in model
  // (the model.glb endpoint resolves it from the footprint). So "has a 3D model" for a passive
  // is "has a footprint", not "has an owned model.file" (which the passive add correctly leaves
  // null). Without this a passive read "Not Linked" though its 3D rendered during add (A8).
  const hasModel = detail?.passive ? !!detail.footprint?.name : !!detail?.model?.file;
  if (isLoading) {
    return <PanelMessage>Loading part...</PanelMessage>;
  }
  if (error) {
    return (
      <PanelMessage tone="err">
        Could not load this part. {error.message}
      </PanelMessage>
    );
  }
  if (!detail) {
    return (
      <PanelMessage>Select A Part To See Its Details.</PanelMessage>
    );
  }

  const score = Math.max(0, PASSPORT_TOTAL - missing.length);
  const subtitle = [detail.mpn || "No Part Number", detail.manufacturer || "Unknown Maker"].join(
    "  ·  ",
  );
  // The persisted pinout (M6i) reads from the record's specs, its provenance from
  // the enrichment map. Shown when present, in both read-only and editable modes.
  const pinout = parsePinout(detail.specs);
  const pinoutProvenance = detail.enrichment?.pinout;

  return (
    <div className="max-w-[760px] pb-10">
      {/* header */}
      <div className="flex items-center gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-title font-semibold text-t1">
            {onEditField ? (
              <EditableText
                value={detail.display_name}
                onSave={(v) => onEditField("display_name", v)}
                label="Name"
                placeholder="Name This Part"
                disabled={busy}
                displayClassName="text-title font-semibold"
              />
            ) : (
              <span className="min-w-0 break-words">{detail.display_name}</span>
            )}
            {!isComplete ? (
              <span className="flex-none text-err" title="Incomplete">
                <WarnIcon />
              </span>
            ) : null}
          </div>
          <div className="mt-1 text-sm text-t3">{subtitle}</div>
        </div>
        <div className="flex flex-none items-center gap-3">
          {onDelete ? (
            <Button small onClick={() => setConfirmDelete(true)} disabled={busy}>
              Delete Part
            </Button>
          ) : null}
          <CompletenessRing
            score={score}
            total={PASSPORT_TOTAL}
            complete={isComplete}
          />
        </div>
      </div>

      {/* completeness block */}
      <div className="mt-4">
        {isComplete ? (
          <Badge tone="ok">Complete</Badge>
        ) : (
          <div>
            <div className="mb-2 block text-xs text-t3">Missing</div>
            <div className="flex flex-wrap gap-1.5">
              {missing.map((m) => (
                <Badge key={m} tone="warn">
                  {m}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* files */}
      <Eyebrow className="mb-2.5 mt-6">Files</Eyebrow>
      <div className="flex max-w-[600px] gap-3">
        <FileCard
          className="flex-[1.55]"
          name="3D Model"
          present={hasModel}
          art={<CubeArt />}
          onOpen={hasModel ? () => setPreview("model") : undefined}
        />
        <div className="flex flex-1 flex-col gap-3">
          <FileCard
            name="Symbol"
            present={!!detail.symbol?.name}
            art={<SymbolArt />}
            thumb={
              detail.symbol?.name ? (
                <PreviewImage
                  kind="symbol"
                  partId={detail.id}
                  fallback={<SymbolArt />}
                />
              ) : undefined
            }
            onOpen={detail.symbol?.name ? () => setPreview("symbol") : undefined}
          />
          <FileCard
            name="Footprint"
            present={!!detail.footprint?.name}
            art={<FootprintArt />}
            thumb={
              detail.footprint?.name ? (
                <PreviewImage
                  kind="footprint"
                  partId={detail.id}
                  fallback={<FootprintArt />}
                />
              ) : undefined
            }
            onOpen={detail.footprint?.name ? () => setPreview("footprint") : undefined}
          />
        </div>
      </div>

      <PreviewModal
        open={preview !== null}
        partId={detail.id}
        partName={detail.display_name}
        available={{
          model: hasModel,
          symbol: !!detail.symbol?.name,
          footprint: !!detail.footprint?.name,
        }}
        initialKind={preview ?? "symbol"}
        onClose={() => setPreview(null)}
      />

      {/* identity fields */}
      <Eyebrow className="mb-2.5 mt-6">Component Fields</Eyebrow>
      <div>
        <IdRow
          label="Part Number"
          value={detail.mpn}
          mono
          onSave={onEditField ? (v) => onEditField("mpn", v) : undefined}
          busy={busy}
        />
        <IdRow
          label="Manufacturer"
          value={detail.manufacturer}
          onSave={onEditField ? (v) => onEditField("manufacturer", v) : undefined}
          busy={busy}
        />
        {/* Category moves the symbol + footprint between libraries, so it is a
            select over known categories, not an inline field edit. */}
        {onMoveCategory && categories && categories.length > 0 ? (
          <CategoryRow
            value={detail.category}
            categories={categories}
            onMove={onMoveCategory}
            busy={busy}
          />
        ) : (
          <IdRow label="Category" value={detail.category} />
        )}
        <IdRow
          label="Description"
          value={detail.description}
          multiline
          onSave={onEditField ? (v) => onEditField("description", v) : undefined}
          busy={busy}
        />
        <IdRow
          label="Datasheet"
          value={detail.datasheet?.file || detail.datasheet?.source_url || ""}
          mono
          href={detail.datasheet?.source_url || undefined}
        />
        {onEditField ? (
          <IdRow
            label="Tags"
            value={detail.tags.join(", ")}
            onSave={(v) => onEditField("tags", splitTags(v))}
            busy={busy}
          />
        ) : detail.tags.length > 0 ? (
          <IdRow label="Tags" value={detail.tags.join(", ")} />
        ) : null}
      </div>

      {/* pinout: shown whenever the record carries one (read-only view of the
          persisted specs.pinout, source of truth per M6i). */}
      {pinout.length > 0 ? (
        <>
          <Eyebrow className="mb-2.5 mt-6">Pinout</Eyebrow>
          <div className="max-w-[600px]">
            {/* Keyed by part id so the viewer's own filter/sort state resets on a
                part switch (matches the EnrichPanel key below); a cached-part switch
                does not unmount the panel, so without this the filter would leak. */}
            <PinoutViewer
              key={detail.id}
              pins={pinout}
              source={pinoutProvenance?.source}
              confidence={pinoutProvenance?.confidence}
            />
          </div>
        </>
      ) : null}

      {/* enrich-to-fill: only in editable mode, and only when there is an MPN to
          look the part up by. Keyed by the MPN so switching parts starts fresh. */}
      {onEditField && detail.mpn ? (
        <EnrichPanel
          key={detail.mpn}
          mpn={detail.mpn}
          category={detail.category}
          current={{
            manufacturer: detail.manufacturer,
            description: detail.description,
          }}
          onApply={onEditField}
          onApplyPinout={onApplyPinout}
          hasPinout={pinout.length > 0}
          busy={busy}
        />
      ) : null}

      {/* sourcing */}
      <Eyebrow className="mb-2.5 mt-6">Sourcing</Eyebrow>
      <Sourcing purchase={detail.purchase} hasMpn={!!detail.mpn} />

      {/* git timeline (M6k): the part's commit history + per-commit field/visual diff.
          Keyed by part id so the selected-commit state resets on a part switch. */}
      <Eyebrow className="mb-2.5 mt-6">History</Eyebrow>
      <div className="max-w-[600px]">
        <PartTimeline key={detail.id} partId={detail.id} />
      </div>

      {onDelete ? (
        <ConfirmDialog
          open={confirmDelete}
          title="Delete This Part?"
          body={
            <>
              This removes {detail.display_name}'s symbol, footprint, and record in
              one commit. You can restore it from git history.
            </>
          }
          confirmLabel="Delete"
          danger
          busy={busy}
          onConfirm={() => {
            setConfirmDelete(false);
            onDelete();
          }}
          onCancel={() => setConfirmDelete(false)}
        />
      ) : null}
    </div>
  );
}

function CategoryRow({
  value,
  categories,
  onMove,
  busy,
}: {
  value: string;
  categories: string[];
  onMove: (category: string) => void;
  busy?: boolean;
}) {
  // Always include the current category, even if the facets have not caught up.
  const options = categories.includes(value) ? categories : [value, ...categories];
  return (
    <div className="flex gap-4 border-b border-line py-2 last:border-b-0">
      <span className="w-[116px] flex-none pt-1.5 text-xs text-t3">Category</span>
      <span className="flex min-w-0 flex-1 items-center">
        <select
          aria-label="Category"
          value={value}
          disabled={busy}
          onChange={(e) => {
            if (e.target.value !== value) onMove(e.target.value);
          }}
          className="rounded-control border border-line2 bg-field px-2 py-1 text-base text-t1 outline-none focus:border-acc disabled:cursor-not-allowed disabled:opacity-50"
        >
          {options.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </span>
    </div>
  );
}

function PanelMessage({
  children,
  tone,
}: {
  children: ReactNode;
  tone?: "err";
}) {
  return (
    <div
      className={
        "flex h-full min-h-[300px] items-center justify-center px-6 text-center text-sm " +
        (tone === "err" ? "text-err" : "text-t3")
      }
    >
      {children}
    </div>
  );
}

function IdRow({
  label,
  value,
  mono,
  href,
  onSave,
  multiline,
  busy,
}: {
  label: string;
  value: string;
  mono?: boolean;
  href?: string;
  onSave?: (value: string) => void;
  multiline?: boolean;
  busy?: boolean;
}) {
  const empty = !value;
  return (
    <div className="flex gap-4 border-b border-line py-2 last:border-b-0">
      <span className="w-[116px] flex-none pt-1.5 text-xs text-t3">{label}</span>
      <span
        className={
          "flex min-w-0 flex-1 items-center gap-1.5 text-base " +
          (empty && !onSave ? "text-err" : "text-t1") +
          (mono ? " tnum" : "")
        }
      >
        {onSave ? (
          <EditableText
            value={value}
            onSave={onSave}
            label={label}
            placeholder="Missing"
            mono={mono}
            multiline={multiline}
            disabled={busy}
          />
        ) : empty ? (
          "Missing"
        ) : href ? (
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-w-0 items-center gap-1.5 truncate text-t1 underline decoration-line2 underline-offset-2 hover:decoration-current"
          >
            <span className="truncate">{value}</span>
            <ExternalIcon className="flex-none text-t3" />
          </a>
        ) : (
          <span className="min-w-0 break-words">{value}</span>
        )}
      </span>
    </div>
  );
}

// Tags edit as a comma-separated string; store them as a clean array.
function splitTags(raw: string): string[] {
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

function FileCard({
  name,
  present,
  art,
  thumb,
  onOpen,
  className,
}: {
  name: string;
  present: boolean;
  art: ReactNode;
  // The live render shown when present (falls back to `art` internally on failure);
  // omit it and `art` is shown directly (the 3D card keeps its glyph, viewed on open).
  thumb?: ReactNode;
  // When present and set, the whole card is a button that expands the preview.
  onOpen?: () => void;
  className?: string;
}) {
  const stage = (
    <div
      className={
        "flex flex-1 items-center justify-center " +
        (present
          ? "bg-[rgba(0,0,0,0.18)] min-h-[118px]"
          : "flex-col gap-1.5 bg-[rgba(0,0,0,0.1)] min-h-[118px] text-t3")
      }
    >
      {present ? (
        thumb ?? art
      ) : (
        <>
          <UploadIcon />
          <span className="text-xs">No {name}</span>
        </>
      )}
    </div>
  );
  const footer = (
    <div className="flex items-center gap-2 px-3 py-2.5">
      <span className="text-xs font-medium text-t1">{name}</span>
      <span className="ml-auto inline-flex items-center gap-1.5 text-2xs text-t3">
        {present ? (
          <>
            <Dot tone="ok" />
            {onOpen ? "View" : "Linked"}
          </>
        ) : (
          <>
            <Dot tone="warn" />
            Not Linked
          </>
        )}
      </span>
    </div>
  );
  const cls =
    "flex min-w-0 flex-col overflow-hidden shadow-file " + (className ?? "");
  if (onOpen && present) {
    // A card-styled button (Card is a div, not polymorphic) so the whole tile is one
    // click target that expands the preview.
    return (
      <button
        type="button"
        onClick={onOpen}
        aria-label={`Open ${name} Preview`}
        className={
          "rounded-card border border-line bg-raise " +
          cls +
          " cursor-pointer text-left transition-colors hover:border-line2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
        }
      >
        {stage}
        {footer}
      </button>
    );
  }
  return <Card className={cls}>{stage}{footer}</Card>;
}

function Sourcing({
  purchase,
  hasMpn,
}: {
  purchase: PurchaseRef[];
  hasMpn: boolean;
}) {
  const orderable = purchase.filter((p) => p.url);
  if (orderable.length === 0) {
    return (
      <Card className="flex items-center gap-3.5 px-4 py-3.5">
        <span className="text-sm text-t2">
          {hasMpn
            ? "No purchase link on record yet."
            : "Not orderable yet, this component has no part number."}
        </span>
      </Card>
    );
  }
  return (
    <div className="flex flex-col gap-2.5">
      {orderable.map((p, i) => (
        <VendorCard key={`${p.vendor}-${i}`} purchase={p} />
      ))}
    </div>
  );
}

function VendorCard({ purchase }: { purchase: PurchaseRef }) {
  const stats: Array<[string, string]> = [];
  if (purchase.stock != null) {
    stats.push(["In Stock", purchase.stock.toLocaleString()]);
  }
  const priceBreaks = normalizePriceBreaks(purchase.price_breaks);
  const unit = priceBreaks.length > 0 ? priceBreaks[0] : null;
  if (unit) {
    stats.push([
      "Unit Price",
      formatPrice(unit.price, purchase.currency),
    ]);
  }

  return (
    <Card className="px-4 py-3.5">
      <div className="flex items-center gap-3">
        <span className="text-sm font-medium text-t1">
          {vendorLabel(purchase.vendor, purchase.url)}
        </span>
        {purchase.fetched_at ? (
          <span className="text-2xs text-t3">
            Checked {purchase.fetched_at}
          </span>
        ) : null}
        <a
          href={purchase.url}
          target="_blank"
          rel="noreferrer"
          className="ml-auto inline-flex items-center gap-1.5 rounded-control bg-raise2 px-3 py-1.5 text-xs font-medium text-t1 hover:brightness-110"
        >
          Open Listing
          <ExternalIcon />
        </a>
      </div>

      {stats.length > 0 ? (
        <div className="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
          {stats.map(([label, value]) => (
            <div
              key={label}
              className="rounded-card border border-line bg-raise px-3 py-2.5"
            >
              <div className="text-2xs text-t3">{label}</div>
              <div className="tnum mt-0.5 text-base font-semibold text-t1">
                {value}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {priceBreaks.length > 1 ? (
        <div className="mt-3">
          <div className="mb-2 text-xs font-semibold text-t3">
            Price Breaks
          </div>
          <div className="flex max-w-[480px] flex-col gap-2">
            {priceBreaks.map((b, i) => (
              <div key={i} className="flex items-center gap-3">
                <span className="tnum w-12 flex-none text-xs text-t3">
                  {b.qty}+
                </span>
                <span className="tnum ml-auto w-16 text-right text-sm font-semibold text-t1">
                  {formatPrice(b.price, purchase.currency)}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </Card>
  );
}

interface NormalizedBreak {
  qty: number;
  price: number;
}

// price_breaks come through as untyped lists; tolerate [qty, price] pairs or
// {qty|quantity|moq, price|unit|unit_price} objects, and drop anything unusable.
function normalizePriceBreaks(raw: unknown[]): NormalizedBreak[] {
  const out: NormalizedBreak[] = [];
  for (const item of raw) {
    if (Array.isArray(item) && item.length >= 2) {
      const qty = Number(item[0]);
      const price = Number(item[1]);
      if (Number.isFinite(qty) && Number.isFinite(price)) {
        out.push({ qty, price });
      }
    } else if (item && typeof item === "object") {
      const rec = item as Record<string, unknown>;
      const qty = Number(rec.qty ?? rec.quantity ?? rec.moq);
      const price = Number(rec.price ?? rec.unit ?? rec.unit_price);
      if (Number.isFinite(qty) && Number.isFinite(price)) {
        out.push({ qty, price });
      }
    }
  }
  return out.sort((a, b) => a.qty - b.qty);
}

function formatPrice(value: number, currency: string): string {
  const symbol = currency === "USD" || !currency ? "$" : "";
  const suffix = symbol ? "" : ` ${currency}`;
  return `${symbol}${value.toFixed(2)}${suffix}`;
}
