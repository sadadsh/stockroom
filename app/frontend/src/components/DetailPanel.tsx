/**
 * The part detail panel (the mockup's renderDetail). Reads the full record from
 * GET /api/library/parts/{id} and lays it out as: identity header with the
 * completeness passport ring, a missing/complete block, the Files section
 * (3D model, symbol, footprint), read-only identity fields, and Sourcing driven
 * by the real purchase records. Everything degrades honestly when a field is
 * absent, and no data is fabricated.
 */
import { useEffect, useState, type ReactNode } from "react";
import type { PartDetail, PurchaseRef, SourcedField } from "../api/types";
import { Badge, Button, Card, Dot, Eyebrow } from "./primitives";
import { TextField } from "./formFields";
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

// The passport has seven required fields (stockroom.model.part.REQUIRED_FIELDS). Symbol,
// footprint, and 3D model no longer gate completeness: they are attached AFTER a part
// lands (see the Files section), so they are not part of this score.
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

// Spec keys that are NOT parametric specs: the asset references (shown as Files cards) and the
// pinout (shown as its own table). Everything else in specs is a real spec the panel lists (B1).
const SPEC_HIDDEN_KEYS = new Set(["Symbol", "Footprint", "3D Model", "product_url", "pinout"]);

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
  // missing-asset cards offer no Attach affordance.
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
  // have an attach endpoint, so the 3D model card carries no Attach affordance.
  const [attachKind, setAttachKind] = useState<"symbol" | "footprint" | null>(null);
  // A passive owns no 3D-model file: it inherits the KiCad stock footprint's built-in model
  // (the model.glb endpoint resolves it from the footprint). So "has a 3D model" for a passive
  // is "has a footprint", not "has an owned model.file" (which the passive add correctly leaves
  // null). Without this a passive read "Not Linked" though its 3D rendered during add (A8).
  const hasModel = detail?.passive ? !!detail.footprint?.name : !!detail?.model?.file;
  // B1: every parametric spec the record holds (Resistance, Tolerance, Voltage Rating, ...) that
  // the panel used to hide - shown in a Specifications section. Asset/internal keys and the pinout
  // (rendered as its own table) are excluded; only scalar spec values are listed.
  const specRows = Object.entries(detail?.specs ?? {}).filter(
    ([key, value]) =>
      !SPEC_HIDDEN_KEYS.has(key) &&
      value != null &&
      typeof value !== "object" &&
      String(value).trim() !== "",
  );
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
      <PanelMessage>Select a part to see its details.</PanelMessage>
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
                placeholder="Name this part"
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
      <div className="flex max-w-[760px] gap-3">
        <FileCard
          className="flex-[1.55]"
          name="3D Model"
          present={hasModel}
          // A passive owns no model.file but inherits its stock footprint's built-in
          // model, so the 3D card's tool falls back to the footprint's tool there.
          tool={detail.model?.tool ?? detail.footprint?.tool}
          art={<CubeArt />}
          onOpen={hasModel ? () => setPreview("model") : undefined}
        />
        <div className="flex flex-1 flex-col gap-3">
          <FileCard
            name="Symbol"
            present={!!detail.symbol?.name}
            tool={detail.symbol?.tool}
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
            onAttach={onAttachSymbol ? () => setAttachKind("symbol") : undefined}
          />
          <FileCard
            name="Footprint"
            present={!!detail.footprint?.name}
            tool={detail.footprint?.tool}
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
            onAttach={onAttachFootprint ? () => setAttachKind("footprint") : undefined}
          />
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

      {/* specifications (B1) with progressive disclosure (B2): every parametric spec the record
          holds, collapsed to the key ones so a deep 28-spec part is scannable, not a wall. */}
      {specRows.length > 0 ? <SpecificationsSection rows={specRows} /> : null}

      {/* pinout: shown whenever the record carries one (read-only view of the
          persisted specs.pinout, source of truth per M6i). */}
      {pinout.length > 0 ? (
        <>
          <Eyebrow className="mb-2.5 mt-6">Pinout</Eyebrow>
          <div className="max-w-[760px]">
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
      <div className="max-w-[760px]">
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
            className="inline-flex min-w-0 items-start gap-1.5 text-t1 underline decoration-line2 underline-offset-2 hover:decoration-current"
          >
            {/* show the FULL url, wrapped - never truncated (a cut-off link reads as broken) */}
            <span className="min-w-0 break-all">{value}</span>
            <ExternalIcon className="mt-1 flex-none text-t3" />
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
  tool,
  art,
  thumb,
  onOpen,
  onAttach,
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
  // omit it and `art` is shown directly (the 3D card keeps its glyph, viewed on open).
  thumb?: ReactNode;
  // When present and set, the whole card is a button that expands the preview.
  onOpen?: () => void;
  // When the asset is MISSING and set, the whole card is a button that opens the
  // Attach modal (assets are attached after the part lands, so a null asset is not a
  // dead end). Ignored when the asset is present.
  onAttach?: () => void;
  className?: string;
}) {
  const stage = (
    <div
      className={
        "flex flex-1 items-center justify-center " +
        (present
          ? "bg-[rgba(0,0,0,0.18)] min-h-[150px]"
          : "flex-col gap-1.5 bg-[rgba(0,0,0,0.1)] min-h-[150px] text-t3")
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
      {present ? (
        <Badge tone="neutral" size="sm">
          {toolLabel(tool)}
        </Badge>
      ) : null}
      <span className="ml-auto inline-flex items-center gap-1.5 text-2xs text-t3">
        {present ? (
          <>
            <Dot tone="ok" />
            {onOpen ? "View" : "Linked"}
          </>
        ) : onAttach ? (
          <>
            <Dot tone="warn" />
            Attach
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
  // The shared card-as-button chrome (Card is a div, not polymorphic), so the whole
  // tile is one click target for both the preview-expand and the attach affordances.
  const buttonCls =
    "rounded-card border border-line bg-raise " +
    cls +
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
  return <Card className={cls}>{stage}{footer}</Card>;
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
const SPEC_COLLAPSE_AT = 10;

function SpecificationsSection({ rows }: { rows: [string, unknown][] }) {
  const [showAll, setShowAll] = useState(false);
  const collapsible = rows.length > SPEC_COLLAPSE_AT;
  const shown = showAll || !collapsible ? rows : rows.slice(0, SPEC_COLLAPSE_AT);
  return (
    <>
      <Eyebrow className="mb-2.5 mt-6">
        Specifications <span className="text-t3">({rows.length})</span>
      </Eyebrow>
      <div className="grid max-w-[760px] grid-cols-1 gap-x-8 sm:grid-cols-2">
        {shown.map(([key, value]) => (
          <div
            key={key}
            className="flex items-baseline justify-between gap-4 border-b border-line py-1.5"
          >
            <span className="text-sm text-t3">{key}</span>
            <span className="text-right text-sm text-t1">{String(value)}</span>
          </div>
        ))}
      </div>
      {collapsible ? (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="mt-2.5 text-xs font-medium text-t2 transition-colors hover:text-t1"
        >
          {showAll ? "Show Fewer" : `Show All ${rows.length}`}
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
        {purchase.part_number ? (
          <span className="tnum text-xs text-t3">{purchase.part_number}</span>
        ) : null}
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
