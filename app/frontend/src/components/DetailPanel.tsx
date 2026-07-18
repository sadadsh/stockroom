/**
 * The part detail panel, designed as an instrument readout (not a CRUD form).
 * Reads the full record from GET /api/library/parts/{id} and lays it out as:
 * an identity band (name headline + the MPN as a mono serial + a single Ready /
 * Missing verdict), the Part Canvas (the 3D physical object as the hero with the
 * schematic symbol + PCB footprint as its embodiments), a borderless datasheet
 * data grid (identity fields + parametric specs in the mono readout face), then
 * Pinout, Sourcing, and History. Everything degrades honestly when a field is
 * absent, and no data is fabricated.
 */
import { Fragment, useEffect, useState, type ReactNode } from "react";
import type { PartDetail, PurchaseRef, SourcedField } from "../api/types";
import { deriveTitle, deriveAttributes } from "../lib/derive";
import { groupSpecs, type SpecGroup } from "../lib/specSchema";
import { Badge, Button, Card } from "./primitives";
import { TextField } from "./formFields";
import { EditableText } from "./EditableText";
import { EnrichPanel } from "./EnrichPanel";
import { PinoutViewer, parsePinout } from "./PinoutViewer";
import { PartTimeline } from "./PartTimeline";
import { ConfirmDialog } from "./ConfirmDialog";
import { PreviewImage } from "./PreviewImage";
import { Glb3DView } from "./Glb3DView";
import { usePreviewGlb } from "../api/queries";
import { PreviewModal, type PreviewKind } from "./PreviewModal";
import {
  CubeArt,
  ExternalIcon,
  FootprintArt,
  SymbolArt,
  UploadIcon,
} from "./icons";

// The passport has seven required fields (stockroom.model.part.REQUIRED_FIELDS). Symbol,
// footprint, and 3D model no longer gate completeness: they are attached AFTER a part
// lands (see the Part Canvas), so they are not part of this score.
const PASSPORT_TOTAL = 7;

// Known EDA tools mapped to their proper casing; anything else is Title Cased from the raw
// value. A present asset always targets some tool, so an absent field reads as the backend
// default "kicad". Data-driven so a future Altium asset surfaces its own label with no code
// change.
const _KNOWN_TOOLS: Record<string, string> = {
  kicad: "KiCad",
  altium: "Altium",
};

