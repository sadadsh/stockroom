/**
 * The right column: Sourcing and Resources.
 *
 * SIX SECTIONS, IN ONE FIXED ORDER, and the order is the order a person asks the questions in:
 *
 *   1 Lifecycle and Availability   can I still buy this part, and is there any of it
 *   2 Distributor Offers           who has it, how many, and for how much
 *   3 Pricing and Lead Time        what does it cost at quantity, and how long is the wait
 *   4 Documents                    what has been written about it
 *   5 Related Parts                what else would do the job, and why
 *   6 Data Provenance and History  where every one of those answers came from
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
 */
import type { MutableRefObject } from "react";
import type { ComponentDossier, DistributorOffer, Staleness } from "../../api/dossierTypes";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { formatCount, formatPrice, formatTimestamp } from "../../lib/formatValue";
import { Button, StatusText } from "../primitives";
import { WorkspaceColumn } from "./WorkspaceColumns";
import { OffersSection } from "./OffersSection";
import { ProvenanceHistory } from "./ProvenanceHistory";
import { DocumentsSection, RelatedPartsSection } from "./ResourcesSection";
import { PropertyRow, SourcingSection } from "./SourcingParts";
import { lifecycleTone } from "./componentIdentity";

/** How much a reading can still be relied on. `unknown` is silence, not freshness. */
const STALENESS_TONE: Record<Staleness, "ok" | "warn" | "err" | "neutral"> = {
  fresh: "ok",
  aging: "warn",
  stale: "err",
  unknown: "neutral",
};

export function SourcingColumn({
  dossier,
  onViewOffers,
  onViewProvenance,
  onOpenDocument,
  onRefresh,
  refreshing,
  scrollRef,
}: {
  dossier: ComponentDossier;
  onViewOffers: () => void;
  onViewProvenance: () => void;
  /** Open a stored or referenced document in the viewer, addressed by its derived id. */
  onOpenDocument: (id: string) => void;
  onRefresh: () => void;
  refreshing: boolean;
  scrollRef: MutableRefObject<HTMLDivElement | null>;
}) {
  const { supplySummary, distributorOffers, documents, relatedParts, provenance } = dossier;

  return (
    <WorkspaceColumn
      id="sourcing"
      devId="component-browser.column-sourcing"
      title={<Text id="component-browser.column-sourcing">Sourcing and Resources</Text>}
      meta={supplySummary.offerCount > 0 ? formatCount(supplySummary.offerCount) : undefined}
      scrollRef={(node) => {
        scrollRef.current = node;
      }}
    >
      <LifecycleSection dossier={dossier} />

      <OffersSection
        offers={distributorOffers}
        failures={supplySummary.failures}
        onRefresh={onRefresh}
        refreshing={refreshing}
      />

      <PricingSection dossier={dossier} onViewOffers={onViewOffers} />

      <DocumentsSection
        documents={documents.items}
        preferredReason={documents.preferredDatasheetReason}
        onOpenDocument={onOpenDocument}
      />

      <RelatedPartsSection parts={relatedParts} />

      <ProvenanceHistory
        provenance={provenance}
        revisions={dossier.revisions}
        diagnostics={dossier.diagnostics}
        onViewProvenance={onViewProvenance}
      />
    </WorkspaceColumn>
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
function LifecycleSection({ dossier }: { dossier: ComponentDossier }) {
  const { supplySummary } = dossier;
  const unknown = useText("component-browser.value-unknown", "Unknown");
  const lifecycle = supplySummary.lifecycle || dossier.identity.lifecycle || "";
  const lastChecked = latestCheck(dossier.distributorOffers);
  const checkedStamp = lastChecked ? formatTimestamp(lastChecked) : null;

  return (
    <SourcingSection
      devId="component-browser.lifecycle"
      title={<Text id="component-browser.lifecycle-title">Lifecycle and Availability</Text>}
    >
      <PropertyRow label={<Text id="component-browser.lifecycle-state">Lifecycle</Text>}>
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
function PricingSection({
  dossier,
  onViewOffers,
}: {
  dossier: ComponentDossier;
  onViewOffers: () => void;
}) {
  const { supplySummary, distributorOffers } = dossier;
  const unknown = useText("component-browser.value-unknown", "Unknown");
  const fromText = useCopyFormatter("component-browser.price-from", "from {provider}");
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
          <Button small data-dev-id="component-browser.offers-all" onClick={onViewOffers}>
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
      <PropertyRow label={<Text id="component-browser.price-breaks">Quantity Breaks</Text>}>
        <span className="ui-property-value ui-numeric">
          {breakCount > 0 ? formatCount(breakCount) : <span className="ui-disabled">{unknown}</span>}
        </span>
      </PropertyRow>
      <PropertyRow label={<Text id="component-browser.factory-lead-time">Factory Lead Time</Text>}>
        <span className="ui-property-value">
          {supplySummary.factoryLeadTime || <span className="ui-disabled">{unknown}</span>}
        </span>
      </PropertyRow>
    </SourcingSection>
  );
}

/** The most recent moment any distributor was read, or "" when none has been. */
export function latestCheck(offers: readonly DistributorOffer[]): string {
  const stamps = offers.map((offer) => offer.lastCheckedAt).filter(Boolean).sort();
  return stamps.length === 0 ? "" : stamps[stamps.length - 1];
}

function StalenessLabel({ staleness }: { staleness: Staleness }) {
  if (staleness === "fresh") return <Text id="component-browser.staleness-fresh">Fresh</Text>;
  if (staleness === "aging") return <Text id="component-browser.staleness-aging">Aging</Text>;
  if (staleness === "stale") return <Text id="component-browser.staleness-stale">Stale</Text>;
  return <Text id="component-browser.staleness-unknown">Age Unknown</Text>;
}
