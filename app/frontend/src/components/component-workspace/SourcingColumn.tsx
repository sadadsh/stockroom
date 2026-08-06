/**
 * The right column: Sourcing and Resources.
 *
 * SIX SECTIONS, IN ONE FIXED ORDER, and the order is the order a person asks the questions in:
 *
 *   1 Product Status and Stock     can I still purchase this part, and is there some of it
 *   2 Distributor Offers           who has it, how many, and for how much
 *   3 Pricing and Lead Time        what does it cost at quantity, and how long is the wait
 *   4 Documents                    what has been written about it
 *   5 Related Parts                what else would do the job, and why
 *   6 Data Provenance and Timeline where each of those answers came from
 *
 * Backend source records are never first. "DigiKey supplied data, Mouser is not connected" is an
 * explanation, and an explanation is only wanted once the thing it explains has been read - so the
 * ledger is at the bottom, under everything it accounts for.
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
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { useDevMode } from "../../lib/devMode";
import { formatCount, formatPrice, formatTimestamp } from "../../lib/formatValue";
import { LayoutRuntimeScope, type RegionChromeProps } from "../../layout/LayoutRenderer";
import { WORKSPACE_CONDITION } from "../../layout/defaultWorkspaceLayout";
import { useWorkspaceRender } from "../../layout/workspaceRenderContext";
import { Button, StatusText } from "../primitives";
import {
  WorkspaceColumnFrame,
  WorkspaceColumnScroller,
  WorkspaceColumnTitleStrip,
} from "./WorkspaceColumns";
import { latestCheck } from "./offerFacts";
import { OffersSection } from "./OffersSection";
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
      refreshing={sourcing.refreshing}
    />
  );
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
 * The one control that reveals the sections with nothing in them.
 *
 * It states the COUNT, so it is an answer as well as an action: `Show 5 Empty Sections` on a part
 * nobody has sourced says exactly how much of the column is silent, which is the direct form the
 * quality vocabulary uses everywhere else ("3 Required Values Missing", never "3 / 8").
 *
 * LAST, under everything it accounts for, and absent when there is nothing to reveal: a control
 * that would show zero sections is a dead click path. When the reveal is off, the provenance
 * section it hides takes `View Data Provenance` with it - which is why that action also has a
 * permanent home in Manage > View Data Provenance...
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
  const unknown = useText("component-browser.value-unknown", "Unknown");
  if (!workspace) return null;
  const dossier: ComponentDossier = workspace.dossier;
  const { supplySummary } = dossier;
  const lifecycle = supplySummary.lifecycle || dossier.identity.lifecycle || "";
  const lastChecked = latestCheck(dossier.distributorOffers);
  const checkedStamp = lastChecked ? formatTimestamp(lastChecked) : null;

  return (
    <SourcingSection
      devId="component-browser.lifecycle"
      title={<Text id="component-browser.lifecycle-title">Product Status and Stock</Text>}
    >
      <PropertyRow label={<Text id="component-browser.lifecycle-state">Product Status</Text>}>
        {lifecycle ? (
          <StatusText tone={lifecycleTone(lifecycle)}>{lifecycle}</StatusText>
        ) : (
          <span className="ui-property-value ui-disabled">{unknown}</span>
        )}
      </PropertyRow>
      <PropertyRow
        label={<Text id="component-browser.manufacturer-status">Manufacturer Status</Text>}
      >
        <span data-dev-id="component-browser.manufacturer-status">
          {supplySummary.manufacturerStatus ? (
            <StatusText tone={lifecycleTone(supplySummary.manufacturerStatus)}>
              {supplySummary.manufacturerStatus}
            </StatusText>
          ) : (
            <span className="ui-property-value ui-disabled">{unknown}</span>
          )}
        </span>
      </PropertyRow>
      <PropertyRow label={<Text id="component-browser.total-stock">Total Stock</Text>}>
        {/* `null` is UNKNOWN. Rendering it as 0 would claim every distributor was asked and every
            one of them answered none, which is a different and much stronger fact. */}
        <span
          data-dev-id="component-browser.total-stock"
          data-stock-known={supplySummary.totalStock === null ? "false" : "true"}
          className="ui-property-value ui-numeric"
        >
          {supplySummary.totalStock === null ? (
            <span className="ui-disabled">{unknown}</span>
          ) : (
            formatCount(supplySummary.totalStock)
          )}
        </span>
      </PropertyRow>
      <PropertyRow label={<Text id="component-browser.lead-time">Lead Time</Text>}>
        <span className="ui-property-value">
          {supplySummary.leadTime || <span className="ui-disabled">{unknown}</span>}
        </span>
      </PropertyRow>
      <PropertyRow label={<Text id="component-browser.last-checked">Last Checked</Text>}>
        {checkedStamp ? (
          <span className="flex items-baseline gap-1.5">
            {/* Relative, with the absolute time in the tooltip. Never one without the other. */}
            <span className="ui-component-metadata" title={checkedStamp.title}>
              {checkedStamp.text}
            </span>
            <StatusText tone={STALENESS_TONE[supplySummary.staleness]} className="flex-none">
              <StalenessLabel staleness={supplySummary.staleness} />
            </StatusText>
          </span>
        ) : (
          <span className="ui-property-value ui-disabled">{unknown}</span>
        )}
      </PropertyRow>
    </SourcingSection>
  );
}

