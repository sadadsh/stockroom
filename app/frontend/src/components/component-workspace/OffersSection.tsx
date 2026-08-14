/**
 * Every normalized distributor offer, as one wrapping ledger per provider.
 *
 * The Sourcing column is intentionally narrow. A wide comparison table hid most facts behind a
 * horizontal scrollbar and reduced each price ladder to one break. The ledger keeps every offer
 * and every break in the normal vertical reading flow, while two-column fact grids preserve useful
 * comparison without creating a second scroll axis.
 *
 * Refresh never blanks the last known numbers, and a source failure stays attached above the data
 * it failed to update rather than disappearing with a toast.
 */
import { useEffect, useRef, type ReactNode } from "react";
import type { DistributorOffer } from "../../api/dossierTypes";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { formatCount, formatPrice, formatTimestamp } from "../../lib/formatValue";
import { ExternalIcon } from "../icons";
import { EmptyState } from "../primitives";
import { SourcingSection } from "./SourcingParts";
import { useSupplyFailureText } from "./provenanceText";

/**
 * The offers to render right now.
 *
 * While a refresh is running the last non-empty list stands. That is the whole rule: a refresh
 * that empties the table before repopulating it looks exactly like a part no distributor carries,
 * and the reader has no way to tell the difference until it comes back - if it comes back.
 */
export function useRetainedOffers(
  offers: readonly DistributorOffer[],
  refreshing: boolean,
): readonly DistributorOffer[] {
  const held = useRef<readonly DistributorOffer[]>(offers);
  useEffect(() => {
    // Only a non-empty answer replaces what is held, and only while nothing is in flight. An
    // empty list that arrives once the refresh has finished is a real answer and is kept.
    if (!refreshing) held.current = offers;
  }, [offers, refreshing]);
  if (!refreshing) return offers;
  return offers.length > 0 ? offers : held.current;
}

