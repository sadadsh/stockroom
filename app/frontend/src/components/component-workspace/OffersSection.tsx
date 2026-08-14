import { useEffect, useRef, type ReactNode } from "react";
import type { DistributorOffer } from "../../api/dossierTypes";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { formatCount, formatPrice, formatTimestamp } from "../../lib/formatValue";
import { Icon } from "../Icon";
import { ExternalIcon } from "../icons";
import { EmptyState } from "../primitives";
import { SourcingSection } from "./SourcingParts";
import { groupOffersByProvider, type OfferGroup } from "./offerFacts";
import { useSupplyFailureText } from "./provenanceText";

/** Keep the last usable list visible while a refresh is in flight. */
export function useRetainedOffers(
  offers: readonly DistributorOffer[],
  refreshing: boolean,
): readonly DistributorOffer[] {
  const held = useRef<readonly DistributorOffer[]>(offers);
  useEffect(() => {
    if (!refreshing) held.current = offers;
  }, [offers, refreshing]);
  if (!refreshing) return offers;
  return offers.length > 0 ? offers : held.current;
}

export function OffersSection({
  offers,
  failures,
  onRefresh,
  onViewAll,
  refreshing,
}: {
  offers: readonly DistributorOffer[];
  failures: ReadonlyArray<{ provider: string; providerLabel: string; state: string }>;
  onRefresh: () => void;
  onViewAll: () => void;
  refreshing: boolean;
}) {
  const refreshLabel = useText("component-browser.refresh-offers", "Refresh Offers");
  const refreshingLabel = useText("component-browser.refreshing-offers", "Refreshing...");
  const ledgerLabel = useText("component-browser.offers-table", "Distributor offers");
  const fullRecordLabel = useText("component-browser.offers-all", "View Full Sourcing Record");
  const shown = useRetainedOffers(offers, refreshing);
  const groups = groupOffersByProvider(shown);

  return (
    <SourcingSection
      devId="component-browser.offers"
      title={(
        <span className="flex items-center gap-1.5">
          <Icon id="action.enrich" className="h-3.5 w-3.5 text-t3" />
          <Text id="component-browser.offers-title">Distributor Offers</Text>
        </span>
      )}
      action={(
        <span className="flex items-center gap-0.5">
          {shown.length > 0 ? (
            <FullRecordAction label={fullRecordLabel} onClick={onViewAll} />
          ) : null}
          <button
            type="button"
            data-dev-id="component-browser.refresh-offers"
            aria-busy={refreshing || undefined}
            aria-label={refreshing ? refreshingLabel : refreshLabel}
            title={refreshing ? refreshingLabel : refreshLabel}
            disabled={refreshing}
            onClick={onRefresh}
            className={iconActionClass}
          >
            {refreshing ? <Spinner /> : <Icon id="action.refresh" className="h-3.5 w-3.5" />}
          </button>
        </span>
      )}
    >
      {failures.length > 0 ? <SupplyFailures failures={failures} /> : null}
      {shown.length === 0 ? (
        <EmptyState dense id="component-browser.offers-empty">
          No distributor has quoted this component.
        </EmptyState>
      ) : (
        <ul data-dev-id="component-browser.offers-table" aria-label={ledgerLabel} className="min-w-0">
          {groups.map((group) => (
            <ProviderGroup key={group.provider || group.providerLabel} group={group} />
          ))}
        </ul>
      )}
    </SourcingSection>
  );
}

const iconActionClass =
  "flex h-[20px] w-[20px] flex-none items-center justify-center rounded-control " +
  "text-t3 hover:bg-control-hover hover:text-t1 disabled:text-t5 disabled:hover:bg-transparent " +
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus";

function FullRecordAction({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      data-dev-id="component-browser.offers-all"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={iconActionClass}
    >
      <Icon id="action.view" className="h-3.5 w-3.5" />
    </button>
  );
}