/**
 * What it costs at quantity, and how long the wait is.
 *
 * The best price names the distributor quoting it, because "$0.42" without a name is not a price
 * anyone can act on. The ladder itself stays one click away: a column is the wrong shape for eight
 * quantity breaks per distributor, and the full sheet is the right one.
 */
export function SourcingPricingPart() {
  const workspace = useWorkspaceRender();
  const unknown = useText("component-browser.value-unknown", "Unknown");
  const fromText = useCopyFormatter("component-browser.price-from", "from {provider}");
  if (!workspace) return null;
  const { supplySummary, distributorOffers } = workspace.dossier;
  const best = distributorOffers.find(
    (offer) => offer.provider === supplySummary.bestUnitPriceProvider,
  );
  const breakCount = distributorOffers.reduce(
    (total, offer) => total + offer.priceBreaks.length,
    0,
  );

  return (
    <SourcingSection
      devId="component-browser.pricing"
      title={<Text id="component-browser.pricing-title">Pricing and Lead Time</Text>}
      action={
        breakCount > 0 ? (
          <Button
            small
            data-dev-id="component-browser.offers-all"
            onClick={workspace.sourcing.onViewOffers}
          >
            <Text id="component-browser.offers-all">View Price Breaks</Text>
          </Button>
        ) : undefined
      }
    >
      <PropertyRow label={<Text id="component-browser.best-price">Best Unit Price</Text>}>
        {supplySummary.bestUnitPrice === null ? (
          <span className="ui-property-value ui-numeric ui-disabled">{unknown}</span>
        ) : (
          <span className="flex items-baseline gap-1.5">
            <span className="ui-key-fact ui-numeric flex-none">
              {formatPrice(
                supplySummary.bestUnitPrice,
                supplySummary.bestUnitPriceCurrency || "$",
              )}
            </span>
            {best ? (
              <span className="ui-component-metadata min-w-0 truncate">
                {fromText({ provider: best.providerLabel })}
              </span>
            ) : null}
          </span>
        )}
      </PropertyRow>
      <PropertyRow label={<Text id="component-browser.price-breaks">Price Breaks</Text>}>
        <span className="ui-property-value ui-numeric">
          {breakCount > 0 ? formatCount(breakCount) : <span className="ui-disabled">{unknown}</span>}
        </span>
      </PropertyRow>
      <PropertyRow label={<Text id="component-browser.factory-lead-time">Manufacturer Lead Time</Text>}>
        <span className="ui-property-value">
          {supplySummary.factoryLeadTime || <span className="ui-disabled">{unknown}</span>}
        </span>
      </PropertyRow>
    </SourcingSection>
  );
}

function StalenessLabel({ staleness }: { staleness: Staleness }) {
  if (staleness === "fresh") return <Text id="component-browser.staleness-fresh">Fresh</Text>;
  if (staleness === "aging") return <Text id="component-browser.staleness-aging">Aging</Text>;
  if (staleness === "stale") return <Text id="component-browser.staleness-stale">Stale</Text>;
  return <Text id="component-browser.staleness-unknown">Age Unknown</Text>;
}