export function toolLabel(tool: string | undefined): string {
  const t = (tool || "").trim();
  if (!t) return _KNOWN_TOOLS.kicad;
  const known = _KNOWN_TOOLS[t.toLowerCase()];
  if (known) return known;
  return t.replace(/\S+/g, (w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase());
}

// Spec presentation (grouping into Electrical / Physical / Ratings / Other, hidden-key and
// empty-value filtering, value+unit split) lives in lib/specSchema, shared with the parametric
// search and extensible: a brand-new spec key still groups sanely with no code change here.

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
  // Attaching a symbol / footprint reference AFTER the part exists (assets no longer
  // gate entry). Each takes a lib + name; omit them for a read-only panel and the
  // missing-asset tiles offer no Attach affordance.
  onAttachSymbol?: (lib: string, name: string) => void;
  onAttachFootprint?: (lib: string, name: string) => void;
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
  onAttachSymbol,
  onAttachFootprint,
  busy = false,
}: Props) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  // Which preview is expanded in the in-window modal (null = closed). The modal has
  // tabs, so this is only the tab it opens on.
  const [preview, setPreview] = useState<PreviewKind | null>(null);
  // Which missing asset's Attach modal is open (null = closed). Only symbol / footprint
  // have an attach endpoint, so the 3D model tile carries no Attach affordance.
  const [attachKind, setAttachKind] = useState<"symbol" | "footprint" | null>(null);
  // A passive owns no 3D-model file: it inherits the KiCad stock footprint's built-in model
  // (the model.glb endpoint resolves it from the footprint). So "has a 3D model" for a passive
  // is "has a footprint", not "has an owned model.file" (which the passive add correctly leaves
  // null). Without this a passive read "Not Linked" though its 3D rendered during add (A8).
  const hasModel = detail?.passive ? !!detail.footprint?.name : !!detail?.model?.file;
  // Inline 3D render (C1/C2): fetch + render the GLB right in the hero, auto-rotating and
  // pointer-events-none so it never fights the tile's own click. Enabled only for a part that
  // actually has a model, so a model-less part pays nothing.
  const modelGlb = usePreviewGlb(detail?.id ?? "", hasModel);
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
    return <PanelMessage>Select a part to see its details.</PanelMessage>;
  }

  const score = Math.max(0, PASSPORT_TOTAL - missing.length);
  // The part's tags plus a few chips derived from key specs (package, mounting,
  // qualifications, salient features), so the attribute band is never empty.
  const attributes = deriveAttributes(detail);
  // Grouped, extensible spec sheet (Electrical / Physical / Ratings / Other) from lib/specSchema.
  const specGroups = groupSpecs(detail.category, detail.specs);
  const specCount = specGroups.reduce((total, group) => total + group.rows.length, 0);
  // The persisted pinout (M6i) reads from the record's specs, its provenance from
  // the enrichment map. Shown when present, in both read-only and editable modes.
  const pinout = parsePinout(detail.specs);
  const pinoutProvenance = detail.enrichment?.pinout;

  return (
    <div className="max-w-[1240px] pb-12">
      {/* identity band: the name headline + the MPN as a mono serial stamp, with a
          single Ready / Missing verdict standing to the right. */}
      <div className="border-b border-line pb-5">
      <div className="flex items-start justify-between gap-6">
        <div className="min-w-0 flex-1">
          <h1 className="min-w-0 break-words text-[38px] font-semibold leading-[1.04] tracking-[-0.02em] text-t1">
            {deriveTitle(detail)}
          </h1>
          <SerialLine
            mpn={detail.mpn}
            manufacturer={detail.manufacturer}
            category={detail.category}
          />
        </div>
        <Verdict complete={isComplete} score={score} total={PASSPORT_TOTAL} />
      </div>

      {/* the missing fields, named, only when incomplete (the verdict already states the count) */}
      {!isComplete && missing.length > 0 ? (
        <div className="mt-3.5 flex flex-wrap items-center gap-1.5">
          <span className="mr-0.5 text-2xs uppercase tracking-wide text-t3">
            Needs
          </span>
          {missing.map((m) => (
            <Badge key={m} tone="warn" size="sm">
              {m}
            </Badge>
          ))}
        </div>
      ) : null}
      </div>

      {/* Attributes: a neutral tag band (no color), full width above the spec sheet. */}
      {attributes.length > 0 ? (
        <div className="mt-5 flex flex-wrap gap-2 rounded-card border border-line bg-raise px-4 py-3.5 shadow-card">
          {attributes.map((a) => (
            <span
              key={a}
              className="rounded-control bg-raise2 px-2.5 py-1 text-xs font-medium text-t2"
            >
              {a}
            </span>
          ))}
        </div>
      ) : null}

      {/* Main composition: a laid-out spec sheet, not a scroll. LEFT is the part seen
          three ways (the 3D hero + its symbol + footprint); RIGHT is the record (identity
          + sourcing). The horizontal space carries the grouping so nothing stacks dead. */}
      <div className="mt-7 grid grid-cols-[1.55fr_1fr] items-start gap-6">
        {/* LEFT: the Part Canvas, then the full spec sheet, so the column fills to
            balance the record column instead of stranding space below it. */}
        <div className="flex flex-col gap-7">
          <div>
          <SectionLabel>Part Canvas</SectionLabel>
          <div className="flex flex-col gap-3">
            <AssetTile
              variant="hero"
              name="3D Model"
              className="h-[336px]"
              present={hasModel}
              // A passive owns no model.file but inherits its stock footprint's built-in
              // model, so the tile's tool falls back to the footprint's tool there.
              tool={detail.model?.tool ?? detail.footprint?.tool}
              art={<CubeArt />}
              thumb={
                hasModel ? (
                  <div className="pointer-events-none h-full w-full">
                    <Glb3DView
                      data={modelGlb.data}
                      isLoading={modelGlb.isLoading}
                      isError={modelGlb.isError}
                      error={modelGlb.error}
                    />
                  </div>
                ) : undefined
              }
              onOpen={hasModel ? () => setPreview("model") : undefined}
            />
            <div className="grid grid-cols-2 gap-3">
              <AssetTile
                variant="tile"
                name="Symbol"
                className="h-[152px]"
                present={!!detail.symbol?.name}
                tool={detail.symbol?.tool}
                art={<SymbolArt />}
                thumb={
                  detail.symbol?.name ? (
                    <PreviewImage kind="symbol" partId={detail.id} fallback={<SymbolArt />} />
                  ) : undefined
                }
                onOpen={detail.symbol?.name ? () => setPreview("symbol") : undefined}
                onAttach={onAttachSymbol ? () => setAttachKind("symbol") : undefined}
              />
              <AssetTile
                variant="tile"
                name="Footprint"
                className="h-[152px]"
                present={!!detail.footprint?.name}
                tool={detail.footprint?.tool}
                art={<FootprintArt />}
                thumb={
                  detail.footprint?.name ? (
                    <PreviewImage kind="footprint" partId={detail.id} fallback={<FootprintArt />} />
                  ) : undefined
                }
                onOpen={detail.footprint?.name ? () => setPreview("footprint") : undefined}
                onAttach={onAttachFootprint ? () => setAttachKind("footprint") : undefined}
              />
            </div>
          </div>
          </div>
          {/* the datasheet parameter block sits under the canvas in the same column */}
          {specCount > 0 ? (
            <SpecificationsSection groups={specGroups} count={specCount} />
          ) : null}
        </div>

        {/* RIGHT: the record - identity fields + sourcing, filling the column */}
        <div className="flex flex-col gap-6">
          <div>
            <SectionLabel>Identity</SectionLabel>
            <div className="rounded-card border border-line bg-raise px-4 py-1 shadow-card">
              <DataRow
                label="Name"
                value={detail.display_name}
                onSave={onEditField ? (v) => onEditField("display_name", v) : undefined}
                busy={busy}
              />
              <DataRow
                label="Part Number"
                value={detail.mpn}
                mono
                onSave={onEditField ? (v) => onEditField("mpn", v) : undefined}
                busy={busy}
              />
              <DataRow
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
                <DataRow label="Category" value={detail.category} />
              )}
              <DataRow
                label="Description"
                value={detail.description}
                multiline
                onSave={onEditField ? (v) => onEditField("description", v) : undefined}
                busy={busy}
              />
              <DataRow
                label="Datasheet"
                // A clean "View Datasheet" link, not the raw full-length URL splashed across
                // the row. The URL rides the href; a file-only datasheet shows its filename.
                value={
                  detail.datasheet?.source_url ? "View Datasheet" : detail.datasheet?.file || ""
                }
                href={detail.datasheet?.source_url || undefined}
              />
              {onEditField ? (
                <DataRow
                  label="Tags"
                  value={detail.tags.join(", ")}
                  onSave={(v) => onEditField("tags", splitTags(v))}
                  busy={busy}
                />
              ) : detail.tags.length > 0 ? (
                <DataRow label="Tags" value={detail.tags.join(", ")} />
              ) : null}
            </div>
          </div>

          <div>
            <SectionLabel>Sourcing</SectionLabel>
            <Sourcing purchase={detail.purchase} hasMpn={!!detail.mpn} />
          </div>
        </div>
      </div>

      {/* Attach a missing symbol / footprint reference after the part landed (assets no
          longer gate entry). Mounted only while open so its form state starts fresh each
          time; the submit routes to the matching handler and defaults the tool to KiCad. */}
      {attachKind ? (
        <AttachAssetModal
          kind={attachKind}
          partName={detail.display_name}
          busy={busy}
          onCancel={() => setAttachKind(null)}
          onSubmit={(lib, name) => {
            if (attachKind === "symbol") onAttachSymbol?.(lib, name);
            else onAttachFootprint?.(lib, name);
            setAttachKind(null);
          }}
        />
      ) : null}

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

      {/* pinout: shown whenever the record carries one (read-only view of the
          persisted specs.pinout, source of truth per M6i). */}
      {pinout.length > 0 ? (
        <>
          <SectionLabel className="mt-9">Pinout</SectionLabel>
          <div>
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
        <div className="mt-9">
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
        </div>
      ) : null}

      {/* git timeline (M6k): the part's commit history + per-commit field/visual diff.
          Keyed by part id so the selected-commit state resets on a part switch. */}
      <SectionLabel className="mt-9">History</SectionLabel>
      <div>
        <PartTimeline key={detail.id} partId={detail.id} />
      </div>

      {/* a destructive action never earns prime real estate: it lives at the very
          bottom as a quiet text link that only reddens on hover. */}
      {onDelete ? (
        <div className="mt-8 border-t border-line pt-4">
          <button
            type="button"
            onClick={() => setConfirmDelete(true)}
            disabled={busy}
            className="text-xs text-t3 transition-colors hover:text-err disabled:opacity-50"
          >
            Delete Part
          </button>
        </div>
      ) : null}

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