export function OffersSection({
  offers,
  failures,
  onRefresh,
  refreshing,
}: {
  offers: readonly DistributorOffer[];
  failures: ReadonlyArray<{ provider: string; providerLabel: string; state: string }>;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const refreshLabel = useText("component-browser.refresh-offers", "Refresh Offers");
  const refreshingLabel = useText("component-browser.refreshing-offers", "Refreshing...");
  const ledgerLabel = useText("component-browser.offers-table", "Distributor offers");
  const shown = useRetainedOffers(offers, refreshing);

  return (
    <SourcingSection
      devId="component-browser.offers"
      title={<Text id="component-browser.offers-title">Distributor Offers</Text>}
      action={
        // A REFRESH GLYPH, which is one of the handful of genuinely universal ones, carrying the
        // complete action name as its tooltip and its accessible name. The word `Offers` was on the
        // control AND on the heading two centimetres to its left, so the control was restating its
        // own container. It keeps a fixed 22px box so the heading row cannot jump when the glyph
        // becomes a spinner, and `Refreshing...` is still announced through `aria-label`.
        <button
          type="button"
          data-dev-id="component-browser.refresh-offers"
          aria-busy={refreshing || undefined}
          aria-label={refreshing ? refreshingLabel : refreshLabel}
          title={refreshing ? refreshingLabel : refreshLabel}
          disabled={refreshing}
          onClick={onRefresh}
          className={
            "flex h-[20px] w-[20px] flex-none items-center justify-center rounded-control " +
            "text-t3 hover:bg-control-hover hover:text-t1 disabled:text-t5 " +
            "disabled:hover:bg-transparent focus-visible:outline focus-visible:outline-2 " +
            "focus-visible:outline-offset-1 focus-visible:outline-focus"
          }
        >
          {refreshing ? <Spinner /> : <RefreshGlyph />}
        </button>
      }
    >
      {/* Above the numbers, never instead of them. */}
      {failures.length > 0 ? <SupplyFailures failures={failures} /> : null}
      {shown.length === 0 ? (
        <EmptyState dense id="component-browser.offers-empty">
          No distributor has quoted this component.
        </EmptyState>
      ) : (
        <ul
          data-dev-id="component-browser.offers-table"
          aria-label={ledgerLabel}
          className="flex min-w-0 flex-col"
        >
          {shown.map((offer) => (
            <OfferRow key={`${offer.provider}:${offer.sku}`} offer={offer} />
          ))}
        </ul>
      )}
    </SourcingSection>
  );
}

/**
 * One distributor's offer.
 *
 * The provider names the row, but the ENGINEERING data outweighs the brand: the counts and the
 * prices are tabular and right-aligned so a column of them compares at a glance, and the action
 * names its destination - `Open Mouser Listing`, never "Product Page" four times over.
 */
function OfferRow({ offer }: { offer: DistributorOffer }) {
  const stockUnknown = useText("component-browser.stock-unknown", "Stock unknown");
  const unknown = useText("component-browser.value-unknown", "Unknown");
  const noPrice = useText("component-browser.no-price", "No price");
  const listing = useCopyFormatter("component-browser.open-listing", "Open {provider} Listing");
  const label = listing({ provider: offer.providerLabel });
  const stamp = offer.lastCheckedAt ? formatTimestamp(offer.lastCheckedAt) : null;

  return (
    <li
      data-dev-id="component-browser.offer-row"
      data-offer-provider={offer.provider}
      className="min-w-0 border-b border-line/60 px-2 py-2 last:border-b-0 even:bg-row-alt/50"
    >
      <header className="flex min-w-0 flex-wrap items-start gap-x-2 gap-y-1">
        <span className="ui-row-secondary min-w-0 flex-1 break-words text-t1">
          {offer.providerLabel}
        </span>
        {offer.offerUrl ? (
          <a
            data-dev-id="component-browser.offer-listing"
            href={offer.offerUrl}
            target="_blank"
            rel="noreferrer"
            aria-label={label}
            title={label}
            className={
              "inline-flex flex-none items-center rounded-control p-0.5 text-t2 transition-colors " +
              "hover:text-t1 focus-visible:outline focus-visible:outline-2 " +
              "focus-visible:outline-offset-1 focus-visible:outline-focus"
            }
          >
            <ExternalIcon className="h-3.5 w-3.5" />
          </a>
        ) : null}
        <span className="ui-component-metadata basis-full break-all" title={offer.sku || undefined}>
          {offer.sku || unknown}
        </span>
      </header>

      <dl className="mt-2 grid min-w-0 grid-cols-2 gap-x-3 gap-y-2">
        <OfferFact label={<Text id="component-browser.offer-col-stock">Stock</Text>} numeric>
          {offer.stock === null ? stockUnknown : formatCount(offer.stock)}
        </OfferFact>
        <OfferFact label={<Text id="component-browser.offer-col-price">Unit Price</Text>} numeric emphasis>
          {offer.unitPrice === null ? noPrice : formatPrice(offer.unitPrice, offer.currency)}
        </OfferFact>
        <OfferFact label={<Text id="component-browser.offer-col-currency">Quote Code</Text>}>
          {offer.currency || unknown}
        </OfferFact>
        <OfferFact label={<Text id="component-browser.offer-col-moq">MOQ</Text>} numeric>
          {offer.moq === null ? unknown : formatCount(offer.moq)}
        </OfferFact>
        <OfferFact label={<Text id="component-browser.offer-col-lead">Lead Time</Text>}>
          {offer.leadTime || unknown}
        </OfferFact>
        <OfferFact label={<Text id="component-browser.factory-lead-time">Manufacturer Lead Time</Text>}>
          {offer.factoryLeadTime || unknown}
        </OfferFact>
        <OfferFact label={<Text id="component-browser.lifecycle-state">Product Status</Text>}>
          {offer.lifecycle || unknown}
        </OfferFact>
        <OfferFact label={<Text id="component-browser.offer-col-checked">Last Checked</Text>}>
          {stamp ? (
            <span title={stamp.title}>
              {stamp.text} · <StalenessLabel staleness={offer.staleness} />
            </span>
          ) : unknown}
        </OfferFact>
      </dl>

      <div data-dev-id="component-browser.offer-price-ladder" className="mt-2 min-w-0 border-t border-line/60 pt-2">
        <h4 className="ui-property-label">
          <Text id="component-browser.price-breaks">Price Breaks</Text>
        </h4>
        {offer.priceBreaks.length === 0 ? (
          <p className="ui-component-metadata mt-1">{noPrice}</p>
        ) : (
          <dl className="mt-1 grid min-w-0 grid-cols-2 gap-x-3 gap-y-1">
            {offer.priceBreaks.map((entry, index) => (
              <div
                key={`${entry.qty ?? "unknown"}:${entry.price ?? "unknown"}:${index}`}
                className="flex min-w-0 items-baseline justify-between gap-2 border-b border-line/40 py-0.5"
              >
                <dt className="ui-component-metadata min-w-0 break-words">
                  {entry.qty === null ? unknown : formatCount(entry.qty)}
                </dt>
                <dd className="ui-key-fact ui-numeric min-w-0 break-words text-right">
                  {entry.price === null ? noPrice : formatPrice(entry.price, offer.currency)}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </li>
  );
}

function OfferFact({
  label,
  numeric = false,
  emphasis = false,
  children,
}: {
  label: ReactNode;
  numeric?: boolean;
  emphasis?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <dt className="ui-property-label break-words">{label}</dt>
      <dd
        className={
          `${emphasis ? "ui-key-fact" : "ui-property-value"} min-w-0 break-words ` +
          (numeric ? "ui-numeric" : "")
        }
      >
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

/**
 * A source that could not be read, NAMED, above the numbers it failed to update.
 *
 * The sentence is chosen by the state rather than having the state pasted into it: "digikey could
 * not be read (not_configured)" showed a person two storage identifiers and called it an
 * explanation. Each state now has its own sentence and its own implied next step.
 */
function SupplyFailures({
  failures,
}: {
  failures: ReadonlyArray<{ provider: string; providerLabel: string; state: string }>;
}) {
  const failureText = useSupplyFailureText();
  return (
    <ul data-dev-id="component-browser.offer-failures" className="flex flex-col">
      {failures.map((failure) => (
        <li
          key={failure.provider}
          className="ui-component-metadata border-b border-line/60 px-2 py-1 text-warn"
        >
          {failureText(failure)}
        </li>
      ))}
    </ul>
  );
}

/** A circular arrow: refresh, and one of the few glyphs that needs no label beside it. */
function RefreshGlyph(): ReactNode {
  return (
    <svg
      viewBox="0 0 16 16"
      aria-hidden
      className="h-3.5 w-3.5"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M13.5 8a5.5 5.5 0 1 1-1.9-4.2" />
      <path d="M13.5 2v3h-3" />
    </svg>
  );
}

/** The one loading mark: the control keeps its size and swaps its icon. Nothing scales. */
function Spinner(): ReactNode {
  return (
    <span
      aria-hidden
      className="inline-block h-2.5 w-2.5 flex-none animate-spin rounded-full border border-t2 border-t-transparent"
    />
  );
}