function ProviderGroup({ group }: { group: OfferGroup }) {
  const count = group.offers.length;
  return (
    <li data-sourcing-provider={group.provider} className="border-b border-line last:border-b-0">
      <div className="flex min-h-[26px] items-center gap-2 bg-row-alt/45 px-2 py-1">
        <span className="ui-row-secondary min-w-0 flex-1 truncate text-t1">{group.providerLabel}</span>
        <span className="ui-component-metadata flex-none tabular-nums">
          {formatCount(count)} {count === 1 ? "offer" : "offers"}
        </span>
      </div>
      <ul className="divide-y divide-line/60">
        {group.offers.map((offer) => (
          <OfferDisclosure key={`${offer.provider}:${offer.sku}`} offer={offer} />
        ))}
      </ul>
    </li>
  );
}

function OfferDisclosure({ offer }: { offer: DistributorOffer }) {
  const noPrice = useText("component-browser.no-price", "No price");
  const stockUnknown = useText("component-browser.stock-unknown", "Not reported");
  const emptyValue = useText("component-browser.no-value", "None");
  const listing = useCopyFormatter("component-browser.open-listing", "Open {provider} Listing");
  const label = listing({ provider: offer.providerLabel });
  const stamp = offer.lastCheckedAt ? formatTimestamp(offer.lastCheckedAt) : null;
  const count = offer.priceBreaks.length;
  const detailsLabel = `${offer.sku || offer.providerLabel}, ${formatCount(count)} ${count === 1 ? "price break" : "price breaks"}`;

  return (
    <li>
      <details
        data-dev-id="component-browser.offer-row"
        data-offer-provider={offer.provider}
        className="group min-w-0"
      >
        <summary
          aria-label={detailsLabel}
          className="flex min-h-[48px] cursor-pointer list-none items-center gap-2 px-2 py-1.5 hover:bg-[var(--c-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-inset focus-visible:outline-focus"
        >
          <span className="min-w-0 flex-1">
            <span className="ui-row-primary block truncate" title={offer.sku || undefined}>
              {offer.sku || emptyValue}
            </span>
            <span className="mt-0.5 flex min-w-0 items-baseline gap-2">
              <span className="ui-component-metadata min-w-0 truncate">
                <Text id="component-browser.offer-col-stock">Stock</Text>{" "}
                <span className="ui-numeric text-t2">
                  {offer.stock === null ? stockUnknown : formatCount(offer.stock)}
                </span>
              </span>
              <span className="ui-component-metadata ml-auto flex-none">
                <Text id="component-browser.offer-col-price">Unit Price</Text>{" "}
                <span className="ui-key-fact ui-numeric">
                  {offer.unitPrice === null ? noPrice : formatPrice(offer.unitPrice, offer.currency)}
                </span>
              </span>
            </span>
          </span>
          <Icon
            id="detail.chevron-right"
            className="h-3 w-3 flex-none text-t3 transition-transform group-open:rotate-90"
          />
        </summary>

        <div data-dev-id="component-browser.offer-details" className="border-t border-line/40 bg-field/25 px-2 pb-2 pt-1.5">
          <div className="flex items-center gap-2">
            <h4 className="ui-property-label min-w-0 flex-1">
              <Text id="component-browser.price-breaks">Price Breaks</Text>{" "}
              <span className="font-normal text-t4">{formatCount(count)}</span>
            </h4>
            {offer.offerUrl ? (
              <a
                data-dev-id="component-browser.offer-listing"
                href={offer.offerUrl}
                target="_blank"
                rel="noreferrer"
                aria-label={label}
                title={label}
                className="inline-flex flex-none rounded-control p-0.5 text-t2 hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus"
              >
                <ExternalIcon className="h-3.5 w-3.5" />
              </a>
            ) : null}
          </div>

          <div data-dev-id="component-browser.offer-price-ladder" className="mt-1">
            {offer.priceBreaks.length === 0 ? (
              <p className="ui-component-metadata">{noPrice}</p>
            ) : (
              <dl className="grid min-w-0 grid-cols-2 gap-x-3">
                {offer.priceBreaks.map((entry, index) => (
                  <div
                    key={`${entry.qty}:${entry.price}:${index}`}
                    className="flex min-w-0 items-baseline justify-between gap-2 border-b border-line/40 py-0.5"
                  >
                    <dt className="ui-component-metadata min-w-0 break-words">
                      {entry.qty === null ? emptyValue : formatCount(entry.qty)}
                    </dt>
                    <dd className="ui-key-fact ui-numeric min-w-0 break-words text-right">
                      {entry.price === null ? emptyValue : formatPrice(entry.price, offer.currency)}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </div>

          {hasOfferMetadata(offer, stamp) ? (
            <dl className="mt-2 grid min-w-0 grid-cols-2 gap-x-3 gap-y-1 border-t border-line/40 pt-1.5">
              {offer.currency ? <OfferFact label={<Text id="component-browser.offer-col-currency">Quote Code</Text>}>{offer.currency}</OfferFact> : null}
              {offer.moq !== null ? <OfferFact label={<Text id="component-browser.offer-col-moq">MOQ</Text>} numeric>{formatCount(offer.moq)}</OfferFact> : null}
              {offer.leadTime ? <OfferFact label={<Text id="component-browser.offer-col-lead">Lead Time</Text>}>{offer.leadTime}</OfferFact> : null}
              {offer.factoryLeadTime ? <OfferFact label={<Text id="component-browser.factory-lead-time">Manufacturer Lead Time</Text>}>{offer.factoryLeadTime}</OfferFact> : null}
              {offer.lifecycle ? <OfferFact label={<Text id="component-browser.lifecycle-state">Product Status</Text>}>{offer.lifecycle}</OfferFact> : null}
              {stamp ? (
                <OfferFact label={<Text id="component-browser.offer-col-checked">Last Checked</Text>}>
                  <span title={stamp.title}>
                    {stamp.text}
                    {offer.staleness === "unknown" ? null : <> · <StalenessLabel staleness={offer.staleness} /></>}
                  </span>
                </OfferFact>
              ) : null}
            </dl>
          ) : null}
        </div>
      </details>
    </li>
  );
}

function hasOfferMetadata(offer: DistributorOffer, stamp: ReturnType<typeof formatTimestamp> | null): boolean {
  return Boolean(
    offer.currency
      || offer.moq !== null
      || offer.leadTime
      || offer.factoryLeadTime
      || offer.lifecycle
      || stamp,
  );
}

function OfferFact({
  label,
  numeric = false,
  children,
}: {
  label: ReactNode;
  numeric?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <dt className="ui-property-label break-words">{label}</dt>
      <dd className={`ui-property-value min-w-0 break-words ${numeric ? "ui-numeric" : ""}`}>
        {children}
      </dd>
    </div>
  );
}

function StalenessLabel({ staleness }: { staleness: DistributorOffer["staleness"] }) {
  if (staleness === "fresh") return <Text id="component-browser.staleness-fresh">Fresh</Text>;
  if (staleness === "aging") return <Text id="component-browser.staleness-aging">Aging</Text>;
  if (staleness === "stale") return <Text id="component-browser.staleness-stale">Stale</Text>;
  return <Text id="component-browser.staleness-unknown">Age Unknown</Text>;
}

function SupplyFailures({
  failures,
}: {
  failures: ReadonlyArray<{ provider: string; providerLabel: string; state: string }>;
}) {
  const failureText = useSupplyFailureText();
  return (
    <ul data-dev-id="component-browser.offer-failures" className="flex flex-col">
      {failures.map((failure) => (
        <li key={failure.provider} className="ui-component-metadata border-b border-line/60 px-2 py-1 text-warn">
          {failureText(failure)}
        </li>
      ))}
    </ul>
  );
}

function Spinner(): ReactNode {
  return (
    <span aria-hidden className="inline-block h-2.5 w-2.5 flex-none animate-spin rounded-full border border-t2 border-t-transparent" />
  );
}