// A section marker: a short copper tick + the label. The copper tick is the identity
// throughline that ties every section to the app's material (a trace on the board), and
// gives the long detail column a scannable rhythm instead of dim floating eyebrows.
function SectionLabel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={"mb-3 flex items-center gap-2.5 " + (className ?? "")}>
      <span className="h-3.5 w-[3px] flex-none rounded-full bg-acc" aria-hidden="true" />
      <span className="text-[12.5px] font-semibold tracking-tight text-t2">{children}</span>
    </div>
  );
}

// The identity serial line: a category dot, the MPN as the mono stamp (a part IS its
// part number), then the manufacturer and category as quiet context. Middot-separated,
// each piece dropping out honestly when the record does not carry it.
function SerialLine({
  mpn,
  manufacturer,
  category,
}: {
  mpn: string;
  manufacturer: string;
  category: string;
}) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1">
      <span className="h-1.5 w-1.5 flex-none rounded-full bg-t3" aria-hidden="true" />
      <span className="tnum font-mono text-sm text-t1">
        {mpn || <span className="font-sans italic text-t3">No Part Number</span>}
      </span>
      {manufacturer ? (
        <>
          <Middot />
          <span className="text-sm text-t2">{manufacturer}</span>
        </>
      ) : null}
      {category ? (
        <>
          <Middot />
          <span className="text-sm text-t3">{category}</span>
        </>
      ) : null}
    </div>
  );
}

