/**
 * The part detail view, laid out as a bench workstation rather than a stack of cards.
 *
 * A fixed LEFT rail is the specimen card: the one identity (a derived headline + the MPN
 * serial + manufacturer, all editable in place), the 3D object as the hero with its symbol
 * and footprint as supporting embodiments, and a single readiness read (KiCad / Altium, what
 * each still needs) with the one Complete Part action. The RIGHT workbench is a tabbed panel
 * (Overview / Representations / Sources / Activity) so the reference depth lives in one panel
 * height and never pushes the page into a long scroll. A slim footer carries the filing
 * (category) control and the quiet Delete.
 *
 * Identity is stated exactly once (the old Overview card is gone), assets read as one strip
 * instead of a tall rail, and the spec sheet no longer dominates the page. Everything degrades
 * honestly when a field is absent, and no data is fabricated.
 */
import {
  useCallback,
  useEffect,
  useState,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import type {
  Asset,
  PartDetail,
  PurchaseRef,
  SourcedAlternate,
  SourcedField,
} from "../api/types";
import { deriveTitle, isReferenceOnlySpecKey } from "../lib/derive";
import { useCapture } from "../lib/capture";
import {
  groupSpecs,
  mergeSameConcept,
  TRADE_GROUP,
  type SpecGroup,
  type SpecRow,
} from "../lib/specSchema";
import {
  breakForQuantity,
  extendedPrice,
  ladderRows,
  orderPurchases,
  recommendVendor,
} from "../lib/sourcingOrder";
import { distributorLabel } from "../lib/sourced";
import {
  assetPresent,
  assetReadiness,
  assetRef,
  assetsFor,
  assetTitleLabel,
  neededKinds,
  type AssetReadiness,
} from "../lib/edaTarget";
import { EDA_TOOLS, partClass } from "../lib/edaRegistry.generated";
import { useInlineEdit } from "../lib/useInlineEdit";
import { Text } from "../lib/copy";
import { Icon } from "./Icon";
import { EnrichPanel } from "./EnrichPanel";
import { CompactPinoutCard, parsePinout } from "./PinoutViewer";
import { PartTimeline } from "./PartTimeline";
import { ConfirmDialog } from "./ConfirmDialog";
import { PreviewImage } from "./PreviewImage";
import { HandoffBand } from "./HandoffBand";
import {
  type PinnedSpecs,
  effectiveKeySpecKeys,
  isCuratedOnly,
  isPinned,
  keySpecRows,
  normalizePinnedSpecs,
  togglePinned,
  withoutPromoted,
} from "../lib/keySpecs";
import { readPref, writePref } from "../lib/uiPrefs";
import { PhotoTrigger, partPhotos } from "./ProductPhoto";
import { Glb3DView } from "./Glb3DView";
import {
  useAltiumEmbedCapability,
  useAltiumEmbedModel,
  useCadSourceQuery,
  useDetachAsset,
  useLandPattern,
  usePreviewGlb,
  useRefreshSourcing,
} from "../api/queries";
import { useToast } from "../lib/toast";
import { PreviewModal, type PreviewKind } from "./PreviewModal";
import { CompletePartModal } from "./CompletePartModal";
import { CadVariantSection } from "./CadVariantSection";
import {
  CubeArt,
  ExternalIcon,
  EyeIcon,
  FootprintArt,
  RefreshIcon,
  SymbolArt,
  TrashIcon,
  UploadIcon,
  WarnIcon,
} from "./icons";
import {
  EYEBROW_DENSE,
  IconButton,
  TabStrip,
  tabButtonId,
  tabPanelId,
  type TabItem,
} from "./primitives";

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

function assetLocation(asset: Asset | null | undefined): string {
  const ref = assetRef(asset);
  if (!ref) return "";
  if (ref.file) return ref.file.split(/[\\/]/).pop() ?? ref.file;
  return [ref.lib, ref.name].filter(Boolean).join(":");
}

function sourceLabel(asset: Asset | null | undefined): string {
  const vendor = asset?.origin?.vendor?.trim();
  if (!vendor) return "Unattributed";
  return vendor
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/**
 * One representation inventory across every registered EDA tool.
 *
 * The old Handoff view jumped straight to the fields emitted during placement, which made it
 * impossible to answer the more basic question: "which symbol, footprint and mechanical body are
 * actually accepted for each tool, and what supports them?" This matrix keeps the underlying
 * tool-neutral Asset/Origin/Check contract visible without forcing Altium through KiCad-shaped
 * cards or reducing provenance to a decorative source badge.
 */
function RepresentationMatrix({ detail }: { detail: PartDetail }) {
  const kinds = Array.from(new Set(EDA_TOOLS.flatMap((tool) => tool.assetKinds)));

  return (
    <section
      data-dev-id="detail.representations"
      aria-labelledby="detail-representations-heading"
      className="flex-none overflow-hidden rounded-panel border border-line bg-s1"
    >
      <div className="flex items-baseline gap-2 border-b border-line px-3 py-2">
        <h2 id="detail-representations-heading" className="text-2xs font-semibold text-t1">
          Representations
        </h2>
        <p className="truncate text-2xs text-t3">
          Exact asset, source, and verification by design tool
        </p>
      </div>
      <div className="overflow-auto">
        <div className="grid min-w-[760px] grid-cols-[136px_repeat(3,minmax(0,1fr))] border-b border-line bg-band text-2xs font-semibold text-t3">
          <div className="px-3 py-1.5">Design Tool</div>
          {kinds.map((kind) => (
            <div key={kind} className="border-l border-line px-3 py-1.5">
              {assetTitleLabel(kind)}
            </div>
          ))}
        </div>
        {EDA_TOOLS.map((tool) => {
          const bundle = assetsFor(detail, tool.key);
          const readiness = assetReadiness(detail, tool.key);
          const requiredKinds = new Set(
            neededKinds(detail, tool.key, partClass(detail.part_class)),
          );

          return (
            <div
              key={tool.key}
              className="grid min-w-[760px] grid-cols-[136px_repeat(3,minmax(0,1fr))] border-b border-line last:border-b-0"
            >
              <div className="flex min-h-14 flex-col justify-center px-3 py-2">
                <div className="truncate text-2xs font-semibold text-t1">{tool.label}</div>
                <div className={`text-2xs ${readiness.ready ? "text-ok" : "text-warn"}`}>
                  {readiness.ready ? "Ready" : `${readiness.missing.length} needed`}
                </div>
              </div>
              {kinds.map((kind) => {
                const asset = bundle[kind as keyof typeof bundle];
                const present = assetPresent(asset);
                const unsupported = tool.unsupportedAssets[kind];
                const embedded = tool.embeddedAssets[kind];
                const required = requiredKinds.has(kind);
                const location = assetLocation(asset);
                const checkCount = asset?.checks?.length ?? 0;
                const state = present
                  ? embedded
                    ? "Embedded"
                    : "Present"
                  : !required
                    ? "Tool Default"
                    : embedded
                      ? "Needs Embed"
                      : unsupported
                        ? "Not Applicable"
                        : "Missing";
                const stateTone = present
                  ? "text-ok"
                  : !required || (unsupported && !embedded)
                    ? "text-t3"
                    : "text-warn";
                const secondary = present
                  ? `${sourceLabel(asset)} · ${checkCount ? `${checkCount} checks` : "Unchecked"}`
                  : !required
                    ? "No dedicated asset required"
                    : embedded
                      ? "Stored inside the footprint"
                      : unsupported
                        ? "This tool cannot reference it"
                        : "No accepted artifact";

                return (
                  <div
                    key={kind}
                    className="flex min-h-14 min-w-0 flex-col justify-center border-l border-line px-3 py-2"
                    title={!present && embedded ? embedded.reason : unsupported}
                  >
                    <div className={`text-2xs font-semibold ${stateTone}`}>{state}</div>
                    <div className="truncate text-2xs text-t1" title={location || undefined}>
                      {location || "—"}
                    </div>
                    <div className="truncate text-2xs text-t2" title={secondary}>
                      {secondary}
                    </div>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </section>
  );
}

type WorkbenchTab = "specs" | "sourcing" | "enrich" | "history" | "handoff";

const PINNED_SPECS_KEY = "stockroom.pinned-specs";

/** The pinned-spec map, host-injected first then the localStorage mirror (see uiPrefs.ts). Unlike the
 *  scalar prefs this one is JSON, so a malformed mirror must degrade to "nothing pinned" rather than
 *  throwing during the first render of the sheet. */
function readPinnedSpecs(): PinnedSpecs {
  return normalizePinnedSpecs(
    readPref<PinnedSpecs>(
      "pinned_specs",
      PINNED_SPECS_KEY,
      (raw) => {
        try {
          const parsed = JSON.parse(raw);
          return parsed && typeof parsed === "object" && !Array.isArray(parsed)
            ? (parsed as PinnedSpecs)
            : undefined;
        } catch {
          return undefined;
        }
      },
      {},
    ),
  );
}

/**
 * KEY SPECIFICATIONS - the block that replaced the EDA handoff at the head of the Specifications
 * column. Same 22px row rhythm and the same label/value/unit split as the Specifications list below
 * it, because the owner asked for it "formatted like the specifications": two lists on one sheet
 * that measure the same thing must not read as two different widget species.
 */
/**
 * The part's description at the head of the Specifications column (owner, 2026-07-26).
 *
 * Renders NOTHING when there is no description: an emphasized empty lede would be the loudest
 * element on the sheet saying nothing, which is exactly the empty-state fault the punch list
 * already carries for other blocks.
 */
function DescriptionLede({
  text,
  alternates,
  onUse,
}: {
  text?: string;
  alternates: SourcedAlternate[];
  onUse?: (value: string) => void;
}) {
  const body = (text ?? "").trim();
  if (!body) return null;
  return (
    <section data-dev-id="detail.description-lede" className="mb-2.5 flex flex-col gap-1">
      <p className="text-xs leading-snug text-t1">{body}</p>
      {/* the disagreement follows the value it is about, the same rule the Handoff tab uses */}
      <AlternatesDisclosure entries={alternates} current={body} onUse={onUse} />
    </section>
  );
}

function KeySpecificationsBlock({
  groups,
  category,
  pinned,
  onTogglePin,
}: {
  groups: SpecGroup[];
  category: string;
  pinned: PinnedSpecs;
  onTogglePin: (category: string, specKey: string) => void;
}) {
  const rows = keySpecRows(groups, category, pinned);
  // What is EFFECTIVELY up here, so a row's star tells the truth in both this block and the list
  // below. Derived from the same call that produced `rows`, never recomputed, or the two could
  // disagree the moment either rule changed.
  const effective = effectiveKeySpecKeys(groups, category, pinned);
  // Nothing to lead with: render NOTHING rather than an empty card. A titled card with no rows in the
  // sheet's most prominent slot reads as a failure, which is exactly what the old empty-state faults
  // in the punch list were about.
  if (rows.length === 0) return null;
  return (
    // DISTINCT from the Specifications list below, and it has to be: since the owner reversed to
    // "copy the specifications", the same row appears in both places, and two identically-styled
    // lists showing one fact read as a bug rather than as a summary. So this is a CARD OF CELLS -
    // label above value, two across, on a tinted surface - against a plain label-left/value-right
    // list. It is deliberately the cell treatment the owner already accepted in this very slot when
    // the EDA handoff band lived here, so it is new to the reader without being unfamiliar.
    // (dev-id stays `detail.key-specs`: it is an internal handle, and renaming it churns the
    // catalogue's count gate for no reader-visible gain.)
    <section
      data-dev-id="detail.key-specs"
      aria-label="Key Specifications"
      className="@container mb-3 flex flex-none flex-col rounded-card border border-line bg-surface"
    >
      <header className="flex h-6 items-center gap-2.5 border-b border-line px-3">
        <span className="text-xs font-semibold text-t1">
          <Text id="detail.top-specifications">Key Specifications</Text>
        </span>
        <span className="truncate text-2xs text-t3">Recommended and pinned</span>
        {/* A PIN, marking what this block IS: the rows pinned up out of the list below. Owner,
            2026-07-26, replacing the "What This Part Is" caption that used to sit here - the caption
            explained the block in words, the pin says the same thing in the same glyph the row
            control uses, and it does not compete with the section title for the eye.
            NOT a button: pinning happens on the rows themselves, and a control here would imply an
            action this header does not have. */}
        <span
          className="ml-auto flex-none text-t3"
          title="Pinned and recommended specifications"
          aria-hidden="true"
        >
          <svg viewBox="0 0 16 16" className="h-[12px] w-[12px]" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
            {/* a drawing pin seen side-on: head, shaft, point */}
            <path d="M6 1.8h4l-.6 3.4 2.1 2.1v1.2H4.5V7.3l2.1-2.1z" />
            <path d="M8 8.5v5.7" />
          </svg>
        </span>
      </header>
      {/* gap-px on a line-coloured background draws the cell grid with no per-cell borders */}
      <div className="grid grid-cols-1 gap-px bg-line @sm:grid-cols-2">
        {rows.map((row) => (
          <div key={row.key} className="group relative flex flex-col gap-0.5 bg-surface px-3 py-2">
            <span className={EYEBROW_DENSE + " truncate"} title={row.label}>
              {row.label}
            </span>
            <span className="tnum break-words font-mono text-sm font-medium leading-tight text-t1">
              <SpecValue value={row.unit ? `${row.value} ${row.unit}` : row.value} />
            </span>
            {/* corner-anchored so it never displaces the value it belongs to */}
            {/* Only a row the USER pinned carries a star up here, and it is the control that takes
                it back down. A curated row gets NONE: every row in this block is by definition in
                this block, so a star on each says nothing the header's pin has not already said,
                and five identical filled stars that cannot be pressed are noise that looks like
                five controls. The star that carries information is the one in the list BELOW,
                where it distinguishes a row already up here from one that is not. */}
            <span className="absolute right-1.5 top-1.5">
              {isCuratedOnly(effective, pinned, category, row.key) ? null : (
                <PinStar
                  pinned={isPinned(pinned, category, row.id ?? row.key)}
                  onToggle={() => onTogglePin(category, row.id ?? row.key)}
                  label={row.label}
                />
              )}
            </span>
          </div>
        ))}
        {/* AN ODD NUMBER OF CELLS LEAVES A PAINTED HOLE. The grid draws its own rules by sitting on
            `bg-line` and letting a 1px gap show through between `bg-surface` cells - which means any
            grid AREA with no cell in it shows that line colour at FULL SIZE, not as a line. With
            five curated specs the second column of the last row was a solid block of border colour,
            reading as a broken or still-loading tile in both themes. This fills it with the surface
            the cells use, and exists ONLY at the two-column breakpoint, because at one column every
            row is full and a filler would add an empty cell of its own. */}
        {rows.length % 2 === 1 ? (
          <div aria-hidden="true" className="hidden bg-surface @sm:block" />
        ) : null}
      </div>
    </section>
  );
}

/** Width of a collapsed pane's rail. Wide enough for a control plus its focus ring. */
const PANE_RAIL_PX = 44;

/**
 * The grid track template for the three-column sheet, given which panes are open.
 *
 * Returned as a STRING fed to a CSS custom property, and NEVER interpolated into a Tailwind class.
 * `grid-cols-[...]` built from a template literal produces a class attribute with no CSS behind it,
 * because utilities are generated by scanning source TEXT - a trap this very grid has already paid
 * for once, when the track definition vanished, the grid collapsed to one cell per line, and a
 * `className`-contains test stayed GREEN through the whole thing. `grid-cols-[var(--sr-panes)]` is
 * a static, scannable class; only the VALUE moves.
 *
 * When all three panes are open they receive equal tracks; matching 20px cell padding then produces
 * equal content widths instead of three almost-but-not-quite widths. "The open ones maximized"
 * (owner, 2026-07-26) decides who takes space released by a collapsed work pane. When both are
 * collapsed the specimen rail grows beside the two 44px rails.
 */
export function panesTemplate(specsOpen: boolean, sourcingOpen: boolean): string {
  const rail = `${PANE_RAIL_PX}px`;
  if (specsOpen && sourcingOpen) {
    return "minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)";
  }
  if (specsOpen) return `320px minmax(16rem,1fr) ${rail}`;
  if (sourcingOpen) return `320px ${rail} minmax(16rem,1fr)`;
  return `minmax(320px,1fr) ${rail} ${rail}`;
}

/**
 * A collapsed pane: a thin vertical rail carrying the pane's own name and the control that reopens
 * it. The name is KEPT, rotated, rather than reduced to a bare chevron - this sheet can hide two
 * panes at once, and a lone glyph does not say which one is behind it.
 */
function CollapsedPaneRail({
  devId,
  label,
  onExpand,
}: {
  devId: string;
  label: string;
  onExpand: () => void;
}) {
  return (
    <div className="flex min-h-0 flex-col border-l border-line py-3">
      <button
        type="button"
        data-dev-id={devId}
        onClick={onExpand}
        aria-expanded="false"
        title={`Expand ${label}`}
        // the whole rail is the hit target, not just the glyph: 44px is already narrow, and a 16px
        // target inside it is the kind of control people miss twice before they find it.
        className="flex w-full flex-1 flex-col items-center gap-3 rounded-control py-2 text-t3 transition-colors hover:bg-[var(--c-hover)] hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
      >
        <Icon id="detail.chevron-right" className="size-3.5 flex-none rotate-180" />
        <span
          className={EYEBROW_DENSE + " flex-none whitespace-nowrap"}
          // bottom-to-top, the way every docked side rail reads
          style={{ writingMode: "vertical-rl", transform: "rotate(180deg)" }}
        >
          {label}
        </span>
      </button>
    </div>
  );
}

/** The control that collapses an open pane, sitting in that pane's own section header. */
function CollapsePaneButton({ devId, label, onCollapse }: { devId: string; label: string; onCollapse: () => void }) {
  return (
    <button
      type="button"
      data-dev-id={devId}
      onClick={onCollapse}
      aria-expanded="true"
      title={`Collapse ${label}`}
      className="inline-flex h-6 w-6 items-center justify-center rounded-control text-t3 transition-colors hover:bg-raise2 hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
    >
      <Icon id="detail.chevron-right" className="size-3.5" />
    </button>
  );
}

/**
 * The star that pins a spec into Key Specifications.
 *
 * Visible at rest ONLY when it is pinned; otherwise it appears on hover or keyboard focus. A star on
 * every row at full strength would put ~30 identical controls down the sheet and compete with the
 * values, and this is a rarely-used affordance - but it must still be REACHABLE without a pointer,
 * which `focus-visible` is what buys.
 */
function PinStar({
  pinned,
  locked,
  onToggle,
  label,
}: {
  pinned: boolean;
  // Already in Top Specifications because the REGISTRY curated it, not because this user pinned it
  // (owner, 2026-07-26). It reads as pinned - which it is - and does not offer to pin it again:
  // that would add a redundant user pin, change nothing visible, and spend one of the capped slots
  // on a row that already had one.
  locked?: boolean;
  onToggle: () => void;
  label: string;
}) {
  const on = pinned || Boolean(locked);
  return (
    <button
      type="button"
      data-dev-id="detail.spec-pin"
      onClick={locked ? undefined : onToggle}
      disabled={locked}
      aria-pressed={on}
      aria-label={
        locked ? `${label} is already in Key Specifications` : on ? `Unpin ${label}` : `Pin ${label}`
      }
      title={
        locked
          ? "Already In Key Specifications"
          : on
            ? "Unpin From Key Specifications"
            : "Pin To Key Specifications"
      }
      className={
        "flex h-[16px] w-[16px] flex-none items-center justify-center rounded-control transition " +
        "focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 " +
        "focus-visible:outline-acc " +
        (on
          ? "text-warn opacity-100" + (locked ? " cursor-default" : "")
          : "text-t3 opacity-0 hover:text-t1 group-hover:opacity-100 focus-visible:opacity-100")
      }
    >
      <svg viewBox="0 0 16 16" aria-hidden className="h-[11px] w-[11px]">
        <path
          d="M8 1.8l1.9 3.9 4.3.6-3.1 3 .7 4.3L8 11.6l-3.8 2 .7-4.3-3.1-3 4.3-.6z"
          fill={pinned ? "currentColor" : "none"}
          stroke="currentColor"
          strokeWidth="1.3"
        />
      </svg>
    </button>
  );
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
  // moves through onMoveCategory, offered as the filing select in the footer.
  onMoveCategory?: (category: string) => void;
  categories?: string[];
  // Deleting confirms in-window, then routes here.
  onDelete?: () => void;
  // Applying an enriched pinout persists through the specs seam (not editField);
  // omit it and the enrich panel offers no pinout Apply.
  onApplyPinout?: (sourced: SourcedField) => void;
  // TRUE only while the delete itself is in flight. Distinct from `busy`, which is the panel's
  // aggregate write flag: spinning the delete control because metadata is saving would claim an
  // action the user never started.
  deleting?: boolean;
  // Putting a DIFFERENT source's answer in force for a spec. It routes through the specs seam
  // (which carries provenance per key), not onEditField, because a spec is not a record field
  // and the swap must record WHICH distributor the new value came from.
  onUseSpecValue?: (key: string, value: string, source: string) => void;
  busy?: boolean;
}

export function DetailPanel({
  detail,
  isLoading,
  error,
  missing,
  onEditField,
  onMoveCategory,
  categories,
  onDelete,
  onApplyPinout,
  onUseSpecValue,
  deleting = false,
  busy = false,
}: Props) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  // Which preview is expanded in the in-window modal (null = closed). The modal has
  // tabs, so this is only the tab it opens on.
  const [preview, setPreview] = useState<PreviewKind | null>(null);
  // The one Complete-Part window (adds every missing file + data field in one place) - open flag.
  const [completeOpen, setCompleteOpen] = useState(false);
  // Finish the background-pill reopen handoff: when the pill asked to reopen THIS part (the page
  // already selected it), open the Complete-Part window and clear the intent.
  const { reopenPartId, clearReopen } = useCapture();
  useEffect(() => {
    if (reopenPartId && detail?.id === reopenPartId) {
      setCompleteOpen(true);
      clearReopen();
    }
  }, [reopenPartId, detail?.id, clearReopen]);
  // Which workbench tab is showing. It resets to Specs whenever the active id falls out
  // of the available set (a part switch that drops the Pinout / Enrich tab).
  const [tab, setTab] = useState<WorkbenchTab>("specs");
  // Pinned specs, per category, persisted through the machine config like the theme and the rail:
  // localStorage alone resets on every launch because the host binds an ephemeral port (uiPrefs.ts).
  const [pinnedSpecs, setPinnedSpecs] = useState<PinnedSpecs>(readPinnedSpecs);
  const togglePin = useCallback((category: string, specKey: string) => {
    setPinnedSpecs((current) => {
      const next = togglePinned(current, category, specKey);
      writePref("pinned_specs", next, PINNED_SPECS_KEY);
      return next;
    });
  }, []);
  // A passive inherits the 3D body BUILT INTO the KiCad STOCK footprint it references (the
  // model.glb endpoint resolves it from the footprint), so "has a 3D model" for a passive is "has
  // a footprint", not "has an owned model.file" - which the passive add correctly leaves null.
  // Without this a passive read "Not Linked" though its 3D rendered during add (A8).
  //
  // FIXED 2026-07-27 (cold-eyes finding 3): this used to read "any class that does not need its
  // OWN model", generalising from `neededKinds` on the theory that avoiding `part_class ===
  // "passive"` avoids the sibling class-blind bug. It does not - it is a DIFFERENT fact. Every
  // class in `CLASS_NEEDS` whose `assets` excludes "model" (passive, mechanical, virtual) took
  // this branch, but only PASSIVE's KiCad reference is guaranteed to be a stock KiCad part
  // shipping a baked-in 3D body; a mechanical part's footprint is Stockroom-authored and has no
  // such guarantee. So a mechanical part with a footprint and NO 3D file read "has a 3D model"
  // regardless. "Doesn't need to own a model" and "its footprint carries one built in" are
  // genuinely different claims, and only the second is true of passives specifically.
  const kicadAssets = detail ? assetsFor(detail, "kicad") : null;
  const usesStockKicadModel = detail?.part_class === "passive";
  const hasModel = usesStockKicadModel
    ? assetPresent(kicadAssets?.footprint)
    : !!assetRef(kicadAssets?.model)?.file;
  // EVERY product photo on record, not just the one that won the specs slot (owner 2026-07-25).
  // Both distributor adapters write specs["Image"] with setdefault, so a second vendor's genuinely
  // different photograph was preserved in `alternates["Image"]` and shown to nobody. Still hidden
  // until clicked - it is the trigger that got bigger, not the default state.
  const partPhotoSet = partPhotos(detail?.derived.specs, detail?.alternates);
  // Inline 3D render (C1/C2): fetch + render the GLB right in the hero, auto-rotating and
  // pointer-events-none so it never fights the tile's own click. Enabled only for a part that
  // actually has a model, so a model-less part pays nothing.
  const modelGlb = usePreviewGlb(detail?.id ?? "", hasModel);
  const landPattern = useLandPattern(detail?.id ?? "", hasModel);
  // Warm the cad-source (DigiKey URL) cache so the Complete Part window opens instantly; its
  // result is NOT used for readiness anymore. Readiness (incl. Altium) reads the part RECORD via
  // assetReadiness, so it refreshes on the clean ["part", id] invalidation after an attach - the
  // old cad-source-derived Altium needs went stale and left a captured part stuck on "CAD
  // Incomplete" (live 2026-07-24). Prefetch only; a failure never affects the readiness display.
  useCadSourceQuery(detail?.id ?? null, true);
  // The per-part sourcing refresh (POST .../refresh): a write-lane job re-pulling
  // price/stock/lifecycle from the distributor APIs. Its outcome reports through the
  // quiet toasts like every other background mutation.
  const refreshJob = useRefreshSourcing(detail?.id ?? "");
  // Whether a 3D body can be written into the Altium footprint HERE. Altium itself does that write
  // (a 3D body lives inside the .PcbLib binary), so the action needs Altium installed and its
  // license seat free, and the registry supplies the sentence explaining it. Declared with the
  // other hooks, above every early return.
  const embedCapability = useAltiumEmbedCapability();
  const embedModel = useAltiumEmbedModel();
  const { toast } = useToast();
  // Per-element removal (owner 2026-07-24): a wrongly-captured element deletes on its
  // own, confirmed in-window, leaving the rest of the part standing.
  const detach = useDetachAsset();
  const [pendingDetach, setPendingDetach] = useState<{ kind: string; label: string } | null>(null);
  // Which side panes are OPEN. Owner, 2026-07-26: "sourcing and specs panes open/closable ... and
  // the open ones maximized". Deliberately NOT persisted yet - the rail's collapsed state lives in
  // MachineConfig.ui and this could join it, but that is backend work and a separate slice.
  //
  // DECLARED HERE, ABOVE the loading / error / no-selection early returns below. React counts hooks
  // per render, so a `useState` placed after an early return changes the COUNT depending on which
  // branch ran - "Rendered more hooks than during the previous render", and the whole panel dies.
  // This exact trap already cost this file 11 test failures once (a `useMemo` for the promoted-spec
  // set, placed below these same returns), and it caught this slice too.
  const [specsOpen, setSpecsOpen] = useState(true);
  const [sourcingOpen, setSourcingOpen] = useState(true);
  const refreshStatus = refreshJob.status;
  const refreshError = refreshJob.error;
  useEffect(() => {
    if (refreshStatus === "done") toast("Sourcing refreshed.", "ok");
    else if (refreshStatus === "error")
      toast(refreshError || "Could not refresh sourcing.", "err");
  }, [refreshStatus, refreshError, toast]);
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

  // Per-tool readiness read straight off the part RECORD (KiCad from symbol/footprint/model,
  // Altium from altium_symbol/altium_footprint) - so an attach refreshes it on the ["part", id]
  // invalidation. Declared before the needs derivation below, which reads altium.missing.
  const kicad = assetReadiness(detail, "kicad");
  const altium = assetReadiness(detail, "altium");

  // The Altium 3D embed affordance. Every precondition is a real one, and each has its own
  // message: a 3D body is written INTO the footprint's .PcbLib, so there must be a footprint to
  // write into and a model file to write. Offered only when the registry says the kind is
  // embeddable at all, so a tool that gains an embed route needs no edit here.
  const altiumFootprint = assetRef(assetsFor(detail, "altium").footprint);
  // Embedding is offered only when the registry says the kind is embeddable AND the part's own
  // class actually needs a 3D model. Offering it to a fiducial would name a gap it cannot have.
  const altiumNeedsModel = neededKinds(detail, "altium", partClass(detail.part_class)).includes(
    "model",
  );
  const embed3d: Embed3dState | null =
    "model" in altium.embedded && altiumNeedsModel
      ? {
          done: !!altium.present.model,
          // The blocker to state, in the order the user would fix them. Null means ready to run.
          blocked: !altiumFootprint?.lib
            ? "Attach the Altium library first: a 3D body is stored inside the footprint's .PcbLib."
            : !hasModel
              ? "Add a 3D model file first. The same file serves every tool."
              : !embedCapability.data
                ? ""
                : !embedCapability.data.installed
                  ? embedCapability.data.reason
                  : embedCapability.data.busy
                    ? `Close Altium first: ${embedCapability.data.busy} is holding the license seat.`
                    : null,
          pending: embedModel.isPending,
          onEmbed: () => embedModel.mutate({ id: detail.id }),
        }
      : null;

  // What the part still needs, files + data, for the one Complete-Part window and its trigger.
  //
  // FIXED 2026-07-27 (cold-eyes finding 3): this used to be a hardcoded symbol/footprint/3-model
  // list, evaluated regardless of what the part's CLASS actually needs - the exact "CAD Incomplete
  // forever" shape `edaTarget.ts` exists to prevent, recreated one layer up. A mechanical part was
  // told to add a symbol it can never have; a fiducial was told to add all three while the CAD
  // chip simultaneously read Complete. Derived from `kicad.missing` instead, which is already
  // class-aware (assetReadiness intersects the class's needed kinds with what KiCad can hold).
  const kicadMissing = new Set(kicad.missing);
  const missingAssets = [
    kicadMissing.has("Symbol") ? "symbol" : null,
    kicadMissing.has("Footprint") ? "footprint" : null,
    kicadMissing.has("3D Model") ? "3D model" : null,
  ].filter((x): x is string => x !== null);
  // Altium gaps read straight off the part RECORD (altium.missing from assetReadiness), so an
  // attach updates them on the ["part", id] refresh - never a stale cad-source needs list.
  const altiumNeeds = altium.missing
    .filter((m) => m === "Symbol" || m === "Footprint")
    .map((m) => `Altium ${m}`);
  const needsList = [...missing, ...missingAssets, ...altiumNeeds];
  // A writable metadata seam makes Complete Part available. CAD never has a reference-entry
  // callback here: symbols, footprints, and models arrive through the network collection flow.
  const canComplete = !!onEditField;

  const derived = deriveTitle(detail);
  const name = detail.derived.display_name.trim();
  // The headline is the best HUMAN name: a passive gets its derived spec title
  // ("0.1 µF X7R Capacitor"); an opaque part whose title fell back to the MPN shows its
  // display name instead when that carries something the MPN does not, so the MPN never
  // headlines AND reads again on the serial line below.
  const titleIsMpn = derived === detail.mpn.trim();
  const headline = titleIsMpn && name && name !== detail.mpn.trim() ? name : derived;
  // Grouped, extensible spec sheet (Electrical / Physical / Ratings / Other) from lib/specSchema,
  // with catalog metadata (manufacturer, country, packaging, ...) dropped so the sheet is the
  // physical parameters, not a distributor page. Groups emptied by the filter fall away.
  // ONE CONCEPT, ONE ROW. Distributors word a parameter differently and the record keeps every
  // wording, so this part carries both `Breakdown Voltage` (6 V) and `Voltage - Breakdown` (8.5 V)
  // - two rows whose labels both prettify to "Breakdown Voltage", showing two numbers with nothing
  // saying which was in force. The fold routes the displaced value into `alternates`, so the
  // existing "N Sources" disclosure shows and swaps it like any other vendor disagreement.
  const mergedSpecs = mergeSameConcept(
    groupSpecs(detail.derived.category, detail.derived.specs),
    detail.alternates ?? {},
  );
  const allSpecGroups = mergedSpecs.groups;
  const specAlternates = mergedSpecs.alternates;
  const specGroups = allSpecGroups
    .filter((group) => group.title !== TRADE_GROUP)
    .map((group) => ({
      ...group,
      rows: group.rows.filter((row) => !isReferenceOnlySpecKey(row.key)),
    }))
    .filter((group) => group.rows.length > 0);
  const promotedSpecKeys = effectiveKeySpecKeys(
    specGroups,
    detail.derived.category,
    pinnedSpecs,
  );
  const remainingSpecGroups = withoutPromoted(specGroups, promotedSpecKeys);
  // The procurement facts (origin, the page's own tariff rate, export classification, order
  // quantities) go to SOURCING, not here. They are real vendor data the owner asked to stop
  // losing, but they are not physical parameters - and this is the one place the reference-only
  // filter must NOT run, because reference data is exactly what the block is for.
  const tradeGroup = allSpecGroups.find((group) => group.title === TRADE_GROUP) ?? null;
  // The persisted pinout (M6i) reads from the record's specs, its provenance from
  // the enrichment map. Shown when present, in both read-only and editable modes.
  const pinout = parsePinout(detail.derived.specs);
  const pinoutProvenance = detail.enrichment?.pinout;

  // Pinout belongs beside the component's CAD representations in the specimen rail, where it
  // remains visible without adding another top-level destination. Sources is present only in
  // editable mode with an MPN to look up by; Activity is always available. The active tab falls
  // back to Overview when the current id is not in the set (a part switch).
  const hasEnrich = !!onEditField && !!detail.mpn;
  const tabs: TabItem<WorkbenchTab>[] = [
    { id: "specs", label: "Overview" },
    // Its own tab (owner's choice from previews, 2026-07-26), rather than a band at the head of the
    // Specifications column. That slot now carries Key Specifications, which is what a person opens
    // a part to read; the handoff is what a person needs once they are about to PLACE it.
    { id: "handoff", label: "Representations" },
    ...(hasEnrich ? [{ id: "enrich" as const, label: "Sources" }] : []),
    { id: "history", label: "Activity" },
  ];
  const activeTab = tabs.some((t) => t.id === tab) ? tab : "specs";

  return (
    <div data-dev-id="detail.root" className="flex h-full min-h-0 flex-col">
      {/* the opened component reads as a docked Altium panel: a title-strip band (the part name +
          its category), the SAME band + hairline as the Components list header and the rail header,
          so the three panes read as one workspace. Then the padded body. */}
      <div
        data-dev-id="detail.title-strip"
        // h-[34px], the SAME as PanelTitle and the rail header. It was 38 while
        // the comment above claimed it matched them, and on the owner's real Windows window that 4px
        // put this header's ink centre at 17.8 against 16.2 for "Components" and the rail toggle -
        // three docked panel headers on one band, one of them sitting low. Measured, not guessed.
        // The literal stays a literal: a Tailwind arbitrary value built from a template literal
        // generates NO CSS, so a shared constant here would silently remove the height entirely.
        className="flex h-[34px] flex-none items-center gap-4 border-b border-line bg-band px-6"
      >
        <TitleBlock
          headline={headline}
          name={detail.derived.display_name}
          onRename={onEditField ? (v) => onEditField("display_name", v) : undefined}
          busy={busy}
        />
        {/* The view tabs share this band rather than owning a second one below it.
            The category eyebrow that used to sit here is gone: it is an EDA handoff field with a
            single home in the block above Specifications, where it is also editable. The punch
            list had separately called it an orphan, sitting ~700px from the title it qualified. */}
        <div data-dev-id="detail.identity" className="ml-auto flex-none">
          <TabStrip
            tabs={tabs}
            active={activeTab}
            onSelect={setTab}
            idBase="workbench"
            devIdBase="detail"
            density="compact"
            aria-label="Part views"
          />
        </div>
      </div>
      {/* @container: the query root every `@`-prefixed breakpoint inside this sheet resolves
          against. It must sit here, on the pane, so the sheet reacts to the room it actually has
          (the rail collapsing 190px -> 52px changes it by 138px at an unchanged window size). */}
      <div className="@container flex min-h-0 flex-1 flex-col px-5 pb-3 pt-3">

        {/* The default view is a three-pane sheet, bordered like docked panels: the PART (its
            embodiments + CAD readiness), the SPECIFICATIONS (one clean column), and the COMMERCIAL
            + reference pane. Sized to fit the window with no scrolling. */}
        <WorkbenchPanel
          id="specs"
          active={activeTab}
          // grid-rows-[minmax(0,1fr)]: without it the single implicit row sizes to its tallest
          // column, so a long specs list grew the whole sheet instead of scrolling inside its
          // own pane. Pinning the row to the container height lets each column's own
          // overflow-y-auto engage.
          // RESPONSIVE ON THE CONTAINER, never the viewport. The three-column form divides the
          // available sheet into equal tracks; at narrower widths the 320px specimen minimum and
          // 256px work-pane minimum determine when it must stack. What it actually gets is the
          // PANE's width, not the window's.
          //
          // This was a VIEWPORT media query (`lg:`/`xl:`) and it was wrong by construction.
          // MEASURED in the real WebView2 window at the host's own default 1400x900 (2026-07-25):
          // rail 190 + picker 320 + padding 48 left the sheet 825px while `xl:` (1280px viewport)
          // had already switched three tracks on, so the middle track pinned at its 256px minimum
          // and Specifications rendered 205px wide by 5885px tall - one word per line. Even at
          // exactly 1280px viewport the sheet only gets ~722px, so the threshold could never be
          // right: it was short by 142px at its own breakpoint.
          //
          // The decisive proof: COLLAPSING THE RAIL fixed it at an UNCHANGED viewport
          // (grid 825 -> 963, specs 205 -> 304 wide, 5885 -> 1916 tall). The rail is collapsible,
          // so no media query can ever know how much room this sheet has. A container query
          // measures the box the columns must fit inside, which is the only honest question.
          //
          // The layout STACKS rather than overlapping. DOM order never changes; only the track
          // count does, and grid auto-placement flows the third column onto a second row:
          //   container >=896px (@4xl)  three columns, as designed
          //   container >=576px (@xl)   two columns; Sourcing drops beneath Specifications
          //   below                     one column; the specimen rail sits on top
          // Each column keeps its own scroller, and `grid-rows` is only pinned in the 3-column
          // case - once columns wrap, the rows must size to content or a stacked column is
          // unreachable.
          // STACKED vs THREE-COLUMN also changes WHERE the scrolling happens, and getting that
          // wrong is what sliced the asset tiles in half: with the row track left implicit, the
          // grid's default stretch split the height into two EQUAL 328px rows, so the specimen
          // column was cut mid-tile and every block grew its own scrollbar. Stacked, the rows size
          // to their content (`content-start`) and the SHEET is the single scroller; at three
          // columns the row is pinned to the pane height again so each column scrolls in place.
          className={
            "mt-2.5 grid min-h-0 flex-1 gap-y-4 " +
            "content-start overflow-y-auto " +
            "grid-cols-1 " +
            "@xl:grid-cols-[320px_minmax(16rem,1fr)] " +
            "@4xl:grid-cols-[var(--sr-panes)] @4xl:grid-rows-[minmax(0,1fr)] " +
            "@4xl:content-normal @4xl:overflow-hidden"
          }
          // the VALUE moves, the class does not - see panesTemplate for why that matters
          style={{ "--sr-panes": panesTemplate(specsOpen, sourcingOpen) } as React.CSSProperties}
        >
          {/* COLUMN 1 - the specimen rail. Stacked (two columns), it SPANS BOTH ROWS: the right
              track carries Specifications above Sourcing, and without the span this column would be
              trapped in a half-height first row - measured, that clipped the symbol and footprint
              tiles to 17 visible pixels and left ~288x330px of dead space beneath them. At three
              columns there is only one row, so the span is released. */}
          <div className="flex min-h-0 flex-col gap-2.5 overflow-y-auto px-4 @xl:row-span-2 @4xl:row-span-1">
          {/* the physical object as the hero, its symbol + footprint as supporting embodiments.
              flex-1 (no min-h-0): the canvas absorbs the pane's slack so the hero grows to fill
              the column beside a tall specs pane, and still scrolls when content genuinely
              overflows (min-height:auto keeps it from compressing below its content). */}
          <div data-dev-id="detail.canvas" className="flex flex-none flex-col gap-2.5">
            <AssetTile
              devId="detail.asset-hero"
              stageDevId="detail.asset-stage"
              name="3D Model"
              present={hasModel}
              // The hero EARNS its size by having something to show. `min-h-[300px] flex-1` was
              // unconditional, so an absent model still claimed a 300px floor AND all the column's
              // slack: measured, a featureless "No 3D Model" placeholder rendered ~420px tall above
              // 142px Symbol and Footprint tiles, making the emptiest thing on the sheet the most
              // prominent. Empty, it now sits as a PEER of its siblings at the same 142px.
              //
              // Present, it keeps the full hero treatment because then the space is carrying a
              // render.
              //
              // TRIED AND REVERTED 2026-07-25, deliberately, so it is not re-attempted blind:
              // `aspect-[3/2] min-h-[180px]`. The reasoning was sound - `flex-1` gives the hero
              // whatever slack the column has, so beside a tall specs pane it measured a 530x965
              // PORTRAIT stage for a subject that is landscape, and a portrait stage makes the
              // camera fit width-limited so the spare height can never be filled without running
              // the pads off the sides. But shipping it ALONE made two things worse, both seen in
              // the shot: the layer and shading chips are absolutely positioned bottom-left and
              // landed ON the model once the stage was short, and roughly 300px of dead column
              // opened below the Footprint tile because nothing else absorbs the slack. The tile's
              // proportion is therefore part of the COLUMN BALANCE slice (the owner's "sourcing is
              // squished, specifications is too large" and "do not look cramped"), not a change
              // that can be made on its own. See the Batch Plan.
              // A FIXED 300px, not `flex-1` (owner's choice, 2026-07-25). With flex-1 the stage
              // stretched to whatever height the Specifications column happened to need - measured
              // 266x618, aspect 0.43, a portrait stage for a part that is inherently landscape,
              // which is the "grotesquely out of proportion" complaint. Pinning the height keeps
              // the 3D tile clearly dominant over its 142px siblings without letting a long spec
              // sheet stretch it. The column ends above the pane bottom as a result; that dead
              // space is the accepted trade, chosen over a portrait stage.
              // GROWS with the column, but BOUNDED (owner, 2026-07-25). Unbounded `flex-1` is what
              // produced the 266x618 portrait stage: it took every pixel a long spec sheet gave the
              // column. A flex SHARE with a max-height lets the tiles fill the space when there is
              // some, while the ceiling stops the stage ever going portrait again. The hero keeps
              // twice the share of the pair below it, so it stays clearly dominant at any height.
              // GROWN, but not stretchy. A flex share with a max-height did grow the tiles, and
              // left 132px of slack INSIDE the column - a hole between the footprint tiles and the
              // CAD row, which reads worse than the same space falling below the column's end.
              // Fixed heights take the growth (stage 268 -> ~250 tall at 266 wide, aspect ~1.06
              // instead of the original 0.43) and let the leftover land at the bottom, where an
              // ended column simply looks ended.
              className={hasModel ? "h-[340px]" : "h-[142px]"}
              art={<CubeArt />}
              thumb={
                hasModel ? (
                  <div className="pointer-events-none h-full w-full">
                    <Glb3DView
                      data={modelGlb.data}
                      isLoading={modelGlb.isLoading}
                      isError={modelGlb.isError}
                      error={modelGlb.error}
                      land={landPattern.data ?? null}
                      // THE MINI TILE GETS EVERYTHING (owner 2026-07-26: "the mini 3d window should
                      // also be interactable with with all the same settings"). These two default to
                      // false and only the modal passed them, so the tile had the layer chips and
                      // nothing else - no views, no shading, no spin control.
                      showViews
                      showShading
                      // ICON chips here: this tile is ~280px, where ten text-labelled controls wrapped
                      // to three rows and took a third of the stage. The modal keeps its labels.
                      compact
                    />
                  </div>
                ) : undefined
              }
              onOpen={hasModel ? () => setPreview("model") : undefined}
            />
            {/* Content-sized, NOT `h-[200px]`. That literal sat here holding two `h-[142px]` tiles,
                so it guaranteed 58px of empty row under the cards on every part, forever - and with
                the column's former `gap-4` on top of it that is the 74px void the owner reported as
                "odd spacing underneath the model symbol and footprint before the cad complete
                button" (measured 75px on their window, 89px ink-to-ink here including the CAD row's
                own padding). Two hardcoded heights that disagreed by 58px, in the same element. */}
            <div className="grid grid-cols-2 gap-2.5">
              <AssetTile
                devId="detail.asset-symbol"
                name="Symbol"
                present={assetPresent(kicadAssets?.symbol)}
                className="h-[142px]"
                art={<SymbolArt />}
                thumb={
                  assetPresent(kicadAssets?.symbol) ? (
                    <PreviewImage kind="symbol" partId={detail.id} fallback={<SymbolArt />} />
                  ) : undefined
                }
                onOpen={assetPresent(kicadAssets?.symbol) ? () => setPreview("symbol") : undefined}
              />
              <AssetTile
                devId="detail.asset-footprint"
                name="Footprint"
                present={assetPresent(kicadAssets?.footprint)}
                className="h-[142px]"
                art={<FootprintArt />}
                thumb={
                  assetPresent(kicadAssets?.footprint) ? (
                    <PreviewImage kind="footprint" partId={detail.id} fallback={<FootprintArt />} />
                  ) : undefined
                }
                onOpen={
                  assetPresent(kicadAssets?.footprint) ? () => setPreview("footprint") : undefined
                }
              />
            </div>
          </div>

          {/* THE PHOTOGRAPH, directly above the CAD row (owner 2026-07-26: "place product photo above
              the cad complete"). It used to sit in the Sourcing column on the reasoning that it is the
              distributor's own image, pulled from the same page as the price - true, but it puts all
              FOUR views of the part (3D body, symbol, land pattern, photograph) in one column, which
              is why they now read as one set of embodiments rather than as commercial trivia. */}
          {partPhotoSet.length ? (
            <div className="flex flex-none flex-col gap-1.5">
              {/* NO eyebrow. The button already says "View 2 Photos", so a PRODUCT PHOTO label above
                  it put the noun twice within a couple of centimetres - and neither neighbour in this
                  column (the Symbol/Footprint tiles, the CAD row) carries one either, so the label
                  was the odd element rather than the consistent one. */}
              <PhotoTrigger
                devId="detail.photo"
                variant="panel"
                photos={partPhotoSet}
                partName={detail.derived.display_name}
              />
            </div>
          ) : null}

          {/* CAD readiness is followed by the datasheet pinout. That makes the specimen rail a
              complete representation summary and turns its former dead space into bounded,
              searchable technical data rather than another top-level workbench destination. */}
          <div className="flex flex-col gap-1.5">
            <ReadinessBlock
              kicad={kicad}
              altium={altium}
              altiumNeeds={altiumNeeds}
              embed3d={embed3d}
              canComplete={canComplete}
              needsList={needsList}
              onComplete={() => setCompleteOpen(true)}
              removable={
                // a class that needs no assets of its own (a passive, a fiducial) references
                // STOCK assets by id and owns no files; element removal applies to owned files
                // only. Read off the class table, never off one hardcoded class name.
                onEditField && (partClass(detail.part_class)?.assets.length ?? 0) > 0
                  ? ([
                      // Every tool's attached assets, from the registry: a third EDA tool
                      // becomes removable by being registered, with no edit here. `kind` is
                      // the `<tool>_<asset kind>` vocabulary LibraryOps.detach_asset speaks.
                      ...EDA_TOOLS.flatMap((tool) =>
                        tool.assetKinds
                          .filter((k) => !(k in tool.unsupportedAssets))
                          .map((k) => {
                            const slot = assetsFor(detail, tool.key)[k as "symbol"];
                            if (!assetPresent(slot)) return null;
                            return {
                              kind: `${tool.key}_${k}`,
                              label: `${tool.label} ${assetTitleLabel(k)}`,
                            };
                          }),
                      ),
                      detail.datasheet ? { kind: "datasheet", label: "Datasheet" } : null,
                    ].filter(Boolean) as { kind: string; label: string }[])
                  : []
              }
              onRemove={(kind, label) => setPendingDetach({ kind, label })}
            />
          </div>
          {pinout.length > 0 ? (
            <CompactPinoutCard
              key={detail.id}
              pins={pinout}
              source={pinoutProvenance?.source}
              confidence={pinoutProvenance?.confidence}
            />
          ) : null}
          </div>

          {/* COLUMN 2 - the specifications, the technical heart, in one clean single column,
              led by the EDA handoff fields.
              Owner, 2026-07-25: "the most important fields (like the ones that go to the eda
              tools) should be top above the specifications. thats the most important info." They
              belong AT THE TOP OF THIS COLUMN, in the same area as the specs they lead - not as a
              full-width band across the sheet. An earlier attempt did the latter and rearranged
              the whole sheet around it, which moved a great deal nobody had asked to move. */}
          {!specsOpen ? (
            <CollapsedPaneRail
              devId="detail.specs-expand"
              label="Specifications"
              onExpand={() => setSpecsOpen(true)}
            />
          ) : (
          <div className="flex min-h-0 flex-col overflow-y-auto border-l border-line px-4">
            {/* KEY SPECIFICATIONS lead this column now, where the EDA handoff band used to sit. The
                owner's ask: "the important specifications should be where the eda handoff is,
                formatted like the specifications, but the most important details people care about
                when looking at this component". Curated per category (lib/keySpecs.ts) with a star on
                any Specifications row below to pin one up here. */}
            {/* THE DESCRIPTION LEADS, and Top Specifications is pushed down behind it. Owner,
                2026-07-26: "the item's description must be emphasized, perhaps above the top
                specifications". It is the one sentence that says what the part IS, and it had been
                reachable only from the Handoff tab - so the Details view opened on parameters
                without ever stating the thing they describe.
                Set in the sheet's reading size rather than as another label/value row: it is prose,
                not a parameter, and giving it the spec treatment is what made it disappear into the
                list before. The "N Sources" swap comes WITH it - two distributors word a description
                differently, and moving the text without its disclosure would silently drop the
                ability to choose between them. */}
            <DescriptionLede
              text={detail.derived.description}
              alternates={detail.alternates?.description ?? []}
              onUse={onEditField ? (value) => onEditField("description", value) : undefined}
            />
            <KeySpecificationsBlock
              groups={specGroups}
              category={detail.derived.category}
              pinned={pinnedSpecs}
              onTogglePin={togglePin}
            />
            <DetailSection
              data-dev-id="detail.specs-list"
              title={<Text id="detail.specifications">Specifications</Text>}
              action={
                <CollapsePaneButton
                  devId="detail.specs-collapse"
                  label="Specifications"
                  onCollapse={() => setSpecsOpen(false)}
                />
              }
            >
              <SpecificationsSection
                // A promoted row has one canonical home. The full sheet keeps the remaining depth;
                // it does not repeat the same fact immediately below the Key Specifications block.
                groups={remainingSpecGroups}
                hasPromotedSpecs={promotedSpecKeys.size > 0}
                alternates={specAlternates}
                onUseSpecValue={onUseSpecValue}
                category={detail.derived.category}
                pinned={pinnedSpecs}
                effectivePinned={promotedSpecKeys}
                onTogglePin={togglePin}
              />
            </DetailSection>
          </div>
          )}

          {/* COLUMN 3 - commercial + reference: where to buy, then the datasheet + a note.
              Once the sheet stacks it drops onto a second row UNDER the Specifications column
              (col-start-2), so it lands in the WIDE track rather than in the 288px specimen rail;
              in the single-column case it simply follows. The left hairline is a COLUMN divider, so
              it applies only while this really is a third column - kept at a wrap it would draw a
              rule across a stacked block.

              THESE MUST BE CONTAINER VARIANTS, matching the sheet's own tracks. Left on `lg:`/`xl:`
              they desynchronised from the grid the moment the grid became container-driven: at a
              1384px viewport `xl:col-start-auto` won, so this column auto-placed into the 288px
              FIRST track instead of under Specifications, both rows were forced to an equal 328px,
              and the asset tiles were sliced in half with a scrollbar on every box. Placement and
              track definition are one decision and have to move together. */}
          {!sourcingOpen ? (
            <CollapsedPaneRail
              devId="detail.sourcing-expand"
              label="Sourcing"
              onExpand={() => setSourcingOpen(true)}
            />
          ) : (
          <div className="flex min-h-0 flex-col gap-4 overflow-y-auto px-4 @xl:col-start-2 @4xl:col-start-auto @4xl:border-l @4xl:border-line">
            <DetailSection
              title={<Text id="detail.sourcing-head">Sourcing</Text>}
              action={
                <span className="inline-flex items-center gap-1">
                {detail.mpn ? (
                  <button
                    type="button"
                    data-dev-id="detail.sourcing-refresh"
                    onClick={() => refreshJob.run()}
                    disabled={refreshStatus === "running"}
                    className="inline-flex h-6 items-center gap-1 rounded-control border border-line bg-field px-2 text-2xs font-semibold text-t2 transition-colors hover:border-line2 hover:bg-raise2 hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc disabled:pointer-events-none disabled:opacity-60"
                  >
                    <RefreshIcon
                      className={refreshStatus === "running" ? "animate-spin" : undefined}
                    />
                    {refreshStatus === "running" ? (
                      <Text id="detail.sourcing-refreshing">Refreshing</Text>
                    ) : (
                      <Text id="detail.sourcing-refresh-label">Refresh</Text>
                    )}
                  </button>
                ) : null}
                  <CollapsePaneButton
                    devId="detail.sourcing-collapse"
                    label="Sourcing"
                    onCollapse={() => setSourcingOpen(false)}
                  />
                </span>
              }
            >
              <Sourcing purchase={detail.purchase} hasMpn={!!detail.mpn} />
              {tradeGroup ? (
                <TradeCompliance
                  group={tradeGroup}
                  alternates={specAlternates}
                  onUseSpecValue={onUseSpecValue}
                />
              ) : null}
            </DetailSection>
          </div>
          )}
        </WorkbenchPanel>

        {hasEnrich ? (
          <WorkbenchPanel
            id="enrich"
            devId="detail.enrich"
            active={activeTab}
            className="mt-3 min-h-0 flex-1 overflow-y-auto"
          >
            <EnrichPanel
              key={detail.mpn}
              mpn={detail.mpn}
              category={detail.derived.category}
              current={{
                manufacturer: detail.manufacturer,
                description: detail.derived.description,
              }}
              onApply={onEditField!}
              onApplyPinout={onApplyPinout}
              hasPinout={pinout.length > 0}
              busy={busy}
            />
          </WorkbenchPanel>
        ) : null}

        {/* THE HANDOFF TAB. It was a band at the head of the Specifications column; the owner chose
            (from previews) to give it a tab of its own, which also gives it room to state each tool's
            readiness instead of one shared "N of N ready" count. */}
        <WorkbenchPanel
          id="handoff"
          devId="detail.handoff-tab"
          active={activeTab}
          className="mt-3 min-h-0 flex-1 overflow-hidden"
        >
          <div className="mx-auto flex h-full min-h-0 w-full max-w-[980px] flex-col gap-3 px-1">
            <RepresentationMatrix detail={detail} />
            <div className="min-h-0 flex-1 overflow-auto rounded-panel">
              <div className="flex flex-col gap-3">
                <CadVariantSection
                  key={detail.id}
                  partId={detail.id}
                  enabled={activeTab === "handoff"}
                />
                <HandoffBand
                  detail={detail}
                  onEditField={onEditField}
                  onMoveCategory={onMoveCategory}
                  categories={categories}
                  busy={busy}
                  slots={{
                    // the disagreement follows the value it is about
                    description: (
                      <AlternatesDisclosure
                        entries={detail.alternates?.description ?? []}
                        current={detail.derived.description}
                        onUse={
                          onEditField
                            ? (value) => onEditField("description", value)
                            : undefined
                        }
                      />
                    ),
                  }}
                />
              </div>
            </div>
          </div>
        </WorkbenchPanel>

        <WorkbenchPanel
          id="history"
          devId="detail.history"
          active={activeTab}
          className="mt-3 min-h-0 flex-1 overflow-y-auto"
        >
          <PartTimeline key={detail.id} partId={detail.id} />
        </WorkbenchPanel>

      {/* footer: filing moved into the part pane; a destructive action never earns prime real
          estate, so Delete sits at the far edge - but as a GLYPH that states its consequence when
          you approach it, not as dim text that reads like a caption (punch 15). The shared
          IconButton carries the reveal, the tone and the running state, so every other destructive
          action in the app inherits the same language for free. */}
      <footer data-dev-id="detail.footer" className="mt-3 flex flex-none items-center justify-end border-t border-line pt-2.5">
        {onDelete ? (
          <IconButton
            data-dev-id="detail.delete"
            compact
            small
            variant="ghost-danger"
            icon={<TrashIcon />}
            label="Delete Part?"
            pending={deleting}
            pendingLabel="Deleting"
            onClick={() => setConfirmDelete(true)}
            disabled={busy}
          />
        ) : null}
      </footer>
      </div>

      {/* The one Complete-Part window: network collection fills CAD while editable rows fill
          metadata (datasheet, MPN, ...). Mounted only while open so its inputs start fresh. */}
      {completeOpen ? (
        <CompletePartModal
          detail={detail}
          hasModel={hasModel}
          busy={busy}
          onClose={() => setCompleteOpen(false)}
          onEditField={onEditField}
        />
      ) : null}

      <PreviewModal
        open={preview !== null}
        partId={detail.id}
        partName={detail.derived.display_name}
        available={{
          model: hasModel,
          symbol: assetPresent(kicadAssets?.symbol),
          footprint: assetPresent(kicadAssets?.footprint),
        }}
        initialKind={preview ?? "symbol"}
        onClose={() => setPreview(null)}
      />

      <ConfirmDialog
        open={pendingDetach !== null}
          title="Remove This Element?"
          body={
            <>
              Remove the <b>{pendingDetach?.label}</b> from this part? The file is
              deleted and the reference cleared; everything else stays.
            </>
          }
          confirmLabel="Remove"
          danger
          busy={detach.isPending}
          onCancel={() => setPendingDetach(null)}
          onConfirm={() => {
            if (!pendingDetach || !detail) return;
            const label = pendingDetach.label;
            detach.mutate(
              { id: detail.id, kind: pendingDetach.kind },
              {
                onSuccess: () => {
                  toast(`${label} removed.`, "ok");
                  setPendingDetach(null);
                },
                onError: (e) => {
                  toast(e instanceof Error ? e.message : "Could not remove it.", "err");
                  setPendingDetach(null);
                },
              },
            );
          }}
      />

      {onDelete ? (
        <ConfirmDialog
          open={confirmDelete}
          title="Delete This Part?"
          body={
            <>
              This removes {detail.derived.display_name}'s symbol, footprint, and record in
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

// One workbench tab panel. Every panel stays mounted (so its data is fetched once and a tab
// switch is instant); the inactive ones carry the `hidden` attribute, the WAI-ARIA tabs
// pattern, so only the active panel is shown and read out.
function WorkbenchPanel({
  id,
  active,
  devId,
  className,
  style,
  children,
}: {
  id: WorkbenchTab;
  active: WorkbenchTab;
  // When set, the panel carries a stable `data-dev-id` for the dev-mode inspector
  // (the panels whose region is not already named by an inner component's id).
  devId?: string;
  className?: string;
  /** Inline style, used only to carry a CSS custom property whose VALUE is dynamic - see
   *  panesTemplate for why the grid template cannot be a Tailwind class built from a literal. */
  style?: React.CSSProperties;
  children: ReactNode;
}) {
  return (
    <div
      role="tabpanel"
      data-dev-id={devId}
      id={tabPanelId("workbench", id)}
      aria-labelledby={tabButtonId("workbench", id)}
      hidden={active !== id}
      className={className}
      // Tailwind display utilities such as `grid` can override the browser's `[hidden]` rule.
      // The result was visible in the real host: selecting Representations left the entire
      // three-column Overview mounted above it. Inline display is the authoritative visibility
      // boundary; the `hidden` attribute remains for the accessibility tree.
      style={active !== id ? { ...style, display: "none" } : style}
    >
      {children}
    </div>
  );
}

// The headline is the derived human title, shown read-only (it is computed from the specs).
// Renaming edits the underlying display name in place: a quiet pencil reveals on hover /
// focus, and clicking it swaps the heading for an input pre-filled with the current name.
function TitleBlock({
  headline,
  name,
  onRename,
  busy,
}: {
  headline: string;
  name: string;
  onRename?: (value: string) => void;
  busy?: boolean;
}) {
  const { editing, draft, setDraft, begin, commit, cancel } = useInlineEdit(
    name,
    onRename ?? (() => {}),
  );

  if (editing) {
    return (
      <input
        autoFocus
        aria-label="Rename Part"
        value={draft}
        disabled={busy}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          } else if (e.key === "Escape") {
            e.preventDefault();
            cancel();
          }
        }}
        className="w-[280px] max-w-full rounded-control border border-line2 bg-field px-2 py-0.5 text-sm font-semibold tracking-[-0.01em] text-t1 outline-none focus:border-acc"
      />
    );
  }

  return (
    <div className="group flex min-w-0 items-center gap-1.5">
      <h1 data-dev-id="detail.title" className="min-w-0 truncate text-sm font-semibold tracking-[-0.01em] text-t1">
        {headline}
      </h1>
      {onRename ? (
        <button
          type="button"
          onClick={begin}
          disabled={busy}
          aria-label="Rename Part"
          className="grid h-5 w-5 flex-none place-items-center rounded-control text-t3 opacity-0 transition hover:bg-raise2 hover:text-t1 focus-visible:opacity-100 group-hover:opacity-100 disabled:opacity-0"
        >
          <Icon id="detail.rename" className="h-3 w-3" />
        </button>
      ) : null}
    </div>
  );
}

// The ONE section wrapper for the whole opened component: an uppercase micro eyebrow, then the
// content. Every data block (readiness, links, description, specifications, sourcing, tags) is a
// DetailSection, so the sheet reads as one consistent system instead of a mix of boxed cards and
// loose labels. Only genuinely-visual tiles (the asset previews) and the single call-to-action
// (Complete) stay boxed; everything that is DATA is a borderless section.
function DetailSection({
  title,
  action,
  className,
  children,
  ...rest
}: { title: ReactNode; action?: ReactNode } & Omit<HTMLAttributes<HTMLElement>, "title">) {
  return (
    <section className={className} {...rest}>
      {/* Pane-level heading: Title Case, t1 - a clear step ABOVE the uppercase micro-eyebrows
          the spec groups use, so "Specifications" and "Electrical" never read as the same level. */}
      <div className="mb-1.5 flex h-6 items-center justify-between gap-2">
        <span className="text-xs font-semibold text-t1">{title}</span>
        {action}
      </div>
      {children}
    </section>
  );
}

// One label/value row, the canonical alignment used across every section (readiness, links,
// specs, sourcing): the label left in quiet text, the value right. Everything lines up because
// everything routes through this.
function DataRow({
  label,
  children,
  className,
}: {
  label: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line/50 py-1.5 last:border-0">
      <span className="min-w-0 flex-none text-xs text-t2">{label}</span>
      <span className={"min-w-0 text-right text-xs text-t1 " + (className ?? "")}>{children}</span>
    </div>
  );
}

// The single readiness read: KiCad and Altium each as one row - a green check when the tool's
// symbol + footprint are both present, else an amber dot and the exact assets it still needs.
// The 3D model is optional (it never blocks readiness), so it is not in the needs line.
// What the readiness popover needs to render the Altium 3D embed row. `blocked` is the sentence
// explaining why the action cannot run (null = it can, "" = still checking), which is the whole
// point: a control that is unavailable must say WHY rather than sit there inert.
export interface Embed3dState {
  done: boolean;
  blocked: string | null;
  pending: boolean;
  onEmbed: () => void;
}

function ReadinessBlock({
  kicad,
  altium,
  altiumNeeds,
  embed3d,
  canComplete,
  needsList,
  onComplete,
  removable = [],
  onRemove,
}: {
  kicad: AssetReadiness;
  altium: AssetReadiness;
  altiumNeeds: string[];
  embed3d: Embed3dState | null;
  canComplete: boolean;
  needsList: string[];
  onComplete: () => void;
  // The elements this part carries that can be removed one by one (owner 2026-07-24:
  // a wrong capture must be deletable without touching the rest of the part).
  removable?: { kind: string; label: string }[];
  onRemove?: (kind: string, label: string) => void;
}) {
  const [open, setOpen] = useState(false);
  // KiCad needs come from the record's own refs; Altium needs prefer the capture query
  // (the record carries no Altium refs), falling back to its own blocking assets.
  const kicadNeeds = kicad.missing.filter((m) => m !== "3D Model");
  const altiumBlocking =
    altiumNeeds.length > 0
      ? altiumNeeds.map((n) => n.replace(/^Altium /, ""))
      : altium.missing.filter((m) => m !== "3D Model");
  const allReady = kicad.ready && altium.ready;
  // Readiness is tucked behind a button (owner's call): a compact status chip that opens a mini
  // popover carrying the KiCad + Altium detail and the Complete action, so the pane stays clean.
  return (
    <div className="relative" data-dev-id="detail.readiness">
      {/* The same row anatomy as Filing below (icon + uppercase label + value + chevron), so the
          two controls read as one unified property cluster, not two widget species. */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex h-8 w-full items-center gap-2.5 rounded-control border border-line bg-field px-3 text-left transition-colors hover:border-line2 hover:bg-raise2"
      >
        {allReady ? (
          <Icon id="detail.ready-check" className="h-3.5 w-3.5 flex-none" />
        ) : (
          <WarnIcon className="h-3.5 w-3.5 flex-none text-warn" />
        )}
        <span className={EYEBROW_DENSE}>CAD</span>
        <span className="ml-auto min-w-0 truncate text-xs font-medium text-t1">
          {allReady ? "Complete" : "Incomplete"}
        </span>
        <Icon
          id="detail.chevron-right"
          className={
            "h-3.5 w-3.5 flex-none text-t3 transition-transform " + (open ? "rotate-90" : "")
          }
        />
      </button>
      {open ? (
        // Opens UPWARD. This control is pinned near the bottom of the specimen rail by design (only
        // Filing sits below it), so a downward popover was clipped by the pane edge and a taller
        // window did not help: the rail grows too, and the control stays at the bottom. Measured
        // 2026-07-25 with `uishot.py --click detail.readiness` at 1000px AND 1500px viewport
        // heights, both cut off at the same place, which means the Altium row, the Complete Part
        // action and the Remove chips had ALL been unreachable. Anchoring to the bottom gives the
        // popover the whole rail height above it, which is always available here.
        <div className="absolute inset-x-0 bottom-[calc(100%+6px)] z-[70] rounded-card border border-line2 bg-popover p-3 shadow-pop">
          <ReadinessRow label="KiCad" ready={kicad.ready} needs={kicadNeeds} />
          <ReadinessRow label="Altium" ready={altium.ready} needs={altiumBlocking} />
          {embed3d ? <Embed3dRow state={embed3d} /> : null}
          {canComplete && needsList.length > 0 ? (
            <button
              data-dev-id="detail.complete-part"
              type="button"
              onClick={() => {
                setOpen(false);
                onComplete();
              }}
              className="group mt-3 flex w-full items-start gap-2.5 rounded-control border border-warn/40 bg-warn/[0.08] px-3 py-2.5 text-left transition hover:border-warn/70 hover:bg-warn/[0.12]"
            >
              <WarnIcon className="mt-0.5 h-4 w-4 flex-none text-warn" />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold text-t1">
                  <Text id="detail.complete-part">Complete Part</Text>
                </span>
                <span className="mt-0.5 block text-2xs leading-snug text-t2">
                  Add {needsList.join(", ")} to make this part usable.
                </span>
              </span>
            </button>
          ) : null}
          {onRemove && removable.length > 0 ? (
            <div className="mt-3 border-t border-line pt-2.5">
              <div className={`mb-1.5 ${EYEBROW_DENSE}`}>
                <Text id="detail.remove-eyebrow">Remove</Text>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {removable.map((r) => (
                  <button
                    key={r.kind}
                    type="button"
                    data-dev-id="detail.remove-asset"
                    onClick={() => {
                      setOpen(false);
                      onRemove(r.kind, r.label);
                    }}
                    className="inline-flex items-center gap-1 rounded-control border border-line px-2 py-1 text-2xs font-medium text-t2 transition-colors hover:border-err/60 hover:text-err focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
                  >
                    {r.label}
                    <span aria-hidden>{"\u00d7"}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/**
 * The Altium 3D embed row inside the readiness popover.
 *
 * It sits under the Altium status because that is where the gap is stated, so the fix is one
 * glance from the problem rather than in a different surface. Three honest states and no fourth:
 * DONE (the container really carries the payload, verified by reading it back from outside
 * Altium), BLOCKED with the reason spelled out, or an armed action. The run drives a real Altium
 * and takes a few seconds, so the pending state says what is happening instead of freezing.
 */
function Embed3dRow({ state }: { state: Embed3dState }) {
  if (state.done) {
    return (
      <div
        data-dev-id="detail.embed3d-done"
        className="ml-5 mt-1.5 flex items-center gap-2 border-l border-line py-1.5 pl-2.5"
      >
        <Icon id="detail.ready-check" className="h-3 w-3 flex-none" />
        <span className="text-2xs font-medium text-t2">3D Model embedded in the footprint</span>
      </div>
    );
  }
  const checking = state.blocked === "";
  const blocked = !!state.blocked;
  // Indented so the row reads as a CHILD of the Altium status line above it. The first version put
  // an "Altium" tag on the right instead, which was removed as redundant; that left the action
  // attributed to a tool by vertical position alone, which is not attribution. The indent says the
  // same thing structurally and costs no words.
  return (
    <div className="ml-5 mt-1.5 border-l border-line pl-2.5">
      <button
        type="button"
        data-dev-id="detail.embed3d"
        onClick={state.onEmbed}
        disabled={blocked || checking || state.pending}
        className="flex w-full items-center gap-2 rounded-control border border-acc/60 bg-acc/[0.14] px-2.5 py-2 text-left transition-colors hover:border-acc hover:bg-acc/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc disabled:pointer-events-none disabled:border-line disabled:bg-field disabled:opacity-60"
      >
        {/* A cube receiving a body, not a chevron: this control WRITES, it does not navigate. The
            accent border and tint are what separate an action from the two status rows above it,
            which is the whole reason the row is styled differently rather than uniformly. */}
        <Icon id="detail.embed-3d" className="h-4 w-4 flex-none text-acc" />
        {/* The LABEL carries the accent, not just the background. A tinted fill reads in the dark
            theme and washes out to plain white in the light one, so the affordance existed in only
            one theme; coloured text is legible in both. Caught by shooting both, not by reasoning. */}
        <span className="text-2xs font-semibold text-acc">
          {state.pending ? "Embedding 3D Model..." : "Embed 3D Model"}
        </span>
      </button>
      {/* Sentence case for prose, per the design contract, and the reason is never omitted: an
          unavailable control that does not explain itself is indistinguishable from a broken one. */}
      {blocked ? (
        <p data-dev-id="detail.embed3d-blocked" className="mt-1 px-2.5 text-2xs leading-snug text-t3">
          {state.blocked}
        </p>
      ) : null}
      {state.pending ? (
        <p className="mt-1 px-2.5 text-2xs leading-snug text-t3">
          Altium is writing the 3D body into the footprint library. This takes a few seconds.
        </p>
      ) : null}
    </div>
  );
}

function ReadinessRow({
  label,
  ready,
  needs,
}: {
  label: string;
  ready: boolean;
  needs: string[];
}) {
  return (
    <DataRow
      label={
        <span className="flex items-center gap-2">
          {ready ? (
            <Icon id="detail.ready-check" className="h-3.5 w-3.5 flex-none" />
          ) : (
            <span
              className="h-2 w-2 flex-none rounded-full"
              style={{ background: "var(--c-warn)" }}
            />
          )}
          <span className="font-medium text-t1">{label}</span>
        </span>
      }
    >
      <span className={ready ? "text-ok" : "text-t2"}>
        {ready
          ? "Ready"
          : needs.length > 0
            ? `Needs ${needs.map((n) => n.toLowerCase()).join(" + ")}`
            : "Not ready"}
      </span>
    </DataRow>
  );
}


// One Part Canvas tile. `hero` is the big physical (3D) stage; `tile` is a compact
// embodiment (symbol / footprint). A present asset exposes the SAME stage-centred Expand
// affordance on hover or keyboard focus; the footer is identity/status only. Missing assets stay
// the honest Not Linked state and are completed through the network workflow, never this tile.
function AssetTile({
  name,
  present,
  art,
  thumb,
  onOpen,
  className,
  devId,
  stageDevId,
}: {
  name: string;
  present: boolean;
  art: ReactNode;
  // The live render shown when present (falls back to `art` internally on failure);
  // omit it and `art` is shown directly.
  thumb?: ReactNode;
  // When present and set, the stage offers a hover/focus Expand action.
  onOpen?: () => void;
  // Height / extra classes for the tile shell (the caller sizes it in its layout).
  className?: string;
  // The stable dev-mode id for the tile shell; each of the three call sites passes a
  // distinct value (hero / symbol / footprint) so inspect can name them apart.
  devId?: string;
  // The stable dev-mode id for the inner stage chamber (the hero copper-glow stage).
  stageDevId?: string;
}) {
  const stage = (
    <div
      data-dev-id={stageDevId}
      className={
        "group relative flex min-h-0 flex-1 items-center justify-center overflow-hidden " +
        (present ? "bg-stage" : "flex-col gap-2 bg-stage text-t3")
      }
    >
      {/* no stage dressing: the 3D chamber is the flat bg-stage surface (owner's call - the
          glow/vignette gradient is gone), so the render sits on a plain field like the
          symbol and footprint tiles */}
      {/* absolute so the preview image / 3D canvas is taken OUT of the intrinsic-height flow:
          otherwise a large SVG/GLB render leaks its natural height into the flex/grid column and
          balloons the whole row. The stage (relative, min-h-0) then collapses to nothing on its
          own and simply fills whatever height the grid cell gives it. */}
      <div className="absolute inset-0 flex items-center justify-center">
        {present ? (
          thumb ?? art
        ) : (
          <div className="flex flex-col items-center gap-1.5">
            <UploadIcon />
            <span className="text-2xs">No {name}</span>
          </div>
        )}
      </div>
      {present && onOpen ? (
        <button
          type="button"
          data-dev-id={devId ? `${devId}-open` : undefined}
          onClick={onOpen}
          aria-label={`Open ${name} Preview`}
          className="absolute inset-0 z-10 flex items-center justify-center bg-canvas/0 opacity-0 transition-[background-color,opacity] duration-150 group-hover:bg-canvas/70 group-hover:opacity-100 focus-visible:bg-canvas/70 focus-visible:opacity-100 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-acc"
        >
          <span className="inline-flex items-center gap-2 rounded-control border border-line2 bg-popover px-3 py-2 text-xs font-semibold text-t1 shadow-pop">
            <EyeIcon className="h-4 w-4 text-t2" />
            Expand
          </span>
        </button>
      ) : null}
    </div>
  );
  const footer = (
    <div className="flex h-7 items-center gap-2 px-3">
      <span className="min-w-0 truncate text-2xs font-semibold text-t1">{name}</span>
      {/* The STATUS never wraps: "Not Linked" broke as "Not / Linked" across two lines in the
          130px Symbol and Footprint tiles, which made a two-word state read as two states and
          pushed the footer to a second row. It is two short words and a dot, so it is the NAME
          on the left that should give way (truncate) if anything has to. */}
      <span className="ml-auto inline-flex flex-none items-center gap-1.5 whitespace-nowrap text-2xs text-t3">
        {present ? (
          <>Linked</>
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
    "flex min-h-0 min-w-0 flex-col overflow-hidden rounded-card border border-line bg-raise " +
    (className ?? "");
  // Present previews are plain shells with one consistent action INSIDE the stage. That keeps the
  // footer quiet, avoids nesting a button around the renderer, and gives 3D, Symbol, and Footprint
  // the same interaction instead of three subtly different click contracts.
  if (onOpen && present) {
    return (
      <div data-dev-id={devId} className={base}>
        {stage}
        {footer}
      </div>
    );
  }
  return (
    <div data-dev-id={devId} className={base}>
      {stage}
      {footer}
    </div>
  );
}

// All specs render at once inside the Specs tab (never collapsed): each group (Electrical /
// Physical / Ratings / Other) is its own labelled block, and the rows within it are a compact
// two-column definition list - the key in quiet sans on the left, the value in the mono readout
// face on the right - so a long value wraps in place. The tab owns the scroll, so however many
// specs a part carries, they never grow the page.
// The property grid's column tracks, defined ONCE. A spec row and the alternates nested under it
// must put their values at the same x or the comparison is unreadable, and the alternates drifted
// the moment the parent row changed - so the label-track width is a shared constant, and the nested
// list subtracts its own 7px indent from the label track rather than adding padding that would
// shift every column right.
// WRITTEN OUT IN FULL, never assembled from a variable. Tailwind generates utilities by scanning
// source TEXT, so an arbitrary value interpolated into a template literal yields a class attribute
// with NO CSS behind it. That failure is invisible to a class-name assertion: `display:grid` still
// applies (it is a literal) while `grid-template-columns` silently does not exist, and the grid
// collapses to one cell per line. It shipped green tests and a broken layout until a shot showed it.
//
// The 10.5rem label track appears in both strings, and a test in eyebrowConsistency holds the two in
// sync - a child's value must land at the same x as its parent's or the comparison is unreadable.
// The label track is RESPONSIVE: a fixed 10.5rem is right in the three-column layout, but once the
// sheet stacks into a ~250px column it ate two thirds of the row and forced "100 nF" to wrap
// mid-value. It narrows to 7rem there, which is still enough for the labels and leaves the value
// whole. Same widths on both levels, asserted by a gate.
// The label track keys off the SHEET's container query, never the viewport. As `xl:` it widened the
// label to 10.5rem inside a column only 205px wide, which is part of why a value had nowhere left to
// go and wrapped one word per line.
//
// The widening threshold is @2xl (672px), NOT the three-column @4xl: once the sheet stacks, the
// Specifications track is the WIDE one (537px measured at an 825px container), and holding the
// narrow 7rem track there truncated real labels - "Operating Tempera...", "Moisture Sensitivit...".
// A label clipped to an ellipsis has lost the same information a clipped value would.
// THREE tracks: label, value, and a fixed lane for the pin star. The star used to be a third child of
// a TWO-column grid, so it wrapped onto a new implicit row and doubled the height of every spec row -
// visible instantly in a render, invisible to every test, because jsdom does no layout. The lane is a
// fixed 16px and is always present so a list WITHOUT pinning keeps identical row geometry.
const SPEC_ROW_GRID =
  "grid grid-cols-[minmax(0,7rem)_minmax(0,1fr)_16px] " +
  "@2xl:grid-cols-[minmax(0,10.5rem)_minmax(0,1fr)_16px] " +
  "@4xl:grid-cols-[minmax(0,13rem)_minmax(0,1fr)_16px] items-baseline gap-3";
const ALT_ROW_GRID =
  "grid grid-cols-[minmax(0,calc(7rem-7px))_minmax(0,1fr)_auto] " +
  "@2xl:grid-cols-[minmax(0,calc(10.5rem-7px))_minmax(0,1fr)_auto] " +
  "@4xl:grid-cols-[minmax(0,calc(13rem-7px))_minmax(0,1fr)_auto] items-baseline gap-3";


/**
 * A spec value, with a comma-separated LIST rendered one option per line.
 *
 * Owner, 2026-07-25. "Packaging: Reel, Cut Tape, MouseReel" is three separate options, and as one
 * run of text it wrapped mid-phrase into "Reel, Cut" / "Tape," / "MouseReel" - which reads as a
 * sentence that ran out of room rather than as three things. Same height, but each line is now a
 * whole answer.
 *
 * Deliberately conservative about what counts as a list, because a comma inside a value is common
 * and splitting one would corrupt the reading:
 *   - every part must be short and word-like, so "-40°C ~ 125°C (TA)" and "2.5A (8/20us)" are left
 *     alone even where they contain a comma;
 *   - a number with thousands separators ("1,000") is one value, never two;
 *   - fewer than two parts is not a list.
 * Anything that fails those is rendered exactly as it arrived.
 */
function AtomicValue({ text }: { text: string }) {
  const tokens = text.split(/(\s+)/);
  const atRisk = tokens.some(
    (tok) => BREAKABLE_INSIDE.test(tok) && tok.length <= SPEC_TOKEN_MAX,
  );
  if (!atRisk) return <>{text}</>;
  return (
    <>
      {tokens.map((tok, i) =>
        BREAKABLE_INSIDE.test(tok) && tok.length <= SPEC_TOKEN_MAX ? (
          <span key={i} className="whitespace-nowrap">
            {tok}
          </span>
        ) : (
          tok
        ),
      )}
    </>
  );
}

// A token this long cannot fit the value track at any realistic width, so it is left breakable:
// an overflowing row is worse than an ugly break. Sized from the measurement below (a ~48px track
// fits about 6 monospace characters, and real protected tokens are 8-12).
const SPEC_TOKEN_MAX = 20;

/** Values whose tokens contain a character the browser treats as a break opportunity. */
const BREAKABLE_INSIDE = /\//;

/** The value with only its AT-RISK tokens held together.
 *
 * MEASURED in real Chromium (a width sweep over the actual value at 12px monospace), because jsdom
 * does no layout and this question cannot be answered by the unit suite:
 *
 *     track 60px+  break-word -> ["2.5A ", "(8/20us)"]            fine
 *     track 48px   break-word -> ["2.5A ", "(8/20u", "s)"]        BREAKS INSIDE
 *     track 40px   break-word -> ["2.5A ", "(8/20", "us)"]        BREAKS INSIDE
 *     any width    nowrap span -> ["2.5A ", "(8/20us)"]           fixed
 *
 * `word-break: keep-all` was measured and does NOTHING here (byte-identical output at every
 * width), so it is not the fix despite reading like it should be. A reader cannot tell "8/20us"
 * from "8/20u s", which makes this a correctness problem rather than a cosmetic one.
 *
 * ONLY at-risk tokens are wrapped. Splitting every value into spans fragments the text node, and
 * `getByText` matches an element by its DIRECT text children - so a blanket split silently broke
 * every existing query for a spec value. A value with no `/` is returned as plain text, unchanged.
 */
function SpecValue({ value }: { value: string }) {
  const text = (value ?? "").trim();
  const parts = text.split(",").map((p) => p.trim());
  const isList =
    parts.length > 1 &&
    parts.every((p) => p.length > 0 && p.length <= 24 && /^[A-Za-z][A-Za-z0-9 ./+-]*$/.test(p));
  if (!isList) return <AtomicValue text={text} />;
  return (
    <span data-dev-id="detail.spec-list" className="flex flex-col gap-0.5">
      {parts.map((p) => (
        <span key={p}>
          <AtomicValue text={p} />
        </span>
      ))}
    </span>
  );
}

// Where two sources disagreed, the panel says so and lets the reader put the other answer in
// force (punch 9: "keep BOTH sourcing descriptions / swap between them"). Quiet until asked,
// because most fields have one answer and a wall of vendor attributions would drown the data.
//
// Deliberately the SAME expand-in-place shape as SpecFamilyRow, so the panel has one language
// for "there is more behind this" instead of a popover here and a disclosure there.
function AlternatesDisclosure({
  entries,
  current,
  onUse,
}: {
  entries: SourcedAlternate[];
  current: string;
  onUse?: (value: string, source: string) => void;
}) {
  const [open, setOpen] = useState(false);
  // Only worth showing when a source actually offered something ELSE; the value in force is
  // repeated as the first entry, so a one-entry list is not a disagreement.
  const distinct = entries.filter((e) => String(e.value ?? "").trim() !== "");
  if (distinct.length < 2) return null;
  const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();
  return (
    <div data-dev-id="detail.alternates" className="mt-0.5">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-2xs text-t3 transition-colors hover:text-t1"
      >
        <Chevron open={open} />
        {distinct.length} Sources
      </button>
      {open ? (
        // Indented under a left rule, exactly like a family row's members: both are children of
        // the row above them, and giving the same relationship two different treatments made the
        // panel look like it had two unrelated kinds of nesting.
        <ul className="mb-0.5 ml-[7px] flex flex-col border-l border-line">
          {distinct.map((entry, i) => {
            const value = String(entry.value ?? "");
            const inForce = same(value, current);
            const label = entry.source ? distributorLabel(entry.source) : "On Record";
            return (
              <li key={`${entry.source}-${i}`} className={`${ALT_ROW_GRID} py-[2px]`}>
                {/* one line per answer: who said it, what they said, and the action. The value used
                    to sit on its own second line, which orphaned it from its source label. */}
                {/* inset inside its own cell, so the indent never moves the value column */}
                <span className={`min-w-0 truncate pl-2.5 ${EYEBROW_DENSE}`}>{label}</span>
                {/* The answer IN FORCE reads strongest. It was the quietest thing in the block
                    while the alternative carried a bordered button, so the panel emphasised the
                    value it was not using over the one it was. */}
                <span
                  className={
                    "tnum min-w-0 truncate font-mono text-xs " +
                    (inForce ? "font-semibold text-t1" : "text-t2")
                  }
                >
                  {value}
                </span>
                {inForce ? (
                  <span className={`flex-none ${EYEBROW_DENSE}`}>
                    In Use
                  </span>
                ) : onUse ? (
                  <button
                    type="button"
                    onClick={() => onUse(value, entry.source)}
                    className="flex-none rounded-control border border-line px-1 py-[1px] text-2xs font-semibold text-t2 transition-colors hover:border-acc hover:text-t1"
                  >
                    Use {label}
                  </button>
                ) : (
                  <span className="flex-none text-2xs text-t3">&nbsp;</span>
                )}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

// The one disclosure marker the panel uses. A rotating chevron rather than a `+`/`-`: this app has
// a real icon system, and an ASCII plus in a dense property grid reads as a minus sign or a stray
// character, not as something you can open.
function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 16 16"
      className={
        "h-2.5 w-2.5 flex-none transition-transform " + (open ? "rotate-90" : "")
      }
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M6 4l4 4-4 4" />
    </svg>
  );
}

// One fact stated once per jurisdiction (six HTS codes, one per region) collapses to a single
// row that says how many it holds, and opens IN PLACE to show each one (punch 3). It expands
// rather than opening a popover on purpose: these are not competing answers to compare, they are
// facets of one fact, and a reader wants them listed under their own heading.
function SpecFamilyRow({ row }: { row: SpecRow }) {
  const [open, setOpen] = useState(false);
  const members = row.members ?? [];
  return (
    <div data-dev-id="detail.spec-family">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="-mx-1.5 flex w-full items-baseline justify-between gap-3 rounded-[2px] px-1.5 py-[3px] text-left transition-colors hover:bg-[var(--c-hover)]"
      >
        {/* spans, not dt/dd: a definition term is only valid as a child of a dl (or a div in one),
            and nesting one inside a button reads as neither to a screen reader. The list semantics
            live on the member rows below, which are real dt/dd pairs. */}
        <span className="flex min-w-0 flex-1 items-baseline gap-1.5 truncate text-xs text-t2">
          <Chevron open={open} />
          {row.label}
        </span>
        <span className="tnum flex-none font-mono text-xs text-t3">
          {members.length} {members.length === 1 ? "Region" : "Regions"}
        </span>
      </button>
      {open ? (
        <div className="mb-0.5 ml-[7px] border-l border-line pl-2.5">
          {members.map((m) => (
            <div
              key={m.key}
              className="flex items-baseline justify-between gap-3 py-[2px]"
            >
              <dt className={`min-w-0 flex-1 truncate ${EYEBROW_DENSE}`}>
                {m.label}
              </dt>
              <dd className="tnum flex-none truncate text-right font-mono text-xs text-t1">
                {m.value}
              </dd>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function SpecificationsSection({
  groups,
  hasPromotedSpecs,
  alternates,
  onUseSpecValue,
  category,
  pinned,
  effectivePinned,
  onTogglePin,
}: {
  groups: SpecGroup[];
  hasPromotedSpecs: boolean;
  alternates: Record<string, SourcedAlternate[]>;
  onUseSpecValue?: (key: string, value: string, source: string) => void;
  // Pinning is threaded down to the ROW because that is where the star lives: the owner's chosen
  // model is "a star on any Specifications row promotes it into Key Specifications".
  category: string;
  pinned: PinnedSpecs;
  effectivePinned: ReadonlySet<string>;
  onTogglePin: (category: string, specKey: string) => void;
}) {
  // Only the groups the user has EXPLICITLY toggled live here; everything else falls back to the
  // index-based default below. Storing the default in state instead would make it a snapshot that
  // goes stale the moment a different part arrives with different groups.
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});
  if (groups.length === 0) {
    return (
      <div data-dev-id="detail.specs" className="text-sm text-t3">
        {hasPromotedSpecs
          ? "All available specifications are shown above."
          : "No parametric specs on record for this part."}
      </div>
    );
  }
  // One clean column inside its own pane (the middle of the three-pane sheet). Groups stack in a
  // consistent rhythm; the pane owns its scroll, so however many rows a part carries, the page
  // never grows.
  return (
    <div data-dev-id="detail.specs" className="flex flex-col gap-3.5">
      {groups.map((group, index) => (
        // px-1.5 ABSORBS THE ROW HOVER BLEED, and belongs on the row's DIRECT container. Each spec
        // row is `-mx-1.5 px-1.5` so its hover highlight extends past the text column; with no
        // padding to land in, that bleed pushed 6px outside (measured: clientWidth 486, scrollWidth
        // 492) and put a horizontal scrollbar under a column with nothing to scroll to.
        // Altium property-grid feel: clean rows with no per-row hairline (that ledger look is
        // gone) - separation is spacing plus a live row hover, and the value reads in the mono
        // data face. The group name stays TYPE ONLY, matching every other eyebrow in the panel;
        // punch 14 removed the box behind it and nothing here re-adds one.
        //
        // The FIRST group is open and the rest are closed. It is the group that identifies the part
        // (Electrical for a diode, and whatever `groupSpecs` ranks first otherwise), so the column
        // opens on the specs someone came to read and holds the rest one click away rather than
        // throwing all 21 rows at them. An explicit toggle always wins over that default.
        <SpecSection
          key={group.title}
          title={group.title}
          count={group.rows.length}
          open={openGroups[group.title] ?? defaultOpen(group, index)}
          onToggle={() =>
            setOpenGroups((prev) => ({
              ...prev,
              [group.title]: !(prev[group.title] ?? defaultOpen(group, index)),
            }))
          }
        >
          <SpecRowList
            rows={group.rows}
            alternates={alternates}
            onUseSpecValue={onUseSpecValue}
            category={category}
            pinned={pinned}
            effectivePinned={effectivePinned}
            onTogglePin={onTogglePin}
          />
        </SpecSection>
      ))}
    </div>
  );
}

/**
 * Which spec groups start open.
 *
 * The FIRST group, because it is the one that identifies the part (Electrical for a diode, and
 * whatever `groupSpecs` ranks first otherwise) - the column should open on what someone came to
 * read. And any group small enough that collapsing it saves nothing: a disclosure holding one row
 * costs a header, a caret and a click to reveal a single value, which is more chrome than the value
 * it is hiding. `OTHER 1` was exactly that.
 */
function defaultOpen(_group: SpecGroup, _index: number): boolean {
  // ALL of them, per the owner 2026-07-26: "the specifications should all be expanded by default".
  // This replaces "first group, plus any group small enough that collapsing it saves nothing" - the
  // reasoning there was about not throwing 21 rows at someone, which the owner has now overruled.
  // An explicit toggle still wins over this default.
  return true;
}

/**
 * A DENSE collapsible section, for the reference columns.
 *
 * Owner, 2026-07-25: *"some specs and sourcing is just data vomit not organized cleanly or doesnt
 * have things hidden behind buttons. its so much thrown in your face."* Measured on their part: 21
 * spec rows across 5 groups plus a 10-row trade block plus a 6-tier ladder, every one of them
 * expanded at once, with no affordance anywhere to put any of it away.
 *
 * NOT `SettingsDisclosure`, deliberately: that one is a 44px row that wraps its content in a `Card`,
 * which is the right weight for a settings page and roughly four times the weight of a spec row. The
 * contract here is the panel's existing eyebrow rhythm, so this borrows that component's ANATOMY
 * (caret, title, right-aligned summary, aria-expanded) at the density this column already uses.
 *
 * The count lives in the header because a closed section must still say how much it is holding -
 * a disclosure that hides an unknown quantity just moves the problem.
 */
function SpecSection({
  title,
  count,
  open,
  onToggle,
  children,
}: {
  title: string;
  count: number;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <section data-dev-id="detail.spec-group" className="px-1.5">
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        data-dev-id="detail.spec-group-toggle"
        className="-mx-1.5 mb-1 flex w-full items-center gap-1.5 rounded-control px-1.5 py-0.5 text-left transition-colors hover:bg-[var(--c-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-acc"
      >
        <Icon
          id="detail.chevron-right"
          className={
            "h-3 w-3 flex-none text-t3 transition-transform duration-150 " +
            (open ? "rotate-90" : "")
          }
        />
        <span className={`min-w-0 truncate ${EYEBROW_DENSE}`}>{title}</span>
        {/* The count is the whole point of a closed section, so it is always present rather than
            only while closed - a number that appears and disappears reads as a state change.
            It sits NEXT TO its label, not flushed right: `ml-auto` put it at the far edge of a
            530px column, measured ~500px from the word it counts, so four numbers hung in a
            column with nothing tying them to anything. A count belongs to its noun. */}
        <span className="flex-none text-2xs tabular-nums text-t3">{count}</span>
      </button>
      {open ? children : null}
    </section>
  );
}

// The rows of one spec group. Shared by the Specs sheet and the Sourcing tab's Trade block, so
// a family disclosure and a vendor disagreement look and behave identically wherever they appear.
function SpecRowList({
  rows,
  alternates,
  onUseSpecValue,
  category,
  pinned,
  effectivePinned,
  onTogglePin,
}: {
  rows: SpecRow[];
  alternates: Record<string, SourcedAlternate[]>;
  onUseSpecValue?: (key: string, value: string, source: string) => void;
  // OPTIONAL, because not every list can be pinned FROM. Trade & Compliance renders through this
  // same component, and those are procurement facts rather than part parameters - `keySpecs`
  // deliberately excludes them, so offering a star there would promise something it would not do.
  category?: string;
  pinned?: PinnedSpecs;
  // The keys Top Specifications is already showing, so a row that is up there by CURATION reads as
  // pinned down here too instead of offering to pin what is already pinned (owner, 2026-07-26).
  // Absent for the lists that cannot be pinned from at all.
  effectivePinned?: ReadonlySet<string>;
  onTogglePin?: (category: string, specKey: string) => void;
}) {
  return (
    // The row breakpoints must resolve against THIS list's column, not the full detail pane.
    // Without this container boundary an equal 280px pane inherited the detail root's @4xl
    // 13rem label track, leaving too little value width and wrapping `3A991`, `Active`, and
    // `Japan` into vertical fragments.
    <dl className="@container flex flex-col">
      {rows.map((row) =>
        row.members ? (
          <SpecFamilyRow key={row.key} row={row} />
        ) : (
          <div key={row.key} className="-mx-1.5 px-1.5">
            {/* The hover fill belongs to the row HEADER, not to the row plus everything it opened:
                on the outer element it highlighted a four-line region in an otherwise flat property
                grid, which read as a raised card rather than as a hovered row.

                A GRID rather than justify-between: pushing the label left and the value hard right
                made the eye cross a long empty gap to pair them on a wide column ("Applications
                ......... HDMI"), which the owner flagged in their own shot critique. A bounded label
                track puts every value in a group at the SAME x, immediately beside its label, which
                is what a property grid is for. */}
            <div className={`-mx-1.5 ${SPEC_ROW_GRID} rounded-[2px] px-1.5 py-[3px] transition-colors hover:bg-[var(--c-hover)]`}>
              <dt
                className="min-w-0 truncate text-xs text-t2"
                title={typeof row.label === "string" ? row.label : undefined}
              >
                {row.label}
              </dt>
              {/* Left-aligned in its own track: a single part sheet has nothing to compare down the
                  column, so tabular right-alignment only bought distance from the label.
                  WRAPS rather than truncates - the owner's complaint is that specs get CUT OFF, and a
                  value clipped to "100 …" has lost the data. Two lines costs nothing; a hidden value
                  costs the whole point of the row. */}
              <dd className="tnum min-w-0 break-words font-mono text-xs text-t1">
                <SpecValue value={row.unit ? `${row.value} ${row.unit}` : row.value} />
              </dd>
              {/* Promotes this spec into Key Specifications at the head of the column. Hidden until
                  the row is hovered or the star is focused, so ~30 of these do not compete with the
                  values they sit beside. */}
              {/* the lane is always here so row geometry never depends on whether this list can
                  be pinned from; only the control inside it is conditional */}
              {onTogglePin && category ? (
                <PinStar
                  pinned={isPinned(pinned ?? {}, category, row.id ?? row.key)}
                  locked={isCuratedOnly(
                    effectivePinned ?? new Set<string>(), pinned ?? {}, category, row.key,
                  )}
                  onToggle={() => onTogglePin(category, row.id ?? row.key)}
                  label={typeof row.label === "string" ? row.label : row.key}
                />
              ) : (
                <span aria-hidden />
              )}
            </div>
            {/* a spec two distributors disagree about keeps both answers, swappable. `raw` and not
                `value`: "1%" renders as "±1%", and comparing the presented string made the answer
                already in force look like a different one. */}
            <AlternatesDisclosure
              entries={alternates[row.key] ?? []}
              current={row.raw}
              onUse={
                onUseSpecValue
                  ? (value, source) => onUseSpecValue(row.key, value, source)
                  : undefined
              }
            />
          </div>
        ),
      )}
    </dl>
  );
}

// Where a part comes from and how it is classified for import, next to the prices rather than
// buried in the physical spec sheet (punch 2 + 3). Every value here was already being pulled from
// the distributor and, until Batch 3, thrown away before it ever reached a record.
function TradeCompliance({
  group,
  alternates,
  onUseSpecValue,
}: {
  group: SpecGroup;
  alternates: Record<string, SourcedAlternate[]>;
  onUseSpecValue?: (key: string, value: string, source: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    // px-1.5 for the same reason as the specs column: these are SpecRows, and their -mx-1.5 hover
    // bleed needs padding to land in or it overflows the block (measured 527 vs 533).
    // CLOSED by default. Ten rows of classification, country of origin and order minima are
    // reference material you look up perhaps twice in a part's life, and they were being given the
    // same standing as the price - which is the whole of the owner's "data vomit" reading of this
    // column. The header still states the count, so nothing is hidden without saying how much.
    <section data-dev-id="detail.trade" className="mt-5 border-t border-line pt-3.5">
      <SpecSection
        title="Trade And Compliance"
        count={group.rows.length}
        open={open}
        onToggle={() => setOpen((o) => !o)}
      >
        {/* Says WHOSE facts these are. Sitting directly under the last distributor's price ladder,
            the block read as that distributor's tariff rather than the part's own classification. */}
        <p className="mb-2 text-2xs text-t3">Part-level, from the distributor pages.</p>
        <SpecRowList
          rows={group.rows}
          alternates={alternates}
          onUseSpecValue={onUseSpecValue}
        />
      </SpecSection>
    </section>
  );
}

/**
 * One distributor's price ladder, CLOSED by default.
 *
 * The unit price and the stock count stay on the vendor's own line, always visible, because that
 * is what the Sourcing column exists to answer. The ladder is the follow-up question - what does it
 * cost at quantity - and printing six tiers per distributor under every part is most of why this
 * column read as a wall. Closed it costs one line and states how many tiers it holds.
 */
function VendorLadder({
  tiers,
  currency,
}: {
  tiers: { qty: number; price: number }[];
  // The record's own field is optional, and `formatPrice` already treats an empty currency as USD,
  // so the default is stated here rather than widening that function's contract.
  currency?: string;
}) {
  const money = (value: number) => formatPrice(value, currency ?? "");
  // OPEN by default, per the owner 2026-07-26: "the sourcing pricing should be maximized always".
  // This overrides the reasoning in the comment above, which was written when the ladder was judged
  // to be most of why this column read as a wall - the owner has since decided the price ladder is
  // the point of the column, not clutter in it. The toggle stays so a single view can be quietened,
  // but every part and every vendor now OPENS maximized rather than needing two clicks to compare.
  const [open, setOpen] = useState(true);
  return (
    <SpecSection
      title="Volume Pricing"
      count={tiers.length}
      open={open}
      onToggle={() => setOpen((o) => !o)}
    >
      {/* The qty-1 unit price is already the headline beside the stock, so the ladder normally
          starts at the first bulk tier (10+, 100+, ...). It reads from 1+ instead whenever that is
          what keeps the count EVEN, because this is a two-column flow and an odd count leaves a
          hole in the bottom-right cell (punch 5). Parity is reached by showing MORE, never by
          hiding a price. */}
      {/* ROW-major (owner's decision, 2026-07-26, from previews). `grid-flow-col` filled the
          columns first, so the first ROW read "1+ $1.22 | 500+ $0.56" - two tiers five steps
          apart sitting side by side, while a person reads a price table across. The DOM order was
          always correct; only the flow was newspaper-style. The even-count logic above still
          matters: it keeps the bottom-right cell from being a hole. */}
      <div className="grid grid-cols-2 gap-x-10">
        {tiers.map((b) => (
          <div
            key={b.qty}
            className="tnum flex items-baseline justify-between py-[3.5px] font-mono text-xs"
          >
            <span className="text-t3">{b.qty}+</span>
            <span className="font-semibold text-t1">{money(b.price)}</span>
          </div>
        ))}
      </div>
    </SpecSection>
  );
}

function Sourcing({
  purchase,
  hasMpn,
}: {
  purchase: PurchaseRef[];
  hasMpn: boolean;
}) {
  // Mouser leads, then DigiKey, then the rest (punch 4). The record's own order is whatever the
  // add flow stored - the pasted vendor led it - so a part bought once from DigiKey listed
  // DigiKey first forever, regardless of where the owner actually buys.
  // Held as a STRING so the field can be emptied while typing without the row prices flickering
  // through 0, and so "blank" is a real state distinct from "1".
  // BLANK by default (owner 2026-07-26). Empty means "no quantity asked", which reads as qty 1 below,
  // so the panel looks and prices exactly as it did before anyone types - the quantity feature costs
  // nothing until it is used.
  // The quantity the sourcing maths prices against. The owner removed the visible input
  // (2026-07-26) but NOT the quantity-aware selection it fed: `recommendVendor` and `extendedPrice`
  // still decide Recommended by what an order actually costs rather than by the qty-1 price, which
  // was a real bug when it was fixed. One named constant, so the day a quantity arrives from
  // somewhere real (a project BOM line) there is exactly one place to feed it.
  const needQty = 1;
  const orderable = orderPurchases(purchase.filter((p) => p.url));
  if (orderable.length === 0) {
    return (
      <div data-dev-id="detail.sourcing" className="text-xs text-t2">
        {hasMpn
          ? "No purchase link on record yet."
          : "Not orderable yet, this component has no part number."}
      </div>
    );
  }
  // RECOMMENDED IS QUANTITY-AWARE (owner 2026-07-26). It used to compare `breaks[0].price` - the
  // qty-1 price - so the badge ignored quantity entirely and could name a vendor that is the most
  // expensive at the amount you actually need. `recommendVendor` costs the whole order and prefers a
  // vendor that can supply it; see lib/sourcingOrder.
  const recommended = orderable.length > 1 ? recommendVendor(orderable, needQty) : null;
  return (
    <div data-dev-id="detail.sourcing" className="flex flex-col">
      {/* THE QUANTITY BOX IS GONE (owner, 2026-07-26: "the need box in the library should be
          removed"). The quantity-AWARE logic stays exactly as it was - `recommendVendor` and
          `extendedPrice` still decide Recommended by what an order actually costs, at `needQty`,
          which is now simply always 1. Only the visible control was removed, so nothing about the
          pricing maths regressed and re-introducing an input elsewhere (a project BOM quantity, say)
          is a matter of feeding this same number from another source. */}
      {orderable.map((p, i) => {
        const breaks = normalizePriceBreaks(p.price_breaks);
        // The tier IN FORCE at the needed quantity, not the qty-1 tier: the headline price now answers
        // "what does it cost me", which is the question the quantity box asks.
        const unit = breakForQuantity(breaks, needQty) ?? breaks[0] ?? null;
        // the in-force qty goes in so the ladder can never hide the tier the headline names
        const tiers = ladderRows(breaks, unit?.qty);
        const isBest = recommended === p;
        const short = p.stock != null && p.stock < needQty;
        const orderTotal = extendedPrice(breaks, needQty);
        const name = vendorLabel(p.vendor, p.url);
        return (
          <div
            key={`${p.vendor}-${i}`}
            // A CARD per distributor (owner: "give the sourcing cards a different style than current").
            // Was a bare row on a hairline, with four data types on one line and no headers - a fault
            // the screen critique logged. The recommended one is bordered in the ok tint so the badge
            // is not the only thing carrying that state.
            className={
              "mb-1.5 rounded-card border px-2.5 py-2 transition-colors last:mb-0 " +
              (isBest ? "border-ok/50 bg-ok/[0.05]" : "border-line bg-surface hover:bg-raise2")
            }
          >
            {/* TWO LINES, not one. Seven things want this row - vendor, Recommended, stock, the volume
                the price belongs to, the unit price, the order total and the link - and they do not fit
                in 300px. Three attempts at cramming them proved it: the badge first collided with the
                stock figure, then printed ON TOP of it, then clipped to "Recor" and took the vendor name
                with it. The original screen critique had already called "four data types on one line
                with no headers" a fault, so the fix is the structural one rather than a fourth nudge.
                Line 1 is WHO (and whether it is recommended), line 2 is the commercial answer. */}
            <div className="flex min-w-0 items-center gap-2">
              <span className="min-w-0 truncate text-xs font-semibold text-t1">{name}</span>
              {isBest ? (
                <span
                  className="flex-none rounded-control px-1.5 py-0.5 text-2xs font-bold"
                  style={{
                    color: "var(--c-ok)",
                    background: "color-mix(in srgb, var(--c-ok) 16%, transparent)",
                  }}
                >
                  Recommended
                </span>
              ) : null}
            </div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="tnum whitespace-nowrap font-mono text-xs text-t2">
                {p.stock != null ? (
                  <>
                    <span
                      className="mr-1.5 inline-block h-[5px] w-[5px] rounded-full align-middle"
                      style={{ background: short ? "var(--c-warn)" : "var(--c-ok)" }}
                    />
                    <span className={short ? "text-warn" : undefined}>
                      {p.stock.toLocaleString()}
                    </span>
                  </>
                ) : null}
                {unit ? (
                  <span className="ml-2 text-2xs text-t3">at {unit.qty.toLocaleString()}+</span>
                ) : null}
              </span>
              <span className="ml-auto flex items-baseline gap-2.5">
                {unit ? (
                  <span className="flex flex-col items-end">
                    <span className="tnum font-mono text-sm font-semibold leading-none text-t1">
                      {formatPrice(unit.price, p.currency)}
                    </span>
                    {needQty > 1 && orderTotal != null ? (
                      <span className="tnum mt-0.5 font-mono text-2xs text-t3">
                        {formatPrice(orderTotal, p.currency)} total
                      </span>
                    ) : null}
                  </span>
                ) : null}
                <a
                  href={p.url}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={`Open on ${name}`}
                  className="flex-none text-t3 transition-colors hover:text-t1"
                >
                  <ExternalIcon />
                </a>
              </span>
            </div>
            {/* THE VENDOR PART NUMBER, on its own full-width line under the grid. It lived in the grid's
                first column, which is sized for a vendor NAME - truncated there it read
                "595-TPD6E05U06R..." and could not be checked against a vendor page or pasted into a
                cart, and `break-all` in a ~90px column shattered it into five lines. Neither is a
                font-size problem: a 14-character part number simply does not belong in that column,
                and the card is 300px wide. */}
            {p.part_number ? (
              <div className="tnum mt-1 truncate font-mono text-2xs text-t3" title={p.part_number}>
                {p.part_number}
              </div>
            ) : null}
            {/* A vendor with a part number but NO price and NO stock renders as a bare line with
                two empty columns, which reads as a broken row rather than as missing data. A real
                zero-stock answer arrives as `stock: 0` and takes the branch above, dot and all. */}
            {p.stock == null && !unit ? (
              <div data-dev-id="detail.sourcing-nodata" className="mt-1 text-2xs text-t3">
                <Text id="detail.sourcing-nodata">
                  No price or stock pulled from this distributor yet.
                </Text>
              </div>
            ) : null}
            {tiers.length > 0 ? (
              <div className="mt-3">
                <VendorLadder tiers={tiers} currency={p.currency} />
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
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
  // Sub-cent unit prices are common on passives at volume; two decimals collapse them
  // to "$0.00", which reads as free/broken. Show real precision (trim trailing zeros)
  // so a fraction of a cent reads as an actual price.
  const body =
    value > 0 && value < 0.01
      ? value.toFixed(4).replace(/0+$/, "")
      : value.toFixed(2);
  return `${symbol}${body}${suffix}`;
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
