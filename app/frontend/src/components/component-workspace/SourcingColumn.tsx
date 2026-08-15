/**
 * The right column: Sourcing and Resources.
 *
 * Price breaks are the one open reading path. Provider and offer identity remain visible because a
 * tier without its seller and SKU is ambiguous; stock, lifecycle, offer metadata, official payloads,
 * documents, alternatives, and provenance each begin as one closed category row. This keeps the
 * everyday comparison direct while preserving every retained fact on request.
 *
 * The fixed order is: Price Breaks, Stock and Status, Official Data, Documents, Alternatives, then
 * Sources and Timeline. Backend records remain last because they explain the decisions above them.
 *
 * Every number here is the projection's, not a re-derivation. `supplySummary.totalStock` is `null`
 * when NOBODY reported a count, and that renders as Unknown rather than as zero: "no stock" and
 * "we never checked" are different answers with different consequences, and summing an empty list
 * to get 0 erases the difference on the way to the screen.
 *
 * Statuses here are text, never controls. `ui-status-text` pins `cursor: default` and strips the
 * border, fill, hover and focus ring, because every one of those says "click me" and a lifecycle
 * state cannot be clicked. Colour is spent only where it means something - green for available and
 * in production, amber for partial and not-recommended, red for obsolete and failed, gray for
 * unknown - and never on blue, which in a grayscale application would be the only hue on screen
 * that encoded nothing.
 *
 * THE ORDER IS THE DOCUMENT'S NOW (plan Phase 1), and each collapsible section's `fill[id] ||
 * showEmpty` is a NAMED CONDITION the document lists and this column answers. The reveal preference
 * stays exactly where it was - read once, on mount, inside the column - because it is a workstation
 * habit rather than shared state, and another tab's write must not change the column under someone
 * mid-read. What the column answers for its own subtree is only that preference; whether each
 * section HAS content is answered once at workspace level, because the column band needs the same
 * answer to decide its widths.
 */
import { createContext, useContext, useMemo, useState } from "react";
import type { ComponentDossier, Staleness } from "../../api/dossierTypes";
import { Text, useCopyFormatter } from "../../lib/copy";
import { useDevMode } from "../../lib/devMode";
import { formatCount, formatTimestamp } from "../../lib/formatValue";
import { LayoutRuntimeScope, type RegionChromeProps } from "../../layout/LayoutRenderer";
import { WORKSPACE_CONDITION } from "../../layout/defaultWorkspaceLayout";
import { useWorkspaceRender } from "../../layout/workspaceRenderContext";
import { Icon } from "../Icon";
import { Button, StatusText } from "../primitives";
import {
  WorkspaceColumnFrame,
  WorkspaceColumnScroller,
  WorkspaceColumnTitleStrip,
} from "./WorkspaceColumns";
import { latestCheck } from "./offerFacts";
import { OffersSection } from "./OffersSection";
import { OfficialApiDataSection } from "./OfficialApiDataSection";
import { ProvenanceHistory } from "./ProvenanceHistory";
import { DocumentsSection, RelatedPartsSection } from "./ResourcesSection";
import { PropertyRow, SourcingSection } from "./SourcingParts";
import {
  emptySourcingSections,
  readShowEmptySections,
  sourcingSectionFill,
  writeShowEmptySections,
} from "./sourcingSections";
import { lifecycleTone } from "./componentIdentity";

/** How much a reading can still be relied on. `unknown` is silence, not freshness. */
const STALENESS_TONE: Record<Staleness, "ok" | "warn" | "err" | "neutral"> = {
  fresh: "ok",
  aging: "warn",
  stale: "err",
  unknown: "neutral",
};

/** Whether the blank sections are on screen, and the one control that changes that. */
interface SourcingReveal {
  showing: boolean;
  toggle: () => void;
}

const SourcingRevealContext = createContext<SourcingReveal>({
  showing: false,
  toggle: () => {},
});

/** The column's frame. */
export function SourcingColumnChrome({ children }: RegionChromeProps) {
  return (
    <WorkspaceColumnFrame id="sourcing" devId="component-browser.column-sourcing">
      {children}
    </WorkspaceColumnFrame>
  );
}