function Middot() {
  return (
    <span className="text-t3" aria-hidden="true">
      ·
    </span>
  );
}

// The single completeness verdict, replacing the old ring + badge + dots trio. Quiet
// and confident when the part is Ready (an ok dot is the only color); a warn readout
// that draws the eye when fields are missing (attention belongs on the gap).
function Verdict({
  complete,
  score,
  total,
}: {
  complete: boolean;
  score: number;
  total: number;
}) {
  if (complete) {
    return (
      <div className="flex flex-none items-center gap-2.5 rounded-control bg-raise px-3.5 py-2 shadow-card">
        <span className="h-2 w-2 flex-none rounded-full bg-ok" aria-hidden="true" />
        <div className="leading-tight">
          <div className="text-sm font-semibold text-t1">Complete</div>
          <div className="tnum font-mono text-2xs text-t3">{total} of {total} fields</div>
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-none items-center gap-2.5 rounded-control bg-[rgba(224,179,84,0.11)] px-3.5 py-2">
      <span className="h-2 w-2 flex-none rounded-full bg-warn" aria-hidden="true" />
      <div className="leading-tight">
        <div className="text-sm font-semibold text-warn">Incomplete</div>
        <div className="tnum font-mono text-2xs text-t3">{score} of {total} fields</div>
      </div>
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
    <div className="flex gap-4 py-2">
      <span className="w-[96px] flex-none pt-1.5 text-sm text-t3">Category</span>
      <span className="flex min-w-0 flex-1 items-center">
        <span className="relative inline-block w-full max-w-[240px]">
          <select
            aria-label="Category"
            value={value}
            disabled={busy}
            onChange={(e) => {
              if (e.target.value !== value) onMove(e.target.value);
            }}
            className="w-full appearance-none rounded-control border border-line2 bg-field px-2.5 py-1.5 pr-8 text-sm text-t1 outline-none focus:border-acc disabled:cursor-not-allowed disabled:opacity-50"
          >
            {options.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <svg
            className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-t3"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            aria-hidden="true"
          >
            <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
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

// One borderless datasheet row: a fixed-width key in quiet sans, the value in the mono
// readout face (for machine data) or sans (for prose). Grouping comes from the shared
// left baseline and whitespace rhythm, not a hairline on every row.
function DataRow({
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
    <div className="flex gap-4 py-1.5">
      <span className="w-[96px] flex-none pt-1.5 text-sm text-t3">{label}</span>
      <span
        className={
          "flex min-w-0 flex-1 items-center gap-1.5 text-base " +
          (empty && !onSave ? "text-err" : "text-t1")
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
            className="inline-flex min-w-0 items-center gap-1.5 rounded-control px-1.5 py-1 font-medium text-t1 underline decoration-line2 underline-offset-2 transition-colors hover:bg-raise2 hover:decoration-current"
          >
            <span className="min-w-0 break-words">{value}</span>
            <ExternalIcon className="flex-none text-t3" />
          </a>
        ) : (
          <span className={"min-w-0 break-words px-1.5 " + (mono ? "tnum font-mono" : "")}>
            {value}
          </span>
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

// One Part Canvas tile. `hero` is the big physical (3D) stage; `tile` is a compact
// embodiment (symbol / footprint). Present -> the whole tile is a button that expands
// the preview; missing-with-handler -> a button that opens the Attach modal; missing
// read-only -> the honest Not Linked state. The recessed `stage` chamber makes a render
// read as a lit object, not a flat image.
function AssetTile({
  name,
  present,
  tool,
  art,
  thumb,
  onOpen,
  onAttach,
  variant,
  className,
}: {
  name: string;
  present: boolean;
  // The EDA tool the present asset targets, shown as a small pill (KiCad today,
  // Altium later). Read straight from the asset's `tool` field; absent reads as the
  // backend default (KiCad). Only meaningful when the asset is present.
  tool?: string;
  art: ReactNode;
  // The live render shown when present (falls back to `art` internally on failure);
  // omit it and `art` is shown directly.
  thumb?: ReactNode;
  // When present and set, the whole tile is a button that expands the preview.
  onOpen?: () => void;
  // When the asset is MISSING and set, the whole tile is a button that opens the
  // Attach modal. Ignored when the asset is present.
  onAttach?: () => void;
  variant: "hero" | "tile";
  // Height / extra classes for the tile shell (the caller sizes it in its layout).
  className?: string;
}) {
  const stage = (
    <div
      className={
        "relative flex min-h-0 flex-1 items-center justify-center overflow-hidden " +
        (present ? "bg-stage" : "flex-col gap-2 bg-stage text-t3")
      }
    >
      {/* the hero specimen chamber: a warm copper glow rising from the pedestal, a
          bright focus pool under the part, and an edge vignette, so the 3D reads as a
          lit object on a bench. Only when a specimen is present - no glow under an empty
          chamber. */}
      {variant === "hero" && present ? (
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(48% 42% at 50% 70%, var(--c-hero-glow), transparent 66%), radial-gradient(125% 120% at 50% 34%, transparent 50%, rgba(0,0,0,0.34))",
          }}
        />
      ) : null}
      <div className="relative flex h-full w-full items-center justify-center">
        {present ? (
          thumb ?? art
        ) : (
          <div className="flex flex-col items-center gap-2">
            <UploadIcon />
            <span className="text-xs">No {name}</span>
          </div>
        )}
      </div>
    </div>
  );
  const footer = (
    <div className="flex items-center gap-2 px-3 py-2.5">
      <span className="text-xs font-semibold text-t1">{name}</span>
      {present ? (
        <Badge tone="neutral" size="sm">
          {toolLabel(tool)}
        </Badge>
      ) : null}
      <span className="ml-auto inline-flex items-center gap-1.5 text-2xs text-t3">
        {present ? (
          <>
            <span className="h-1.5 w-1.5 rounded-full bg-ok" aria-hidden="true" />
            {onOpen ? "View" : "Linked"}
          </>
        ) : onAttach ? (
          <>
            <span className="h-1.5 w-1.5 rounded-full bg-warn" aria-hidden="true" />
            Attach
          </>
        ) : (
          <>
            <span className="h-1.5 w-1.5 rounded-full bg-warn" aria-hidden="true" />
            Not Linked
          </>
        )}
      </span>
    </div>
  );
  const base =
    "flex min-h-0 min-w-0 flex-col overflow-hidden rounded-card border bg-raise " +
    (variant === "hero"
      ? "border-line shadow-raise "
      : "border-line shadow-file ") +
    (className ?? "");
  const buttonCls =
    base +
    " cursor-pointer text-left transition-colors hover:border-line2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc";
  if (onOpen && present) {
    return (
      <button
        type="button"
        onClick={onOpen}
        aria-label={`Open ${name} Preview`}
        className={buttonCls}
      >
        {stage}
        {footer}
      </button>
    );
  }
  if (onAttach && !present) {
    return (
      <button
        type="button"
        onClick={onAttach}
        aria-label={`Attach ${name}`}
        className={buttonCls}
      >
        {stage}
        {footer}
      </button>
    );
  }
  return (
    <div className={base}>
      {stage}
      {footer}
    </div>
  );
}

// The Attach-a-reference modal: a lib + name form that POSTs a symbol / footprint
// reference onto an existing part (assets are attached after the part lands). Same
// scrim-and-card idiom as ConfirmDialog; the tool defaults to KiCad on the wire, so
// there is no tool picker here yet (a future Altium flow can add one). Escape or a
// scrim click cancels; Attach is disabled until a name is entered (the backend gate
// requires it).
function AttachAssetModal({
  kind,
  partName,
  busy,
  onSubmit,
  onCancel,
}: {
  kind: "symbol" | "footprint";
  partName: string;
  busy: boolean;
  onSubmit: (lib: string, name: string) => void;
  onCancel: () => void;
}) {
  const [lib, setLib] = useState("");
  const [name, setName] = useState("");
  const kindLabel = kind === "symbol" ? "Symbol" : "Footprint";
  // Examples steer the two halves of a KiCad lib_id (library nickname + entry name).
  const libExample = kind === "symbol" ? "Device" : "Resistor_SMD";
  const nameExample = kind === "symbol" ? "R" : "R_0603_1608Metric";

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const canSubmit = !!name.trim() && !busy;

  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center bg-black/50 p-4"
      role="presentation"
      onClick={onCancel}
    >
      <form
        className="w-full max-w-[420px] rounded-card border border-line bg-raise p-5 shadow-pop"
        role="dialog"
        aria-modal="true"
        aria-label={`Attach ${kindLabel}`}
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          if (canSubmit) onSubmit(lib.trim(), name.trim());
        }}
      >
        <div className="text-base font-semibold text-t1">Attach {kindLabel}</div>
        <div className="mt-2 text-sm text-t2">
          Reference a KiCad {kind} by its library and name for {partName}.
        </div>
        <div className="mt-4 flex flex-col gap-3">
          <TextField
            label="Library"
            value={lib}
            onChange={setLib}
            placeholder={libExample}
          />
          <TextField
            label="Name"
            value={name}
            onChange={setName}
            placeholder={nameExample}
          />
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button small type="button" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button small variant="accent" type="submit" disabled={!canSubmit}>
            Attach {kindLabel}
          </Button>
        </div>
      </form>
    </div>
  );
}

// B2 progressive disclosure: a deep part can carry ~28 specs; show the first (most important,
// insertion-ordered) ones and let the rest expand, so the section is scannable, not a wall.
const SPEC_COLLAPSE_AT = 12;

function SpecificationsSection({ groups, count }: { groups: SpecGroup[]; count: number }) {
  const [showAll, setShowAll] = useState(false);
  const collapsible = count > SPEC_COLLAPSE_AT;
  // Flatten to one ordered list (groups already come in Electrical -> Physical -> Ratings ->
  // Other order) so the collapse counts rows across groups; each row carries its group title so
  // the group eyebrow prints once, before that group's first shown row.
  const flat = groups.flatMap((g) => g.rows.map((r) => ({ ...r, group: g.title })));
  const shown = showAll || !collapsible ? flat : flat.slice(0, SPEC_COLLAPSE_AT);
  return (
    <>
      <SectionLabel>
        Specifications <span className="ml-0.5 font-mono text-t3">({count})</span>
      </SectionLabel>
      {/* a datasheet parameter block: two aligned columns, values in the mono readout face with
          tabular figures, sectioned by a full-width group eyebrow (Electrical / Physical / ...). */}
      <div className="grid grid-cols-1 border-t border-line pt-1 sm:grid-cols-2 sm:gap-x-10">
        {shown.map((row, i) => {
          const firstOfGroup = i === 0 || shown[i - 1].group !== row.group;
          return (
            <Fragment key={row.key}>
              {firstOfGroup ? (
                <div className="px-1.5 pb-1 pt-3 text-2xs font-semibold uppercase tracking-wide text-t3 first:pt-1 sm:col-span-2">
                  {row.group}
                </div>
              ) : null}
              <div className="flex items-baseline justify-between gap-4 px-1.5 py-[7px]">
                <span className="text-sm text-t3">{row.label}</span>
                <span className="tnum font-mono text-sm text-t1 text-right">
                  {row.unit ? `${row.value} ${row.unit}` : row.value}
                </span>
              </div>
            </Fragment>
          );
        })}
      </div>
      {collapsible ? (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="mt-2.5 text-xs font-medium text-t2 transition-colors hover:text-t1"
        >
          {showAll ? "Show Fewer" : `Show All ${count}`}
        </button>
      ) : null}
    </>
  );
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
    stats.push(["Unit Price", formatPrice(unit.price, purchase.currency)]);
  }

  return (
    <Card className="px-4 py-3.5">
      <div className="flex items-center gap-3">
        <span className="text-sm font-semibold text-t1">
          {vendorLabel(purchase.vendor, purchase.url)}
        </span>
        {purchase.part_number ? (
          <span className="tnum font-mono text-xs text-t3">{purchase.part_number}</span>
        ) : null}
        {purchase.fetched_at ? (
          <span className="text-2xs text-t3">Checked {purchase.fetched_at}</span>
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
            <div key={label} className="rounded-card bg-stage px-3 py-2.5">
              <div className="text-2xs text-t3">{label}</div>
              <div className="tnum mt-0.5 font-mono text-base font-semibold text-t1">
                {value}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {priceBreaks.length > 1 ? (
        <div className="mt-3">
          <div className="mb-2 text-xs font-semibold text-t3">Price Breaks</div>
          <div className="flex max-w-[480px] flex-col gap-2">
            {priceBreaks.map((b, i) => (
              <div key={i} className="flex items-center gap-3">
                <span className="tnum font-mono w-12 flex-none text-xs text-t3">{b.qty}+</span>
                <span className="tnum font-mono ml-auto w-16 text-right text-sm font-semibold text-t1">
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
