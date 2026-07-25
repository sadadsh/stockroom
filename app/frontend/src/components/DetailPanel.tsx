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
import { useEffect, useState, type HTMLAttributes, type ReactNode } from "react";
import type {
  PartDetail,
  PurchaseRef,
  SourcedAlternate,
  SourcedField,
} from "../api/types";
import { deriveTitle, isReferenceOnlySpecKey } from "../lib/derive";
import { useCapture } from "../lib/capture";
import {
  groupSpecs,
  TRADE_GROUP,
  type SpecGroup,
  type SpecRow,
} from "../lib/specSchema";
import { ladderRows, orderPurchases } from "../lib/sourcingOrder";
import { distributorLabel } from "../lib/sourced";
import {
  assetReadiness,
  assetsFor,
  assetTitleLabel,
  type AssetReadiness,
} from "../lib/edaTarget";
import { EDA_TOOLS } from "../lib/edaRegistry.generated";
import { useInlineEdit } from "../lib/useInlineEdit";
import { Text } from "../lib/copy";
import { EditableText } from "./EditableText";
import { Icon } from "./Icon";
import { EnrichPanel } from "./EnrichPanel";
import { PinoutViewer, parsePinout } from "./PinoutViewer";
import { PartTimeline } from "./PartTimeline";
import { ConfirmDialog } from "./ConfirmDialog";
import { PreviewImage } from "./PreviewImage";
import { PhotoTrigger, productPhotoUrl } from "./ProductPhoto";
import { Glb3DView } from "./Glb3DView";
import {
  useAltiumEmbedCapability,
  useAltiumEmbedModel,
  useCadSourceQuery,
  useDetachAsset,
  usePreviewGlb,
  useRefreshSourcing,
} from "../api/queries";
import { useToast } from "../lib/toast";
import { PreviewModal, type PreviewKind } from "./PreviewModal";
import { CompletePartModal } from "./CompletePartModal";
import {
  CubeArt,
  ExternalIcon,
  FootprintArt,
  RefreshIcon,
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
  onAttachSymbol,
  onAttachFootprint,
  onUseSpecValue,
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
  // A passive owns no 3D-model file: it inherits the KiCad stock footprint's built-in model
  // (the model.glb endpoint resolves it from the footprint). So "has a 3D model" for a passive
  // is "has a footprint", not "has an owned model.file" (which the passive add correctly leaves
  // null). Without this a passive read "Not Linked" though its 3D rendered during add (A8).
  const kicadAssets = detail ? assetsFor(detail, "kicad") : null;
  const hasModel = detail?.passive
    ? !!kicadAssets?.footprint?.name
    : !!kicadAssets?.model?.file;
  // The pulled product photo (specs["Image"]): hidden behind a click-to-view chip
  // (owner 2026-07-24: "hidden until someone clicks to view it and like a card opens").
  const heroPhotoUrl = productPhotoUrl(detail?.specs);
  // Inline 3D render (C1/C2): fetch + render the GLB right in the hero, auto-rotating and
  // pointer-events-none so it never fights the tile's own click. Enabled only for a part that
  // actually has a model, so a model-less part pays nothing.
  const modelGlb = usePreviewGlb(detail?.id ?? "", hasModel);
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
  const altiumFootprint = assetsFor(detail, "altium").footprint;
  const embed3d: Embed3dState | null =
    "model" in altium.embedded && !detail.passive
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
  const missingAssets = [
    !kicadAssets?.symbol?.name ? "symbol" : null,
    !kicadAssets?.footprint?.name ? "footprint" : null,
    !hasModel ? "3D model" : null,
  ].filter((x): x is string => x !== null);
  // Altium gaps read straight off the part RECORD (altium.missing from assetReadiness), so an
  // attach updates them on the ["part", id] refresh - never a stale cad-source needs list.
  const altiumNeeds = altium.missing
    .filter((m) => m === "Symbol" || m === "Footprint")
    .map((m) => `Altium ${m}`);
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
  const allSpecGroups = groupSpecs(detail.category, detail.specs);
  const specGroups = allSpecGroups
    .filter((group) => group.title !== TRADE_GROUP)
    .map((group) => ({
      ...group,
      rows: group.rows.filter((row) => !isReferenceOnlySpecKey(row.key)),
    }))
    .filter((group) => group.rows.length > 0);
  // The procurement facts (origin, the page's own tariff rate, export classification, order
  // quantities) go to SOURCING, not here. They are real vendor data the owner asked to stop
  // losing, but they are not physical parameters - and this is the one place the reference-only
  // filter must NOT run, because reference data is exactly what the block is for.
  const tradeGroup = allSpecGroups.find((group) => group.title === TRADE_GROUP) ?? null;
  // The persisted pinout (M6i) reads from the record's specs, its provenance from
  // the enrichment map. Shown when present, in both read-only and editable modes.
  const pinout = parsePinout(detail.specs);
  const pinoutProvenance = detail.enrichment?.pinout;

  // The workbench tabs: Specs and Sourcing always; Pinout only when the record carries one;
  // Enrich only in editable mode with an MPN to look up by; History always. The active tab
  // falls back to Specs when the current id is not in the set (a part switch).
  const hasEnrich = !!onEditField && !!detail.mpn;
  const tabs: TabItem<WorkbenchTab>[] = [
    { id: "specs", label: "Details" },
    ...(pinout.length > 0 ? [{ id: "pinout" as const, label: "Pinout" }] : []),
    ...(hasEnrich ? [{ id: "enrich" as const, label: "Enrich" }] : []),
    // Labelled Timeline (the component IS PartTimeline) - "History" broke the no-y copy rule.
    { id: "history", label: "Timeline" },
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
          <PhotoTrigger
            devId="detail.photo"
            url={heroPhotoUrl}
            partName={detail.display_name}
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
          // grid-rows-[minmax(0,1fr)]: without it the single implicit row sizes to its tallest
          // column, so a long specs list grew the whole sheet instead of scrolling inside its
          // own pane. Pinning the row to the container height lets each column's own
          // overflow-y-auto engage.
          className="mt-3 grid min-h-0 flex-1 grid-cols-[288px_minmax(0,1fr)_320px] grid-rows-[minmax(0,1fr)]"
        >
          <div className="flex min-h-0 flex-col gap-4 overflow-y-auto pr-5">
          {/* the physical object as the hero, its symbol + footprint as supporting embodiments.
              flex-1 (no min-h-0): the canvas absorbs the pane's slack so the hero grows to fill
              the column beside a tall specs pane, and still scrolls when content genuinely
              overflows (min-height:auto keeps it from compressing below its content). */}
          <div data-dev-id="detail.canvas" className="flex flex-1 flex-col gap-2.5">
            <AssetTile
              devId="detail.asset-hero"
              stageDevId="detail.asset-stage"
              name="3D Model"
              present={hasModel}
              className="min-h-[300px] flex-1"
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
                name="Symbol"
                present={!!kicadAssets?.symbol?.name}
                className="h-[142px]"
                art={<SymbolArt />}
                thumb={
                  kicadAssets?.symbol?.name ? (
                    <PreviewImage kind="symbol" partId={detail.id} fallback={<SymbolArt />} />
                  ) : undefined
                }
                onOpen={kicadAssets?.symbol?.name ? () => setPreview("symbol") : undefined}
              />
              <AssetTile
                devId="detail.asset-footprint"
                name="Footprint"
                present={!!kicadAssets?.footprint?.name}
                className="h-[142px]"
                art={<FootprintArt />}
                thumb={
                  kicadAssets?.footprint?.name ? (
                    <PreviewImage kind="footprint" partId={detail.id} fallback={<FootprintArt />} />
                  ) : undefined
                }
                onOpen={kicadAssets?.footprint?.name ? () => setPreview("footprint") : undefined}
              />
            </div>
          </div>

          {/* the CAD status + Filing as ONE tight cluster of matching property rows */}
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
                // a passive references KiCad STOCK assets by id (no owned files);
                // element removal applies to owned files only
                onEditField && !detail.passive
                  ? ([
                      // Every tool's attached assets, from the registry: a third EDA tool
                      // becomes removable by being registered, with no edit here. `kind` is
                      // the `<tool>_<asset kind>` vocabulary LibraryOps.detach_asset speaks.
                      ...EDA_TOOLS.flatMap((tool) =>
                        tool.assetKinds
                          .filter((k) => !(k in tool.unsupportedAssets))
                          .map((k) => {
                            const ref = assetsFor(detail, tool.key)[k as "symbol"];
                            if (!ref || !(ref.name || ref.file)) return null;
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
            <Filing
              category={detail.category}
              categories={categories}
              onMoveCategory={onMoveCategory}
              busy={busy}
            />
          </div>
          </div>

          {/* COLUMN 2 - the specifications, the technical heart, in one clean single column. */}
          <div className="flex min-h-0 flex-col overflow-y-auto border-l border-line px-5">
            <DetailSection title={<Text id="detail.specifications">Specifications</Text>}>
              <SpecificationsSection
                groups={specGroups}
                alternates={detail.alternates ?? {}}
                onUseSpecValue={onUseSpecValue}
              />
            </DetailSection>
          </div>

          {/* COLUMN 3 - commercial + reference: where to buy, then the datasheet + a note. */}
          <div className="flex min-h-0 flex-col gap-5 overflow-y-auto border-l border-line pl-5">
            <DetailSection
              title={<Text id="detail.sourcing-head">Sourcing</Text>}
              action={
                detail.mpn ? (
                  <button
                    type="button"
                    data-dev-id="detail.sourcing-refresh"
                    onClick={() => refreshJob.run()}
                    disabled={refreshStatus === "running"}
                    className="inline-flex items-center gap-1 rounded-control px-1 py-0.5 text-2xs font-semibold text-t3 transition-colors hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc disabled:pointer-events-none disabled:opacity-60"
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
                ) : undefined
              }
            >
              <Sourcing purchase={detail.purchase} hasMpn={!!detail.mpn} />
              {tradeGroup ? (
                <TradeCompliance
                  group={tradeGroup}
                  alternates={detail.alternates ?? {}}
                  onUseSpecValue={onUseSpecValue}
                />
              ) : null}
            </DetailSection>
            <RailReference
              datasheetUrl={detail.datasheet?.source_url || detail.datasheet?.file || ""}
              datasheetHref={detail.datasheet?.source_url || undefined}
              description={detail.description}
              descriptionAlternates={detail.alternates?.description ?? []}
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
          symbol: !!kicadAssets?.symbol?.name,
          footprint: !!kicadAssets?.footprint?.name,
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
      {/* Pane-level heading: Title Case, t1 - a clear step ABOVE the uppercase micro-eyebrows
          the spec groups use, so "Specifications" and "Electrical" never read as the same level. */}
      <div className="mb-2 flex h-5 items-center justify-between gap-2">
        <span className="text-sm font-semibold text-t1">{title}</span>
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
        className="flex h-[34px] w-full items-center gap-2.5 rounded-control border border-line bg-field px-3 text-left transition-colors hover:bg-raise2"
      >
        {allReady ? (
          <Icon id="detail.ready-check" className="h-3.5 w-3.5 flex-none" />
        ) : (
          <WarnIcon className="h-3.5 w-3.5 flex-none text-warn" />
        )}
        <span className="text-2xs font-semibold uppercase tracking-[0.07em] text-t3">CAD</span>
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
              <div className="mb-1.5 text-2xs font-semibold uppercase tracking-[0.07em] text-t3">
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

// The datasheet as a real BUTTON carrying a human label (owner's call - not a raw URL): it opens
// the datasheet in a new tab, with a quiet pencil that swaps in an inline field to paste a new
// link. Falls back to an honest "None on file" when there is no datasheet.
function DatasheetField({
  url,
  href,
  onEdit,
  busy,
}: {
  url: string;
  href?: string;
  onEdit?: (value: string) => void;
  busy?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(url);
  if (editing && onEdit) {
    return (
      <input
        autoFocus
        value={draft}
        disabled={busy}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          onEdit(draft.trim());
          setEditing(false);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            onEdit(draft.trim());
            setEditing(false);
          } else if (e.key === "Escape") {
            setDraft(url);
            setEditing(false);
          }
        }}
        placeholder="Paste a datasheet link"
        aria-label="Datasheet link"
        className="w-full rounded-control border border-line2 bg-field px-2.5 py-1.5 font-mono text-xs text-t1 outline-none focus:border-acc"
      />
    );
  }
  return (
    <div className="flex items-center gap-1.5">
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 rounded-control border border-line bg-field px-2.5 py-1.5 text-xs font-medium text-t1 transition hover:border-line2 hover:bg-raise2"
        >
          <Text id="detail.datasheet">Datasheet</Text>
          <ExternalIcon className="text-t3" />
        </a>
      ) : (
        <span className="text-xs italic text-t3">None on file</span>
      )}
      {onEdit ? (
        <button
          type="button"
          onClick={() => {
            setDraft(url);
            setEditing(true);
          }}
          disabled={busy}
          aria-label="Edit datasheet link"
          title="Edit datasheet link"
          className="grid h-6 w-6 flex-none place-items-center rounded-control text-t3 transition hover:bg-raise2 hover:text-t1 disabled:opacity-50"
        >
          <Icon id="detail.rename" className="h-3.5 w-3.5" />
        </button>
      ) : null}
    </div>
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
  descriptionAlternates,
  onEditDatasheet,
  onEditDescription,
  busy,
}: {
  datasheetUrl: string;
  datasheetHref?: string;
  description: string;
  descriptionAlternates: SourcedAlternate[];
  onEditDatasheet?: (value: string) => void;
  onEditDescription?: (value: string) => void;
  busy?: boolean;
}) {
  return (
    <div data-dev-id="detail.reference" className="flex flex-col gap-4">
      <DetailSection title={<Text id="detail.links">Links</Text>} data-dev-id="detail.datasheet-row">
        <DatasheetField
          url={datasheetUrl}
          href={datasheetHref}
          onEdit={onEditDatasheet}
          busy={busy}
        />
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
        {/* Two distributors describing the same part differently is normal and useful; the one
            in force stays above, and the other is a click away with its vendor named. */}
        <AlternatesDisclosure
          entries={descriptionAlternates}
          current={description}
          onUse={onEditDescription ? (value) => onEditDescription(value) : undefined}
        />
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
  // Filing shares the CAD row's exact anatomy (icon + uppercase label + value + chevron): the
  // visual row is one flat control, and in editable mode a transparent native <select> overlays
  // it so clicking still opens the real category dropdown.
  const editable = !!(onMoveCategory && categories && categories.length > 0);
  return (
    <div className="group relative" data-dev-id="detail.filing">
      <div
        aria-hidden={editable || undefined}
        className={
          "flex h-[34px] items-center gap-2.5 rounded-control border border-line bg-field px-3 transition-colors " +
          (editable ? "group-hover:bg-raise2 " : "") +
          (busy ? "opacity-50" : "")
        }
      >
        <Icon id="detail.filing-folder" className="h-3.5 w-3.5 flex-none text-t3" />
        <span className="text-2xs font-semibold uppercase tracking-[0.07em] text-t3">
          <Text id="detail.filing">Filing</Text>
        </span>
        <span className="ml-auto min-w-0 truncate text-xs font-medium text-t1">{category}</span>
        {editable ? (
          <Icon id="detail.select-chevron" className="h-3 w-3 flex-none text-t3" />
        ) : null}
      </div>
      {editable ? (
        <select
          aria-label="Category"
          value={category}
          disabled={busy}
          onChange={(e) => {
            if (e.target.value !== category) onMoveCategory!(e.target.value);
          }}
          className="absolute inset-0 h-full w-full cursor-pointer appearance-none opacity-0 disabled:cursor-not-allowed"
        >
          {categories!.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      ) : null}
    </div>
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
        <ul className="mt-1 flex flex-col">
          {distinct.map((entry, i) => {
            const value = String(entry.value ?? "");
            const inForce = same(value, current);
            const label = entry.source ? distributorLabel(entry.source) : "On Record";
            return (
              <li
                key={`${entry.source}-${i}`}
                className="flex items-baseline justify-between gap-2 py-[2px]"
              >
                {/* one line per answer: who said it, what they said, and the action. The value used
                    to sit on its own second line, which orphaned it from its source label. */}
                <span className="flex-none text-2xs uppercase tracking-[0.04em] text-t3">
                  {label}
                </span>
                <span className="min-w-0 flex-1 truncate text-right text-xs text-t2">{value}</span>
                {inForce ? (
                  <span className="flex-none text-2xs text-t3">In Use</span>
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
              <dt className="min-w-0 flex-1 truncate text-2xs uppercase tracking-[0.04em] text-t3">
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
  alternates,
  onUseSpecValue,
}: {
  groups: SpecGroup[];
  alternates: Record<string, SourcedAlternate[]>;
  onUseSpecValue?: (key: string, value: string, source: string) => void;
}) {
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
              row hover, and the value reads in the mono data face. The header is STICKY, so a part
              with far more specs than fit scrolls the pane while the group name stays in view. */}
          <div className="sticky top-0 z-[1] mb-1 flex items-center gap-2 border-b border-line bg-surface pb-1 pt-0.5">
            <span className="text-2xs font-semibold uppercase tracking-[0.08em] text-t3">
              {group.title}
            </span>
          </div>
          <SpecRowList
            rows={group.rows}
            alternates={alternates}
            onUseSpecValue={onUseSpecValue}
          />
        </section>
      ))}
    </div>
  );
}

// The rows of one spec group. Shared by the Specs sheet and the Sourcing tab's Trade block, so
// a family disclosure and a vendor disagreement look and behave identically wherever they appear.
function SpecRowList({
  rows,
  alternates,
  onUseSpecValue,
}: {
  rows: SpecRow[];
  alternates: Record<string, SourcedAlternate[]>;
  onUseSpecValue?: (key: string, value: string, source: string) => void;
}) {
  return (
    <dl className="flex flex-col">
      {rows.map((row) =>
        row.members ? (
          <SpecFamilyRow key={row.key} row={row} />
        ) : (
          <div
            key={row.key}
            className="-mx-1.5 rounded-[2px] px-1.5 py-[3px] transition-colors hover:bg-[var(--c-hover)]"
          >
            <div className="flex items-baseline justify-between gap-3">
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
  return (
    <section data-dev-id="detail.trade" className="mt-5 border-t border-line pt-3.5">
      <div className="mb-0.5 text-2xs font-semibold uppercase tracking-[0.05em] text-t3">
        Trade And Compliance
      </div>
      {/* Says WHOSE facts these are. Sitting directly under the last distributor's price ladder,
          the block read as that distributor's tariff rather than the part's own classification. */}
      <p className="mb-2 text-2xs text-t3">Part-level, from the distributor pages.</p>
      <SpecRowList
        rows={group.rows}
        alternates={alternates}
        onUseSpecValue={onUseSpecValue}
      />
    </section>
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
  const orderable = orderPurchases(purchase.filter((p) => p.url));
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
        const tiers = ladderRows(breaks);
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
            {tiers.length > 0 ? (
              <div className="mt-3">
                <div className="mb-2 text-2xs font-semibold uppercase tracking-[0.05em] text-t3">
                  Volume Pricing
                </div>
                {/* The qty-1 unit price is already the headline beside the stock, so the ladder
                    normally starts at the first bulk tier (10+, 100+, ...). It reads from 1+
                    instead whenever that is what keeps the count EVEN, because this is a
                    two-column flow and an odd count leaves a hole in the bottom-right cell
                    (punch 5). Parity is reached by showing MORE, never by hiding a price. */}
                <div
                  className="grid grid-flow-col gap-x-10"
                  style={{ gridTemplateRows: `repeat(${tiers.length / 2}, auto)` }}
                >
                  {tiers.map((b) => (
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