export function SourcingTitleStripPart() {
  const workspace = useWorkspaceRender();
  if (!workspace) return null;
  const { offerCount } = workspace.dossier.supplySummary;
  return (
    <WorkspaceColumnTitleStrip
      title={<Text id="component-browser.column-sourcing">Sourcing and Resources</Text>}
      meta={offerCount > 0 ? formatCount(offerCount) : undefined}
    />
  );
}

/**
 * The column's one scroller, and the reveal preference that decides how much is in it.
 *
 * Read once, on mount. Re-reading per render would let another tab's write change the column under
 * someone mid-read, and this is a preference, not shared state. The toggle it belongs to is a
 * placement of its own at the bottom of the column, so the state is handed down through the
 * document's runtime rather than through a prop.
 */
export function SourcingBodyChrome({ children }: RegionChromeProps) {
  const workspace = useWorkspaceRender();
  const [showEmpty, setShowEmpty] = useState(readShowEmptySections);
  const conditions = useMemo(
    () => ({ [WORKSPACE_CONDITION.sourcingShowEmpty]: showEmpty }),
    [showEmpty],
  );
  const reveal = useMemo<SourcingReveal>(
    () => ({
      showing: showEmpty,
      toggle: () => {
        const next = !showEmpty;
        setShowEmpty(next);
        writeShowEmptySections(next);
      },
    }),
    [showEmpty],
  );
  if (!workspace) return null;
  return (
    <WorkspaceColumnScroller
      id="sourcing"
      scrollRef={(node) => {
        workspace.sourcing.scrollRef.current = node;
      }}
    >
      <SourcingRevealContext.Provider value={reveal}>
        <LayoutRuntimeScope conditions={conditions}>{children}</LayoutRuntimeScope>
      </SourcingRevealContext.Provider>
    </WorkspaceColumnScroller>
  );
}

export function SourcingOffersPart() {
  const workspace = useWorkspaceRender();
  if (!workspace) return null;
  const { dossier, sourcing } = workspace;
  return (
    <OffersSection
      offers={dossier.distributorOffers}
      failures={dossier.supplySummary.failures}
      onRefresh={sourcing.onRefresh}
      onViewAll={sourcing.onViewOffers}
      refreshing={sourcing.refreshing}
    />
  );
}

export function SourcingOfficialApiPart() {
  const workspace = useWorkspaceRender();
  if (!workspace) return null;
  return <OfficialApiDataSection data={workspace.dossier.officialApiData} />;
}

export function SourcingDocumentsPart() {
  const workspace = useWorkspaceRender();
  if (!workspace) return null;
  const { dossier, sourcing } = workspace;
  return (
    <DocumentsSection
      documents={dossier.documents.items}
      preferredReason={dossier.documents.preferredDatasheetReason}
      onOpenDocument={sourcing.onOpenDocument}
    />
  );
}

export function SourcingRelatedPart() {
  const workspace = useWorkspaceRender();
  if (!workspace) return null;
  return <RelatedPartsSection parts={workspace.dossier.relatedParts} />;
}

export function SourcingProvenancePart() {
  const workspace = useWorkspaceRender();
  if (!workspace) return null;
  const { dossier, sourcing } = workspace;
  return (
    <ProvenanceHistory
      provenance={dossier.provenance}
      revisions={dossier.revisions}
      diagnostics={dossier.diagnostics}
      onViewProvenance={sourcing.onViewProvenance}
    />
  );
}

/**
 * Developer recovery for sections with no content. Normal use omits blank categories entirely;
 * Design Studio can still reveal them to inspect and arrange every registered piece. The control
 * remains last and disappears when there is nothing to reveal.
 */
export function SourcingEmptySectionsPart() {
  const workspace = useWorkspaceRender();
  const { enabled: developerMode } = useDevMode();
  const reveal = useContext(SourcingRevealContext);
  const showLabel = useCopyFormatter(
    "component-browser.show-empty-sections",
    "Show {count} Blank Sections",
  );
  const hideLabel = useCopyFormatter(
    "component-browser.hide-empty-sections",
    "Hide {count} Blank Sections",
  );
  if (!workspace) return null;
  if (!developerMode) {
    return <div data-dev-id="component-browser.empty-sections" hidden />;
  }
  const hidden = emptySourcingSections(
    sourcingSectionFill(workspace.dossier, developerMode),
  ).length;
  if (hidden === 0) return null;
  const count = formatCount(hidden);
  return (
    <div className="px-2 py-1">
      <Button
        small
        data-dev-id="component-browser.empty-sections"
        aria-expanded={reveal.showing}
        onClick={reveal.toggle}
      >
        {reveal.showing ? hideLabel({ count }) : showLabel({ count })}
      </Button>
    </div>
  );
}

