/**
 * The part detail view, laid out as a bench workstation rather than a stack of cards.
 *
 * A fixed LEFT rail is the specimen card: the one identity (a derived headline + the MPN
 * serial + manufacturer, all editable in place), the 3D object as the hero with its symbol
 * and footprint as supporting embodiments, and a single readiness read (KiCad / Altium, what
 * each still needs) with the one Complete Part action. The RIGHT workbench is a tabbed panel
 * (Specs / Sourcing / Pinout / Enrich / History) so the reference depth lives in one panel
 * height and never pushes the page into a long scroll. A slim footer carries the filing
 * (category) control and the quiet Delete.
 *
 * Identity is stated exactly once (the old Overview card is gone), assets read as one strip
 * instead of a tall rail, and the spec sheet no longer dominates the page. Everything degrades
 * honestly when a field is absent, and no data is fabricated.
 */
import { useState, type HTMLAttributes, type ReactNode } from "react";
import type { PartDetail, PurchaseRef, SourcedField } from "../api/types";
import { deriveTitle, isReferenceOnlySpecKey } from "../lib/derive";
import { groupSpecs, type SpecGroup } from "../lib/specSchema";
import { assetReadiness, type AssetReadiness } from "../lib/edaTarget";
import { useInlineEdit } from "../lib/useInlineEdit";
import { Text } from "../lib/copy";
import { EditableText } from "./EditableText";
import { Icon } from "./Icon";
import { EnrichPanel } from "./EnrichPanel";
import { PinoutViewer, parsePinout } from "./PinoutViewer";
import { PartTimeline } from "./PartTimeline";
import { ConfirmDialog } from "./ConfirmDialog";
import { PreviewImage } from "./PreviewImage";
import { Glb3DView } from "./Glb3DView";
import { useCadSourceQuery, usePreviewGlb } from "../api/queries";
import { PreviewModal, type PreviewKind } from "./PreviewModal";
import { CompletePartModal } from "./CompletePartModal";
import {
  CubeArt,
  ExternalIcon,
  FootprintArt,
  SymbolArt,
  UploadIcon,
  WarnIcon,
} from "./icons";
import {
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

type WorkbenchTab = "specs" | "sourcing" | "pinout" | "enrich" | "history";

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
  // The one Complete-Part window (adds every missing file + data field in one place) - open flag.
  const [completeOpen, setCompleteOpen] = useState(false);
  // Which workbench tab is showing. It resets to Specs whenever the active id falls out
  // of the available set (a part switch that drops the Pinout / Enrich tab).
  const [tab, setTab] = useState<WorkbenchTab>("specs");
  // A passive owns no 3D-model file: it inherits the KiCad stock footprint's built-in model
  // (the model.glb endpoint resolves it from the footprint). So "has a 3D model" for a passive
  // is "has a footprint", not "has an owned model.file" (which the passive add correctly leaves
  // null). Without this a passive read "Not Linked" though its 3D rendered during add (A8).
  const hasModel = detail?.passive ? !!detail.footprint?.name : !!detail?.model?.file;
  // Inline 3D render (C1/C2): fetch + render the GLB right in the hero, auto-rotating and
  // pointer-events-none so it never fights the tile's own click. Enabled only for a part that
  // actually has a model, so a model-less part pays nothing.
  const modelGlb = usePreviewGlb(detail?.id ?? "", hasModel);
  // The part's capture needs (KiCad + Altium). Altium presence is not on the detail
  // record, so this is how the panel knows to offer Complete Part for a part that is
  // KiCad-complete but still missing its Altium assets (the common case). Cached under
  // the same key the Complete Part window uses, so it is fetched once and shared.
  const cadSource = useCadSourceQuery(detail?.id ?? null, true);
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

  // What the part still needs, files + data, for the one Complete-Part window and its trigger.
  const missingAssets = [
    !detail.symbol?.name ? "symbol" : null,
    !detail.footprint?.name ? "footprint" : null,
    !hasModel ? "3D model" : null,
  ].filter((x): x is string => x !== null);
  // Altium gaps come from the capture-needs query (not on the detail record), so an
  // Altium-only-missing part still offers Complete Part.
  const altiumNeeds = (cadSource.data?.needs ?? [])
    .filter((n) => n === "altium_symbol" || n === "altium_footprint")
    .map((n) => (n === "altium_symbol" ? "Altium symbol" : "Altium footprint"));
  const needsList = [...missing, ...missingAssets, ...altiumNeeds];
  // The panel is completable when it can edit a field OR attach an asset (a read-only panel gets
  // no Complete Part affordance, only the honest "Not linked" state on the tiles).
  const canComplete = !!(onEditField || onAttachSymbol || onAttachFootprint);

  const derived = deriveTitle(detail);
  const name = detail.display_name.trim();
  // The headline is the best HUMAN name: a passive gets its derived spec title
  // ("0.1 µF X7R Capacitor"); an opaque part whose title fell back to the MPN shows its
  // display name instead when that carries something the MPN does not, so the MPN never
  // headlines AND reads again on the serial line below.
  const titleIsMpn = derived === detail.mpn.trim();
  const headline = titleIsMpn && name && name !== detail.mpn.trim() ? name : derived;
  // Grouped, extensible spec sheet (Electrical / Physical / Ratings / Other) from lib/specSchema,
  // with catalog metadata (manufacturer, country, packaging, ...) dropped so the sheet is the
  // physical parameters, not a distributor page. Groups emptied by the filter fall away.
  const specGroups = groupSpecs(detail.category, detail.specs)
    .map((group) => ({
      ...group,
      rows: group.rows.filter((row) => !isReferenceOnlySpecKey(row.key)),
    }))
    .filter((group) => group.rows.length > 0);
  // The persisted pinout (M6i) reads from the record's specs, its provenance from
  // the enrichment map. Shown when present, in both read-only and editable modes.
  const pinout = parsePinout(detail.specs);
  const pinoutProvenance = detail.enrichment?.pinout;

  const kicad = assetReadiness(detail, "kicad");
  const altium = assetReadiness(detail, "altium");

  // The workbench tabs: Specs and Sourcing always; Pinout only when the record carries one;
  // Enrich only in editable mode with an MPN to look up by; History always. The active tab
  // falls back to Specs when the current id is not in the set (a part switch).
  const hasEnrich = !!onEditField && !!detail.mpn;
  const tabs: TabItem<WorkbenchTab>[] = [
    { id: "specs", label: "Details" },
    ...(pinout.length > 0 ? [{ id: "pinout" as const, label: "Pinout" }] : []),
    ...(hasEnrich ? [{ id: "enrich" as const, label: "Enrich" }] : []),
    { id: "history", label: "History" },
  ];
  const activeTab = tabs.some((t) => t.id === tab) ? tab : "specs";

  return (
    <div data-dev-id="detail.root" className="flex h-full min-h-0 flex-col">
      {/* the opened component reads as a docked Altium panel: a title-strip band (the part name +
          its category), the SAME band + hairline as the Components list header and the rail header,
          so the three panes read as one workspace. Then the padded body. */}
      <div
        data-dev-id="detail.title-strip"
        className="flex h-[34px] flex-none items-center gap-3 border-b border-line bg-band px-6"
      >
        <TitleBlock
          headline={headline}
          name={detail.display_name}
          onRename={onEditField ? (v) => onEditField("display_name", v) : undefined}
          busy={busy}
        />
        <span className="ml-auto flex-none truncate text-2xs font-semibold uppercase tracking-[0.07em] text-t3">
          {detail.category}
        </span>
      </div>
      <div className="flex min-h-0 flex-1 flex-col px-6 pb-3 pt-3">
        {/* sub-header: the part number + maker lead on the left, the view tabs on the right, on
            one bordered band - the sheet gets a real head instead of a flat wall of sections. */}
        <div
          data-dev-id="detail.identity"
          className="flex flex-none items-center justify-between gap-4 border-b border-line pb-2.5"
        >
          <IdentityLine
            mpn={detail.mpn}
            manufacturer={detail.manufacturer}
            onEditMpn={onEditField ? (v) => onEditField("mpn", v) : undefined}
            onEditManufacturer={
              onEditField ? (v) => onEditField("manufacturer", v) : undefined
            }
            busy={busy}
          />
          <TabStrip
            tabs={tabs}
            active={activeTab}
            onSelect={setTab}
            idBase="workbench"
            devIdBase="detail"
            aria-label="Part views"
          />
        </div>

        {/* The default view is a three-pane sheet, bordered like docked panels: the PART (its
            embodiments + CAD readiness), the SPECIFICATIONS (one clean column), and the COMMERCIAL
            + reference pane. Sized to fit the window with no scrolling. */}
        <WorkbenchPanel
          id="specs"
          active={activeTab}
          className="mt-3 grid min-h-0 flex-1 grid-cols-[288px_minmax(0,1fr)_320px]"
        >
          <div className="flex min-h-0 flex-col gap-4 overflow-y-auto pr-5">
          {/* the physical object as the hero, its symbol + footprint as supporting embodiments */}
          <div data-dev-id="detail.canvas" className="flex flex-col gap-2.5">
            <AssetTile
              devId="detail.asset-hero"
              stageDevId="detail.asset-stage"
              variant="hero"
              name="3D Model"
              present={hasModel}
              className="h-[300px]"
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
            <div className="grid grid-cols-2 gap-2.5">
              <AssetTile
                devId="detail.asset-symbol"
                variant="tile"
                name="Symbol"
                present={!!detail.symbol?.name}
                className="h-[142px]"
                art={<SymbolArt />}
                thumb={
                  detail.symbol?.name ? (
                    <PreviewImage kind="symbol" partId={detail.id} fallback={<SymbolArt />} />
                  ) : undefined
                }
                onOpen={detail.symbol?.name ? () => setPreview("symbol") : undefined}
              />
              <AssetTile
                devId="detail.asset-footprint"
                variant="tile"
                name="Footprint"
                present={!!detail.footprint?.name}
                className="h-[142px]"
                art={<FootprintArt />}
                thumb={
                  detail.footprint?.name ? (
                    <PreviewImage kind="footprint" partId={detail.id} fallback={<FootprintArt />} />
                  ) : undefined
                }
                onOpen={detail.footprint?.name ? () => setPreview("footprint") : undefined}
              />
            </div>
          </div>

          <ReadinessBlock
            kicad={kicad}
            altium={altium}
            altiumNeeds={altiumNeeds}
            canComplete={canComplete}
            needsList={needsList}
            onComplete={() => setCompleteOpen(true)}
          />
          {/* filing (category) moved off the footer into the part pane, as one more labelled,
              editable field that matches the rest - and it fills the pane so there is less dead space. */}
          <Filing
            category={detail.category}
            categories={categories}
            onMoveCategory={onMoveCategory}
            busy={busy}
          />
          </div>

          {/* COLUMN 2 - the specifications, the technical heart, in one clean single column. */}
          <div className="flex min-h-0 flex-col overflow-y-auto border-l border-line px-5">
            <DetailSection title={<Text id="detail.specifications">Specifications</Text>}>
              <SpecificationsSection groups={specGroups} />
            </DetailSection>
          </div>

          {/* COLUMN 3 - commercial + reference: where to buy, then the datasheet + a note. */}
          <div className="flex min-h-0 flex-col gap-5 overflow-y-auto border-l border-line pl-5">
            <DetailSection title={<Text id="detail.sourcing-head">Sourcing</Text>}>
              <Sourcing purchase={detail.purchase} hasMpn={!!detail.mpn} />
            </DetailSection>
            <RailReference
              datasheetUrl={detail.datasheet?.source_url || detail.datasheet?.file || ""}
              datasheetHref={detail.datasheet?.source_url || undefined}
              description={detail.description}
              onEditDatasheet={onEditField ? (v) => onEditField("datasheet", v) : undefined}
              onEditDescription={onEditField ? (v) => onEditField("description", v) : undefined}
              busy={busy}
            />
          </div>
        </WorkbenchPanel>

        {pinout.length > 0 ? (
          <WorkbenchPanel
            id="pinout"
            devId="detail.pinout"
            active={activeTab}
            className="mt-3 min-h-0 flex-1 overflow-y-auto"
          >
            <PinoutViewer
              key={detail.id}
              pins={pinout}
              source={pinoutProvenance?.source}
              confidence={pinoutProvenance?.confidence}
            />
          </WorkbenchPanel>
        ) : null}

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
              category={detail.category}
              current={{
                manufacturer: detail.manufacturer,
                description: detail.description,
              }}
              onApply={onEditField!}
              onApplyPinout={onApplyPinout}
              hasPinout={pinout.length > 0}
              busy={busy}
            />
          </WorkbenchPanel>
        ) : null}

        <WorkbenchPanel
          id="history"
          devId="detail.history"
          active={activeTab}
          className="mt-3 min-h-0 flex-1 overflow-y-auto"
        >
          <PartTimeline key={detail.id} partId={detail.id} />
        </WorkbenchPanel>

      {/* footer: filing moved into the part pane; a destructive action never earns prime real
          estate, so Delete stays as the quiet text link at the far edge. */}
      <footer data-dev-id="detail.footer" className="mt-3 flex flex-none items-center justify-end border-t border-line pt-2.5">
        {onDelete ? (
          <button
            data-dev-id="detail.delete"
            type="button"
            onClick={() => setConfirmDelete(true)}
            disabled={busy}
            className="text-xs text-t3 transition-colors hover:text-err disabled:opacity-50"
          >
            <Text id="detail.delete">Delete Part</Text>
          </button>
        ) : null}
      </footer>
      </div>

      {/* The one Complete-Part window: every missing file (symbol / footprint / 3D model) and
          data field (datasheet, MPN, ...) is added here, replacing the per-tile attach buttons
          and the standalone DigiKey card. Mounted only while open so its inputs start fresh. */}
      {completeOpen ? (
        <CompletePartModal
          detail={detail}
          hasModel={hasModel}
          busy={busy}
          onClose={() => setCompleteOpen(false)}
          onAttachSymbol={onAttachSymbol}
          onAttachFootprint={onAttachFootprint}
          onEditField={onEditField}
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

// One workbench tab panel. Every panel stays mounted (so its data is fetched once and a tab
// switch is instant); the inactive ones carry the `hidden` attribute, the WAI-ARIA tabs
// pattern, so only the active panel is shown and read out.
function WorkbenchPanel({
  id,
  active,
  devId,
  className,
  children,
}: {
  id: WorkbenchTab;
  active: WorkbenchTab;
  // When set, the panel carries a stable `data-dev-id` for the dev-mode inspector
  // (the panels whose region is not already named by an inner component's id).
  devId?: string;
  className?: string;
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
        className="w-[280px] max-w-full rounded-control border border-line2 bg-field px-2 py-0.5 text-base font-semibold tracking-[-0.01em] text-t1 outline-none focus:border-acc"
      />
    );
  }

  return (
    <div className="group flex min-w-0 items-center gap-1.5">
      <h1 data-dev-id="detail.title" className="min-w-0 truncate text-base font-semibold tracking-[-0.01em] text-t1">
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

// The identity serial line: a category dot, the MPN as the mono stamp (a part IS its part
// number, editable in place), then the manufacturer. Each piece drops out honestly when the
// record does not carry it, and stays editable so a mistyped MPN is a click to fix.
function IdentityLine({
  mpn,
  manufacturer,
  onEditMpn,
  onEditManufacturer,
  busy,
}: {
  mpn: string;
  manufacturer: string;
  onEditMpn?: (value: string) => void;
  onEditManufacturer?: (value: string) => void;
  busy?: boolean;
}) {
  return (
    <div data-dev-id="detail.identity-line" className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1">
      {onEditMpn ? (
        <EditableText
          value={mpn}
          onSave={onEditMpn}
          label="Part Number"
          placeholder="No Part Number"
          mono
          disabled={busy}
          displayClassName="text-sm"
        />
      ) : (
        <span className="tnum px-1.5 font-mono text-sm text-t1">
          {mpn || <span className="font-sans italic text-t3">No Part Number</span>}
        </span>
      )}
      <span className="text-t3" aria-hidden="true">
        ·
      </span>
      {onEditManufacturer ? (
        <EditableText
          value={manufacturer}
          onSave={onEditManufacturer}
          label="Manufacturer"
          placeholder="Add manufacturer"
          disabled={busy}
          displayClassName="text-sm"
        />
      ) : (
        <span className="px-1.5 text-sm text-t2">{manufacturer}</span>
      )}
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
      <div className="mb-1.5 flex h-4 items-center justify-between gap-2">
        <span className="text-2xs font-semibold uppercase tracking-[0.07em] text-t3">{title}</span>
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
function ReadinessBlock({
  kicad,
  altium,
  altiumNeeds,
  canComplete,
  needsList,
  onComplete,
}: {
  kicad: AssetReadiness;
  altium: AssetReadiness;
  altiumNeeds: string[];
  canComplete: boolean;
  needsList: string[];
  onComplete: () => void;
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
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 rounded-control border border-line bg-field px-3 py-2 text-left transition hover:bg-raise2"
      >
        <span className="flex items-center gap-2">
          {allReady ? (
            <Icon id="detail.ready-check" className="h-3.5 w-3.5 flex-none" />
          ) : (
            <WarnIcon className="h-3.5 w-3.5 flex-none text-warn" />
          )}
          <span className="text-xs font-semibold text-t1">
            {allReady ? "CAD complete" : "CAD incomplete"}
          </span>
        </span>
        <Icon
          id="detail.chevron-right"
          className={
            "h-3.5 w-3.5 flex-none text-t3 transition-transform " + (open ? "rotate-90" : "")
          }
        />
      </button>
      {open ? (
        <div className="absolute inset-x-0 top-[calc(100%+6px)] z-[70] rounded-card border border-line2 bg-popover p-3 shadow-pop">
          <ReadinessRow label="KiCad" ready={kicad.ready} needs={kicadNeeds} />
          <ReadinessRow label="Altium" ready={altium.ready} needs={altiumBlocking} />
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
        </div>
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

// The outbound links + free-form notes, as the foot of the identity rail. "Links" gathers the
// datasheet and the vendor product page into one obvious place (the owner asked for a clear home
// for links); both the datasheet and the note stay editable so a part is completed here. All
// microcopy avoids the lowercase letter y (owner rule).
function RailReference({
  datasheetUrl,
  datasheetHref,
  description,
  onEditDatasheet,
  onEditDescription,
  busy,
}: {
  datasheetUrl: string;
  datasheetHref?: string;
  description: string;
  onEditDatasheet?: (value: string) => void;
  onEditDescription?: (value: string) => void;
  busy?: boolean;
}) {
  return (
    <div data-dev-id="detail.reference" className="flex flex-col gap-4">
      <DetailSection title={<Text id="detail.links">Links</Text>} data-dev-id="detail.datasheet-row">
        <div className="flex items-baseline gap-2">
          <span className="w-[64px] flex-none text-xs text-t2">
            <Text id="detail.datasheet">Datasheet</Text>
          </span>
          <span className="flex min-w-0 flex-1 items-center gap-1">
            {onEditDatasheet ? (
              <EditableText
                value={datasheetUrl}
                onSave={onEditDatasheet}
                label="Datasheet"
                placeholder="Paste a datasheet link"
                mono
                truncate
                disabled={busy}
                displayClassName="text-xs"
              />
            ) : datasheetHref ? (
              <a
                href={datasheetHref}
                target="_blank"
                rel="noreferrer"
                className="inline-flex min-w-0 items-center gap-1 truncate text-xs text-acc hover:underline"
              >
                <span className="truncate">Open datasheet</span>
                <ExternalIcon className="flex-none" />
              </a>
            ) : datasheetUrl ? (
              <span className="tnum truncate font-mono text-xs text-t1">{datasheetUrl}</span>
            ) : (
              <span className="text-xs italic text-t3">None on file</span>
            )}
            {onEditDatasheet && datasheetHref ? (
              <a
                href={datasheetHref}
                target="_blank"
                rel="noreferrer"
                aria-label="Open datasheet"
                className="flex-none text-t3 transition-colors hover:text-t1"
              >
                <ExternalIcon />
              </a>
            ) : null}
          </span>
        </div>
      </DetailSection>
      <DetailSection title={<Text id="detail.notes">Description</Text>} data-dev-id="detail.notes-row">
        {onEditDescription ? (
          <EditableText
            value={description}
            onSave={onEditDescription}
            label="Description"
            placeholder="Add a description"
            multiline
            clampLines={3}
            disabled={busy}
            displayClassName="text-xs"
          />
        ) : description ? (
          <span className="text-xs text-t2">{description}</span>
        ) : (
          <span className="text-xs italic text-t3">None</span>
        )}
      </DetailSection>
    </div>
  );
}

// The filing (category) control: moving a part between category libraries is organization,
// not identity, so it sits in the footer as a quiet inline select, not in the masthead.
function Filing({
  category,
  categories,
  onMoveCategory,
  busy,
}: {
  category: string;
  categories?: string[];
  onMoveCategory?: (category: string) => void;
  busy?: boolean;
}) {
  // Filing is now a labelled section field like every other, and editable (a category dropdown)
  // when moves are allowed - so it matches the rest instead of sitting oddly in the footer.
  return (
    <DetailSection title={<Text id="detail.filing">Filing</Text>} data-dev-id="detail.filing">
      {onMoveCategory && categories && categories.length > 0 ? (
        <div className="relative">
          <select
            aria-label="Category"
            value={category}
            disabled={busy}
            onChange={(e) => {
              if (e.target.value !== category) onMoveCategory(e.target.value);
            }}
            className="w-full appearance-none rounded-control border border-line bg-field py-1.5 pl-2.5 pr-7 text-xs font-medium text-t1 outline-none hover:border-line2 focus:border-acc disabled:cursor-not-allowed disabled:opacity-50"
          >
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <Icon
            id="detail.select-chevron"
            className="pointer-events-none absolute right-2 top-1/2 h-3 w-3 -translate-y-1/2 text-t3"
          />
        </div>
      ) : (
        <span className="text-xs text-t2">{category}</span>
      )}
    </DetailSection>
  );
}


// One Part Canvas tile. `hero` is the big physical (3D) stage; `tile` is a compact
// embodiment (symbol / footprint). Present -> the whole tile is a button that expands
// the preview; missing-with-handler -> a button that opens the Attach modal; missing
// read-only -> the honest Not Linked state. The recessed `stage` chamber makes a render
// read as a lit object, not a flat image.
function AssetTile({
  name,
  present,
  art,
  thumb,
  onOpen,
  onAttach,
  variant,
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
  // When present and set, the whole tile is a button that expands the preview.
  onOpen?: () => void;
  // When the asset is MISSING and set, the whole tile is a button that opens the
  // Attach modal. Ignored when the asset is present.
  onAttach?: () => void;
  variant: "hero" | "tile";
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
    </div>
  );
  const footer = (
    <div className="flex items-center gap-2 px-3 py-2">
      <span className="text-2xs font-semibold text-t1">{name}</span>
      <span className="ml-auto inline-flex items-center gap-1.5 text-2xs text-t3">
        {present ? (
          // no green "present" dot (owner's call - the render itself already reads as present)
          <>{onOpen ? "View" : "Linked"}</>
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
    "flex min-h-0 min-w-0 flex-col overflow-hidden rounded-card border border-line bg-raise " +
    (className ?? "");
  const buttonCls =
    base +
    " cursor-pointer text-left transition-colors hover:border-line2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc";
  if (onOpen && present) {
    return (
      <button
        data-dev-id={devId}
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
        data-dev-id={devId}
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
function SpecificationsSection({ groups }: { groups: SpecGroup[] }) {
  if (groups.length === 0) {
    return (
      <div data-dev-id="detail.specs" className="text-sm text-t3">No parametric specs on record for this part.</div>
    );
  }
  // One clean column inside its own pane (the middle of the three-pane sheet). Groups stack in a
  // consistent rhythm; the pane owns its scroll, so however many rows a part carries, the page
  // never grows.
  return (
    <div data-dev-id="detail.specs" className="flex flex-col gap-3.5">
      {groups.map((group) => (
        <section key={group.title} data-dev-id="detail.spec-group">
          {/* Altium property-grid feel: the group name sits on a divider band, then clean rows with
              no per-row hairline (that ledger look is gone) - separation is the divider + a live
              row hover, and the value reads in the mono data face. */}
          <div className="mb-1 flex items-center gap-2 border-b border-line pb-1">
            <span className="text-2xs font-semibold uppercase tracking-[0.08em] text-t3">
              {group.title}
            </span>
          </div>
          <dl className="flex flex-col">
            {group.rows.map((row) => (
              <div
                key={row.key}
                className="-mx-1.5 flex items-baseline justify-between gap-3 rounded-[2px] px-1.5 py-[3px] transition-colors hover:bg-[var(--c-hover)]"
              >
                <dt
                  className="min-w-0 flex-1 truncate text-xs text-t2"
                  title={typeof row.label === "string" ? row.label : undefined}
                >
                  {row.label}
                </dt>
                <dd className="tnum flex-none truncate text-right font-mono text-xs text-t1">
                  {row.unit ? `${row.value} ${row.unit}` : row.value}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ))}
    </div>
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
      <div data-dev-id="detail.sourcing" className="text-sm text-t2">
        {hasMpn
          ? "No purchase link on record yet."
          : "Not orderable yet, this component has no part number."}
      </div>
    );
  }
  // The cheapest unit price across the orderable distributors earns the "Best" tag (only
  // meaningful with more than one to compare).
  const units = orderable.map((p) => normalizePriceBreaks(p.price_breaks)[0]?.price ?? null);
  const cheapest = Math.min(...units.filter((v): v is number => v != null));
  return (
    <div data-dev-id="detail.sourcing" className="flex flex-col">
      {orderable.map((p, i) => {
        const breaks = normalizePriceBreaks(p.price_breaks);
        const unit = breaks[0] ?? null;
        const isBest = orderable.length > 1 && unit != null && unit.price === cheapest;
        const name = vendorLabel(p.vendor, p.url);
        return (
          <div key={`${p.vendor}-${i}`} className="border-b border-line py-[11px] last:border-0">
            <div className="grid grid-cols-[1fr_auto_auto] items-center gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-t1">{name}</span>
                {isBest ? (
                  <span
                    className="rounded-control px-1.5 py-0.5 text-2xs font-bold"
                    style={{
                      color: "var(--c-ok)",
                      background: "color-mix(in srgb, var(--c-ok) 16%, transparent)",
                    }}
                  >
                    Best
                  </span>
                ) : null}
              </div>
              {p.part_number ? (
                <div className="tnum mt-0.5 truncate font-mono text-2xs text-t3">
                  {p.part_number}
                </div>
              ) : null}
            </div>
            <div className="tnum whitespace-nowrap text-right font-mono text-xs text-t2">
              {p.stock != null ? (
                <>
                  <span
                    className="mr-1.5 inline-block h-[5px] w-[5px] rounded-full align-middle"
                    style={{ background: "var(--c-ok)" }}
                  />
                  {p.stock.toLocaleString()}
                </>
              ) : null}
            </div>
            <div className="flex items-center justify-end gap-2.5">
              {unit ? (
                <span className="tnum font-mono text-base font-semibold text-t1">
                  {formatPrice(unit.price, p.currency)}
                </span>
              ) : null}
              <a
                href={p.url}
                target="_blank"
                rel="noreferrer"
                aria-label={`Open on ${name}`}
                className="text-t3 transition-colors hover:text-t1"
              >
                <ExternalIcon />
              </a>
            </div>
            </div>
            {breaks.length > 1 ? (
              <div className="mt-3">
                <div className="mb-2 text-2xs font-semibold uppercase tracking-[0.05em] text-t3">
                  Volume Pricing
                </div>
                {/* the qty-1 unit price is already shown next to the stock above, so the ladder
                    starts at the FIRST bulk tier (10+, 100+, ...) - no redundant "1+" row */}
                <div
                  className="grid grid-flow-col gap-x-10"
                  style={{
                    gridTemplateRows: `repeat(${Math.ceil((breaks.length - 1) / 2)}, auto)`,
                  }}
                >
                  {breaks.slice(1).map((b) => (
                    <div
                      key={b.qty}
                      className="tnum flex items-baseline justify-between py-[3.5px] font-mono text-xs"
                    >
                      <span className="text-t3">{b.qty}+</span>
                      <span className="font-semibold text-t1">
                        {formatPrice(b.price, p.currency)}
                      </span>
                    </div>
                  ))}
                </div>
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
  return `${symbol}${value.toFixed(2)}${suffix}`;
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
