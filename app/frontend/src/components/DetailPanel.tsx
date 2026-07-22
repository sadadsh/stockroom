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
import { useState, type ReactNode } from "react";
import type { PartDetail, PurchaseRef, SourcedField } from "../api/types";
import { deriveTitle, deriveAttributes, isReferenceOnlySpecKey } from "../lib/derive";
import { groupSpecs, type SpecGroup } from "../lib/specSchema";
import { assetReadiness, type AssetReadiness } from "../lib/edaTarget";
import { useInlineEdit } from "../lib/useInlineEdit";
import { EditableText } from "./EditableText";
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
  // The part's tags plus a few chips derived from key specs (package, mounting,
  // qualifications, salient features), so the attribute band is never empty.
  const attributes = deriveAttributes(detail);
  // Grouped, extensible spec sheet (Electrical / Physical / Ratings / Other) from lib/specSchema,
  // with catalog metadata (manufacturer, country, packaging, ...) dropped so the sheet is the
  // physical parameters, not a distributor page. Groups emptied by the filter fall away.
  const specGroups = groupSpecs(detail.category, detail.specs)
    .map((group) => ({
      ...group,
      rows: group.rows.filter((row) => !isReferenceOnlySpecKey(row.key)),
    }))
    .filter((group) => group.rows.length > 0);
  const specCount = specGroups.reduce((total, group) => total + group.rows.length, 0);
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
    { id: "specs", label: "Specs" },
    { id: "sourcing", label: "Sourcing" },
    ...(pinout.length > 0 ? [{ id: "pinout" as const, label: "Pinout" }] : []),
    ...(hasEnrich ? [{ id: "enrich" as const, label: "Enrich" }] : []),
    { id: "history", label: "History" },
  ];
  const activeTab = tabs.some((t) => t.id === tab) ? tab : "specs";

  return (
    <div className="flex h-full flex-col px-[30px] pb-4 pt-[22px]">
      <div className="flex min-h-0 w-full max-w-[1360px] flex-1 gap-7">
        {/* LEFT rail: the specimen card - identity, the physical object + its embodiments,
            and the single readiness read with the one Complete Part action. */}
        <aside className="flex w-[344px] flex-none flex-col gap-4 overflow-y-auto pr-1">
          <div>
            <TitleBlock
              headline={headline}
              name={detail.display_name}
              onRename={onEditField ? (v) => onEditField("display_name", v) : undefined}
              busy={busy}
            />
            <IdentityLine
              mpn={detail.mpn}
              manufacturer={detail.manufacturer}
              onEditMpn={onEditField ? (v) => onEditField("mpn", v) : undefined}
              onEditManufacturer={
                onEditField ? (v) => onEditField("manufacturer", v) : undefined
              }
              busy={busy}
            />
          </div>

          {/* the physical object as the hero, its symbol + footprint as supporting embodiments */}
          <div className="flex flex-col gap-2.5">
            <AssetTile
              variant="hero"
              name="3D Model"
              present={hasModel}
              className="h-[208px]"
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
                variant="tile"
                name="Symbol"
                present={!!detail.symbol?.name}
                className="h-[118px]"
                art={<SymbolArt />}
                thumb={
                  detail.symbol?.name ? (
                    <PreviewImage kind="symbol" partId={detail.id} fallback={<SymbolArt />} />
                  ) : undefined
                }
                onOpen={detail.symbol?.name ? () => setPreview("symbol") : undefined}
              />
              <AssetTile
                variant="tile"
                name="Footprint"
                present={!!detail.footprint?.name}
                className="h-[118px]"
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

          <ReadinessBlock kicad={kicad} altium={altium} altiumNeeds={altiumNeeds} />

          {canComplete && needsList.length > 0 ? (
            <button
              type="button"
              onClick={() => setCompleteOpen(true)}
              className="flex w-full items-center gap-2.5 rounded-card border border-warn/40 bg-warn/10 px-3.5 py-2.5 text-left transition hover:border-warn/70"
            >
              <WarnIcon className="h-4 w-4 flex-none text-warn" />
              <span className="flex-none text-sm font-semibold text-t1">Complete Part</span>
              <span className="min-w-0 flex-1 truncate text-2xs text-t3">
                Needs {needsList.join(", ")}
              </span>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5 flex-none text-t3">
                <path d="m9 18 6-6-6-6" />
              </svg>
            </button>
          ) : null}

          <RailReference
            datasheetUrl={detail.datasheet?.source_url || detail.datasheet?.file || ""}
            datasheetHref={detail.datasheet?.source_url || undefined}
            description={detail.description}
            onEditDatasheet={onEditField ? (v) => onEditField("datasheet", v) : undefined}
            onEditDescription={onEditField ? (v) => onEditField("description", v) : undefined}
            busy={busy}
          />
        </aside>

        {/* RIGHT workbench: the reference depth in one tabbed panel, so it never grows the page. */}
        <section className="flex min-h-0 min-w-0 flex-1 flex-col">
          <TabStrip
            tabs={tabs}
            active={activeTab}
            onSelect={setTab}
            idBase="workbench"
            aria-label="Part details"
            className="self-start"
          />
          <div className="mt-3 min-h-0 flex-1 overflow-y-auto">
            <WorkbenchPanel id="specs" active={activeTab}>
              <AttributesCard
                derived={attributes}
                manual={detail.tags}
                onEditTags={onEditField ? (next) => onEditField("tags", next) : undefined}
                busy={busy}
              />
              <SpecificationsSection groups={specGroups} count={specCount} />
            </WorkbenchPanel>

            <WorkbenchPanel id="sourcing" active={activeTab}>
              <Sourcing purchase={detail.purchase} hasMpn={!!detail.mpn} />
            </WorkbenchPanel>

            {pinout.length > 0 ? (
              <WorkbenchPanel id="pinout" active={activeTab}>
                <PinoutViewer
                  key={detail.id}
                  pins={pinout}
                  source={pinoutProvenance?.source}
                  confidence={pinoutProvenance?.confidence}
                />
              </WorkbenchPanel>
            ) : null}

            {hasEnrich ? (
              <WorkbenchPanel id="enrich" active={activeTab}>
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

            <WorkbenchPanel id="history" active={activeTab}>
              <PartTimeline key={detail.id} partId={detail.id} />
            </WorkbenchPanel>
          </div>
        </section>
      </div>

      {/* footer: filing (category) is organization, not identity, so it lives here, quiet; a
          destructive action never earns prime real estate, so Delete is the quiet text link
          opposite it. */}
      <footer className="mt-3 flex flex-none items-center justify-between border-t border-line pt-3">
        <Filing
          category={detail.category}
          categories={categories}
          onMoveCategory={onMoveCategory}
          busy={busy}
        />
        {onDelete ? (
          <button
            type="button"
            onClick={() => setConfirmDelete(true)}
            disabled={busy}
            className="text-xs text-t3 transition-colors hover:text-err disabled:opacity-50"
          >
            Delete Part
          </button>
        ) : null}
      </footer>

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
  children,
}: {
  id: WorkbenchTab;
  active: WorkbenchTab;
  children: ReactNode;
}) {
  return (
    <div
      role="tabpanel"
      id={tabPanelId("workbench", id)}
      aria-labelledby={tabButtonId("workbench", id)}
      hidden={active !== id}
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
        className="w-full rounded-control border border-line2 bg-field px-2 py-1 text-2xl font-bold tracking-[-0.02em] text-t1 outline-none focus:border-acc"
      />
    );
  }

  return (
    <div className="group flex items-start gap-1.5">
      <h1 className="min-w-0 break-words text-2xl font-bold leading-[1.06] tracking-[-0.022em] text-t1">
        {headline}
      </h1>
      {onRename ? (
        <button
          type="button"
          onClick={begin}
          disabled={busy}
          aria-label="Rename Part"
          className="mt-1 grid h-6 w-6 flex-none place-items-center rounded-control text-t3 opacity-0 transition hover:bg-raise2 hover:text-t1 focus-visible:opacity-100 group-hover:opacity-100 disabled:opacity-0"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
            <path d="M12 20h9" />
            <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
          </svg>
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
    <div className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1">
      <span className="h-1.5 w-1.5 flex-none rounded-full bg-t3" aria-hidden="true" />
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

// The single readiness read: KiCad and Altium each as one row - a green check when the tool's
// symbol + footprint are both present, else an amber dot and the exact assets it still needs.
// The 3D model is optional (it never blocks readiness), so it is not in the needs line.
function ReadinessBlock({
  kicad,
  altium,
  altiumNeeds,
}: {
  kicad: AssetReadiness;
  altium: AssetReadiness;
  altiumNeeds: string[];
}) {
  // KiCad needs come from the record's own refs; Altium needs prefer the capture query
  // (the record carries no Altium refs), falling back to its own blocking assets.
  const kicadNeeds = kicad.missing.filter((m) => m !== "3D Model");
  const altiumBlocking =
    altiumNeeds.length > 0
      ? altiumNeeds.map((n) => n.replace(/^Altium /, ""))
      : altium.missing.filter((m) => m !== "3D Model");
  return (
    <div className="rounded-card border border-line bg-surface">
      <ReadinessRow label="KiCad" ready={kicad.ready} needs={kicadNeeds} />
      <div className="border-t border-line" />
      <ReadinessRow label="Altium" ready={altium.ready} needs={altiumBlocking} />
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
    <div className="flex items-center gap-2.5 px-3.5 py-2.5">
      {ready ? (
        <svg viewBox="0 0 24 24" fill="none" stroke="var(--c-ok)" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5 flex-none">
          <path d="M20 6 9 17l-5-5" />
        </svg>
      ) : (
        <span className="h-2 w-2 flex-none rounded-full" style={{ background: "var(--c-warn)" }} />
      )}
      <span className="text-sm font-semibold text-t1">{label}</span>
      <span className="ml-auto text-2xs text-t3">
        {ready ? (
          <span className="text-ok">Ready</span>
        ) : needs.length > 0 ? (
          `Needs ${needs.map((n) => n.toLowerCase()).join(" + ")}`
        ) : (
          "Not ready"
        )}
      </span>
    </div>
  );
}

// The two remaining reference fields that are not part of the identity read: the datasheet
// (a link when it resolves) and the free-form description. Both stay editable so a part is
// completed here, and both read as quiet, labelled rows at the foot of the rail.
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
    <div className="flex flex-col gap-1 border-t border-line pt-3">
      <div className="flex items-baseline gap-2">
        <span className="w-[68px] flex-none pt-1 text-2xs uppercase tracking-[0.05em] text-t3">
          Datasheet
        </span>
        <span className="flex min-w-0 flex-1 items-center gap-1">
          {onEditDatasheet ? (
            <EditableText
              value={datasheetUrl}
              onSave={onEditDatasheet}
              label="Datasheet"
              placeholder="Add datasheet"
              mono
              truncate
              disabled={busy}
              displayClassName="text-xs"
            />
          ) : datasheetUrl ? (
            <span className="tnum truncate px-1.5 font-mono text-xs text-t1">{datasheetUrl}</span>
          ) : (
            <span className="px-1.5 text-xs italic text-t3">None</span>
          )}
          {datasheetHref ? (
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
      <div className="flex items-baseline gap-2">
        <span className="w-[68px] flex-none pt-1 text-2xs uppercase tracking-[0.05em] text-t3">
          Notes
        </span>
        <span className="min-w-0 flex-1">
          {onEditDescription ? (
            <EditableText
              value={description}
              onSave={onEditDescription}
              label="Description"
              placeholder="Add a note"
              multiline
              disabled={busy}
              displayClassName="text-xs"
            />
          ) : description ? (
            <span className="px-1.5 text-xs text-t2">{description}</span>
          ) : (
            <span className="px-1.5 text-xs italic text-t3">None</span>
          )}
        </span>
      </div>
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
  if (!onMoveCategory || !categories || categories.length === 0) {
    return (
      <div className="text-xs text-t3">
        Filing <span className="ml-1 text-t2">{category}</span>
      </div>
    );
  }
  return (
    <label className="flex items-center gap-1.5 text-xs text-t3">
      Filing
      <span className="relative inline-block">
        <select
          aria-label="Category"
          value={category}
          disabled={busy}
          onChange={(e) => {
            if (e.target.value !== category) onMoveCategory(e.target.value);
          }}
          className="appearance-none rounded-control border border-line bg-transparent py-1 pl-2 pr-6 text-xs font-medium text-t1 outline-none hover:border-line2 focus:border-acc disabled:cursor-not-allowed disabled:opacity-50"
        >
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <svg
          className="pointer-events-none absolute right-1.5 top-1/2 h-3 w-3 -translate-y-1/2 text-t3"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          aria-hidden="true"
        >
          <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
    </label>
  );
}

// The Attributes band: the FEW derived, parameter-ranked chips (deriveAttributes) plus any the
// user pins by hand. Manual attributes persist in the record's `tags` field (the retired "tags"
// concept is now this), so each shows a remove control and there is an inline add. Derived chips
// are read-only (they mirror the specs); a manual chip that duplicates a derived one is hidden.
function AttributesCard({
  derived,
  manual,
  onEditTags,
  busy,
}: {
  derived: string[];
  manual: string[];
  onEditTags?: (next: string[]) => void;
  busy?: boolean;
}) {
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const [expanded, setExpanded] = useState(false);

  const derivedLower = new Set(derived.map((a) => a.toLowerCase()));
  const manualChips = manual.filter(
    (t) => t.trim() !== "" && !derivedLower.has(t.trim().toLowerCase()),
  );
  // the most important first (derived is already importance-ranked), then the user's manual pins
  const chips = [
    ...derived.map((label) => ({ label, manual: false })),
    ...manualChips.map((label) => ({ label, manual: true })),
  ];
  const COLLAPSED = 8;
  const hasMore = chips.length > COLLAPSED;
  // collapsed keeps to ONE non-wrapping row (a glance); expanded wraps to show everything + edit.
  const open = expanded || !hasMore;
  const shown = open ? chips : chips.slice(0, COLLAPSED);

  const chipCls =
    "inline-flex flex-none items-center gap-1.5 rounded-full border px-3 py-[5px] text-xs font-medium";

  function commitAdd() {
    const value = draft.trim();
    setDraft("");
    setAdding(false);
    if (!value || !onEditTags) return;
    const exists =
      derivedLower.has(value.toLowerCase()) ||
      manual.some((t) => t.toLowerCase() === value.toLowerCase());
    if (!exists) onEditTags([...manual, value]);
  }

  function removeManual(tag: string) {
    onEditTags?.(manual.filter((t) => t !== tag));
  }

  if (chips.length === 0 && !onEditTags) return null;

  return (
    <div className="mb-5">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-2xs font-semibold uppercase tracking-[0.06em] text-t3">
          Attributes
        </span>
        {hasMore ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-2xs font-semibold text-t2 hover:text-t1"
          >
            {expanded ? "Show Less" : `Show All ${chips.length}`}
          </button>
        ) : null}
      </div>
      <div className={open ? "flex flex-wrap items-center gap-2" : "flex gap-2 overflow-hidden"}>
        {shown.map((c) =>
          c.manual ? (
            <span key={`m-${c.label}`} className={chipCls + " border-line2 bg-raise2 text-t1"}>
              {c.label}
              {onEditTags && open ? (
                <button
                  type="button"
                  onClick={() => removeManual(c.label)}
                  disabled={busy}
                  aria-label={`Remove ${c.label}`}
                  className="-mr-1 grid h-4 w-4 place-items-center rounded-full text-t3 hover:bg-line2 hover:text-t1 disabled:opacity-50"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" className="h-2.5 w-2.5">
                    <path d="M18 6 6 18M6 6l12 12" />
                  </svg>
                </button>
              ) : null}
            </span>
          ) : (
            <span key={`d-${c.label}`} className={chipCls + " border-line bg-field text-t2"}>
              {c.label}
            </span>
          ),
        )}
        {onEditTags && open ? (
          adding ? (
            <input
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commitAdd}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitAdd();
                else if (e.key === "Escape") {
                  setDraft("");
                  setAdding(false);
                }
              }}
              placeholder="Add attribute"
              aria-label="Add attribute"
              className="h-[29px] w-36 flex-none rounded-full border border-line2 bg-field px-3 text-xs text-t1 outline-none placeholder:text-t3 focus:border-acc"
            />
          ) : (
            <button
              type="button"
              onClick={() => setAdding(true)}
              disabled={busy}
              className="inline-flex flex-none items-center gap-1 rounded-full border border-dashed border-line2 px-3 py-[5px] text-xs font-medium text-t3 hover:border-acc hover:text-t1 disabled:opacity-50"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" className="h-3 w-3">
                <path d="M12 5v14M5 12h14" />
              </svg>
              Add
            </button>
          )
        ) : null}
      </div>
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
  variant,
  className,
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
    (variant === "hero" ? "border-line shadow-raise " : "border-line shadow-file ") +
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

// All specs render at once inside the Specs tab (never collapsed): each group (Electrical /
// Physical / Ratings / Other) is its own labelled block, and the rows within it are a compact
// two-column definition list - the key in quiet sans on the left, the value in the mono readout
// face on the right - so a long value wraps in place. The tab owns the scroll, so however many
// specs a part carries, they never grow the page.
function SpecificationsSection({ groups, count }: { groups: SpecGroup[]; count: number }) {
  if (groups.length === 0) {
    return (
      <div className="text-sm text-t3">No parametric specs on record for this part.</div>
    );
  }
  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <span className="text-2xs font-semibold uppercase tracking-[0.06em] text-t3">
          Specifications
        </span>
        <span className="tnum font-mono text-2xs text-t3">{count}</span>
      </div>
      {/* One column (the owner's call): a plain label -> value definition list per group, so
          nothing truncates and no spec ever sits in a cramped side column. The tab owns the
          scroll, so however many rows a part carries, they never grow the page. */}
      <div className="flex max-w-[560px] flex-col gap-5">
        {groups.map((group) => (
          <section key={group.title}>
            <div className="mb-1 text-2xs font-semibold uppercase tracking-[0.05em] text-t2">
              {group.title}
            </div>
            <dl>
              {group.rows.map((row) => (
                <div
                  key={row.key}
                  className="grid grid-cols-[minmax(0,190px)_1fr] gap-x-6 border-b border-line/60 py-1.5 last:border-0"
                >
                  <dt
                    className="break-words text-xs text-t3"
                    title={typeof row.label === "string" ? row.label : undefined}
                  >
                    {row.label}
                  </dt>
                  <dd className="tnum min-w-0 break-words font-mono text-sm text-t1">
                    {row.unit ? `${row.value} ${row.unit}` : row.value}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
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
      <div className="text-sm text-t2">
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
    <div className="flex flex-col">
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