/**
 * Can this part still be bought, and is there any of it.
 *
 * `Lifecycle` is the library's canonical state; `Manufacturer Status` is the manufacturer's own
 * word for the same thing. They are separate rows because they are allowed to disagree - a
 * manufacturer marking a part NRND while a distributor still lists it as active is exactly the
 * disagreement a person needs to see rather than have resolved for them.
 */
export function SourcingLifecyclePart() {
  const workspace = useWorkspaceRender();
  if (!workspace) return null;
  const dossier: ComponentDossier = workspace.dossier;
  const { supplySummary } = dossier;
  const lifecycle = supplySummary.lifecycle || dossier.identity.lifecycle || "";
  const lastChecked = latestCheck(dossier.distributorOffers);
  const checkedStamp = lastChecked ? formatTimestamp(lastChecked) : null;
  if (
    !lifecycle
    && !supplySummary.manufacturerStatus
    && supplySummary.totalStock === null
    && !supplySummary.leadTime
    && !checkedStamp
  ) return null;

  return (
    <SourcingSection
      devId="component-browser.lifecycle"
      title={(
        <span className="flex items-center gap-1.5">
          <Icon id="status.info" className="h-3.5 w-3.5 text-t3" />
          <Text id="component-browser.lifecycle-title">Stock and Status</Text>
        </span>
      )}
      collapsed
    >
      {lifecycle ? (
        <PropertyRow label={<Text id="component-browser.lifecycle-state">Product Status</Text>}>
          <StatusText tone={lifecycleTone(lifecycle)}>{lifecycle}</StatusText>
        </PropertyRow>
      ) : null}
      {supplySummary.manufacturerStatus ? (
        <PropertyRow
          label={<Text id="component-browser.manufacturer-status">Manufacturer Status</Text>}
        >
          <span data-dev-id="component-browser.manufacturer-status">
            <StatusText tone={lifecycleTone(supplySummary.manufacturerStatus)}>
              {supplySummary.manufacturerStatus}
            </StatusText>
          </span>
        </PropertyRow>
      ) : null}
      {supplySummary.totalStock !== null ? (
        <PropertyRow label={<Text id="component-browser.total-stock">Total Stock</Text>}>
          <span
            data-dev-id="component-browser.total-stock"
            data-stock-known="true"
            className="ui-property-value ui-numeric"
          >
            {formatCount(supplySummary.totalStock)}
          </span>
        </PropertyRow>
      ) : null}
      {supplySummary.leadTime || checkedStamp ? (
        <div data-dev-id="component-browser.lifecycle-details">
          {supplySummary.leadTime ? (
            <PropertyRow label={<Text id="component-browser.lead-time">Lead Time</Text>}>
              <span className="ui-property-value">{supplySummary.leadTime}</span>
            </PropertyRow>
          ) : null}
          {checkedStamp ? (
            <PropertyRow label={<Text id="component-browser.last-checked">Last Checked</Text>}>
              <span className="flex items-baseline gap-1.5">
                <span className="ui-component-metadata" title={checkedStamp.title}>
                  {checkedStamp.text}
                </span>
                {supplySummary.staleness === "unknown" ? null : (
                  <StatusText tone={STALENESS_TONE[supplySummary.staleness]} className="flex-none">
                    <StalenessLabel staleness={supplySummary.staleness} />
                  </StatusText>
                )}
              </span>
            </PropertyRow>
          ) : null}
        </div>
      ) : null}
    </SourcingSection>
  );
}

function StalenessLabel({ staleness }: { staleness: Staleness }) {
  if (staleness === "fresh") return <Text id="component-browser.staleness-fresh">Fresh</Text>;
  if (staleness === "aging") return <Text id="component-browser.staleness-aging">Aging</Text>;
  if (staleness === "stale") return <Text id="component-browser.staleness-stale">Stale</Text>;
  return <Text id="component-browser.staleness-unknown">Age Unknown</Text>;
}
