/**
 * Distributor offers, as a dense table.
 *
 * A table rather than a stack of provider cards, because the question is comparative: who has it,
 * how many, at what price, from what quantity, and how long ago we asked. Cards answer that one
 * provider at a time and make the brand the biggest thing in each of them; a column of tabular
 * figures answers it in one glance and keeps the provider name at the weight a provider name
 * deserves.
 *
 * THE REFRESH IS THE CAREFUL PART. Three rules, all of them because the alternative was visible:
 *
 *   * the table is never blanked. `useRetainedOffers` holds the last non-empty list for as long as
 *     a refresh is running, so a job that momentarily reports nothing cannot wipe the numbers off
 *     the screen. Stale data with its staleness stated beats an empty table every time.
 *   * the column widths do not move. They are declared once in `<colgroup>`, so a spinner
 *     appearing in the toolbar cannot re-measure the price column underneath it.
 *   * a failure attaches to THIS section, above the numbers it failed to update, and never only to
 *     a toast that is gone before the reader looks up.
 */
import { useEffect, useRef, type ReactNode } from "react";
import type { DistributorOffer } from "../../api/dossierTypes";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { formatCount, formatPrice, formatTimestamp } from "../../lib/formatValue";
import { ExternalIcon } from "../icons";
import { EmptyState } from "../primitives";
import { SourcingSection } from "./SourcingParts";
import { volumeBreak } from "./offerFacts";
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
  const tableLabel = useText("component-browser.offers-table", "Distributor offers");
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
        <div data-dev-id="component-browser.offers-table" className="overflow-x-auto">
          <table className="w-full border-collapse" aria-label={tableLabel}>
            {/* Declared once. A refresh cannot re-measure a column that was never measured. */}
            <colgroup>
              <col className="w-[7rem]" />
              <col className="w-[4.5rem]" />
              <col className="w-[5rem]" />
              <col className="w-[7rem]" />
              <col className="w-[3.5rem]" />
              <col className="w-[4rem]" />
              <col className="w-[6rem]" />
              <col className="w-[6rem]" />
              <col className="w-[1.75rem]" />
            </colgroup>
            <thead>
              <tr className="border-b border-line-dark">
                <Heading copyId="component-browser.offer-col-provider">Provider</Heading>
                <Heading copyId="component-browser.offer-col-stock" numeric>
                  Stock
                </Heading>
                <Heading copyId="component-browser.offer-col-price" numeric>
                  Unit Price
                </Heading>
                <Heading copyId="component-browser.offer-col-break" numeric>
                  Price Break
                </Heading>
                <Heading copyId="component-browser.offer-col-currency">Currency</Heading>
                <Heading copyId="component-browser.offer-col-moq" numeric>
                  MOQ
                </Heading>
                <Heading copyId="component-browser.offer-col-lead">Lead Time</Heading>
                <Heading copyId="component-browser.offer-col-checked">Last Checked</Heading>
                <th className="w-[1.75rem]" />
              </tr>
            </thead>
            <tbody>
              {shown.map((offer) => (
                <OfferRow key={`${offer.provider}:${offer.sku}`} offer={offer} />
              ))}
            </tbody>
          </table>
        </div>
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
  const listing = useCopyFormatter("component-browser.open-listing", "Open {provider} Listing");
  const breakText = useCopyFormatter("component-browser.offer-break", "{qty} at {price}");
  const label = listing({ provider: offer.providerLabel });
  const stamp = offer.lastCheckedAt ? formatTimestamp(offer.lastCheckedAt) : null;
  const volume = volumeBreak(offer);
  return (
    <tr
      data-dev-id="component-browser.offer-row"
      data-offer-provider={offer.provider}
      // A REAL GRID. The row carries an alternating tint and every cell a 1px right rule, because
      // eight numeric columns read across without either: a data grid that hides its cells asks the
      // eye to hold a column boundary it cannot see. Both steps are deliberately at the edge of
      // perception - `--c-row-alt` is 1.06:1 off the workspace - so it reads as structure and not
      // as stripes.
      className="border-b border-line/60 last:border-b-0 even:bg-row-alt [&>td]:border-r [&>td]:border-line/50 [&>td:last-child]:border-r-0"
    >
      <td className="px-2 py-1 align-baseline">
        <span className="ui-row-secondary block truncate" title={offer.providerLabel}>
          {offer.providerLabel}
        </span>
        {offer.sku ? (
          <span className="ui-component-metadata block truncate" title={offer.sku}>
            {offer.sku}
          </span>
        ) : null}
      </td>
      <td className="px-2 py-1 align-baseline">
        {offer.stock === null ? (
          <span className="ui-property-value ui-numeric ui-disabled block" title={stockUnknown}>
            {stockUnknown}
          </span>
        ) : (
          <span className="ui-property-value ui-numeric block">{formatCount(offer.stock)}</span>
        )}
      </td>
      <td className="px-2 py-1 align-baseline">
        <span className="ui-key-fact ui-numeric block">
          {offer.unitPrice === null ? "" : formatPrice(offer.unitPrice, offer.currency)}
        </span>
      </td>
      <td className="px-2 py-1 align-baseline">
        <span className="ui-row-metadata ui-numeric block">
          {volume
            ? breakText({
                qty: formatCount(volume.qty),
                price: formatPrice(volume.price, offer.currency),
              })
            : ""}
        </span>
      </td>
      <td className="px-2 py-1 align-baseline">
        <span className="ui-row-metadata block">{offer.currency}</span>
      </td>
      <td className="px-2 py-1 align-baseline">
        <span className="ui-row-metadata ui-numeric block">
          {offer.moq === null ? "" : formatCount(offer.moq)}
        </span>
      </td>
      <td className="px-2 py-1 align-baseline">
        <span className="ui-row-metadata block truncate">{offer.leadTime}</span>
      </td>
      <td className="px-2 py-1 align-baseline">
        {stamp ? (
          <span className="ui-component-metadata block truncate" title={stamp.title}>
            {stamp.text}
          </span>
        ) : null}
      </td>
      <td className="px-2 py-1 align-baseline">
        {offer.offerUrl ? (
          <a
            data-dev-id="component-browser.offer-listing"
            href={offer.offerUrl}
            target="_blank"
            rel="noreferrer"
            aria-label={label}
            title={label}
            className={
              "inline-flex items-center rounded-control p-0.5 text-t2 transition-colors " +
              "hover:text-t1 focus-visible:outline focus-visible:outline-2 " +
              "focus-visible:outline-offset-1 focus-visible:outline-focus"
            }
          >
            <ExternalIcon className="h-3.5 w-3.5" />
          </a>
        ) : null}
      </td>
    </tr>
  );
}

/**
 * One column header. Sentence case, 10/600, and right-aligned when the column below it is.
 *
 * `copyId` rather than `id` because that is this codebase's one prop name for "the copy layer
 * resolves my children", which is what makes the heading rewordable in dev mode like every other
 * string on the surface.
 */
function Heading({
  copyId,
  numeric,
  children,
}: {
  copyId: string;
  numeric?: boolean;
  children: string;
}) {
  return (
    <th
      scope="col"
      className={
        "ui-table-header whitespace-nowrap border-r border-line/50 px-2 py-1 last:border-r-0 " +
        (numeric ? "text-right" : "text-left")
      }
    >
      <Text id={copyId}>{children}</Text>
    </th>
  );
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
