/**
 * The EXHAUSTIVE sourcing sheet: every offer, every price break, and everything a distributor
 * said ABOUT the part that is not an electrical specification.
 *
 * Provider-neutral by construction. Nothing here reads `catalog.digikey` or any other vendor key -
 * the projection has already turned provider payloads into offers, shared trade facts, related
 * parts and resources, so adding a fifth distributor changes no line in this file.
 *
 * The relationships block is the one that has to be careful. A distributor's "substitution" is a
 * distributor's SUGGESTION. Stockroom has not compared pinouts, packages, ratings or anything else,
 * and a row that merely says "Substitutions" invites a person to drop one part in for another on
 * our authority. So the group is labelled as unvalidated, in prose, above the list - not in a
 * tooltip, and not only in a comment in the code.
 */
import type {
  ComponentSourcingView,
  SourceRecordView,
  SourcingOfferView,
} from "../../api/workspaceTypes";
import { Text, useText } from "../../lib/copy";
import { ExternalIcon } from "../icons";
import { DataTable, EmptyState, Section } from "../primitives";
import { SourceNote, SourceStateBadge } from "./SheetParts";

/** The lowest quoted unit price, or nothing. Never an interpolated "from" price nobody quoted. */
export function lowestPrice(offer: SourcingOfferView): number | null {
  const prices = offer.priceBreaks
    .map((entry) => entry.price)
    .filter((price): price is number => price != null);
  return prices.length === 0 ? null : Math.min(...prices);
}

export function SourcingSheet({
  sourcing,
  sourceRecords,
}: {
  sourcing: ComponentSourcingView;
  /** The per-source outcomes, so a distributor that FAILED is not shown as one with no stock. */
  sourceRecords: SourceRecordView[];
}) {
  const { offers, shared, relationships, resources } = sourcing;
  const stockUnknown = useText("component-browser.stock-unknown", "Stock unknown");
  const undated = useText("component-browser.undated", "Undated");
  const emptyValue = useText("component-browser.no-value", "None");
  const priceTableLabel = useText("component-browser.price-ladder", "Price breaks");
  const statesLabel = useText("component-browser.source-states", "Sources");
  const openLabel = useText("component-browser.offer-open", "Open Product Page");

  return (
    <div data-dev-id="component-browser.sourcing-sheet" className="flex flex-col gap-4">
      <Section
        title="Source Status"
        copyId="component-browser.source-status-title"
        count={sourceRecords.length}
        note={
          <Text id="component-browser.source-status-note">
            What happened the last time each source was consulted. A source that failed is not a
            source that answered and does not carry this part.
          </Text>
        }
      >
        {sourceRecords.length === 0 ? (
          <EmptyState id="component-browser.source-states-empty">
            No source has been consulted for this component yet.
          </EmptyState>
        ) : (
          <ul aria-label={statesLabel} className="flex flex-col gap-1">
            {sourceRecords.map((record) => (
              <li
                key={record.id}
                data-dev-id="component-browser.source-state"
                className="flex items-center gap-2 rounded-card border border-line bg-raise px-3 py-1.5"
              >
                <span className="min-w-0 flex-1 truncate text-2xs text-t1">{record.label}</span>
                <span className="flex-none text-2xs text-t3">{record.fetchedAt || undated}</span>
                <SourceStateBadge state={record.state} />
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        title="Distributor Offers"
        copyId="component-browser.offers-title"
        count={offers.length}
      >
        {offers.length === 0 ? (
          <EmptyState id="component-browser.sourcing-empty">
            No distributor offers on record.
          </EmptyState>
        ) : (
          offers.map((offer) => (
            <article
              key={`${offer.sourceId}:${offer.partNumber}`}
              data-dev-id="component-browser.offer"
              aria-label={`${offer.sourceLabel || offer.sourceId} ${offer.partNumber}`.trim()}
              className="flex flex-col gap-2 rounded-card border border-line bg-raise px-3 py-2"
            >
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="text-xs font-semibold text-t1">
                  {offer.sourceLabel || offer.sourceId}
                </span>
                <span className="tnum font-mono text-2xs text-t2">
                  {offer.partNumber || emptyValue}
                </span>
                <span className="tnum font-mono text-2xs text-t2">
                  {offer.stock === null ? stockUnknown : offer.stock.toLocaleString()}
                </span>
                <span className="text-2xs text-t3">{offer.currency}</span>
                <span className="text-2xs text-t3">{offer.fetchedAt || undated}</span>
                {offer.url ? (
                  <a
                    href={offer.url}
                    target="_blank"
                    rel="noreferrer"
                    aria-label={`${openLabel} ${offer.sourceLabel || offer.sourceId}`}
                    className="ml-auto inline-flex flex-none items-center gap-1 rounded-control px-1 text-2xs text-t2 transition-colors hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
                  >
                    <Text id="component-browser.offer-open">Open Product Page</Text>
                    <ExternalIcon />
                  </a>
                ) : null}
              </div>
              {offer.priceBreaks.length === 0 ? (
                <p className="text-2xs text-t3">
                  <Text id="component-browser.no-price">No price</Text>
                </p>
              ) : (
                <DataTable
                  devId="component-browser.offer-ladder"
                  label={`${priceTableLabel} ${offer.sourceLabel || offer.sourceId}`}
                  headings={[
                    <Text key="q" id="component-browser.price-col-qty">
                      Quantity
                    </Text>,
                    <Text key="p" id="component-browser.price-col-price">
                      Unit Price
                    </Text>,
                  ]}
                >
                  {offer.priceBreaks.map((entry, index) => (
                    <tr key={index} className="border-b border-line/60 last:border-b-0">
                      <td className="tnum px-3 py-1 font-mono">{entry.qty ?? emptyValue}</td>
                      <td className="tnum px-3 py-1 font-mono">
                        {entry.price == null
                          ? emptyValue
                          : `${offer.currency || ""}${entry.price.toFixed(4)}`}
                      </td>
                    </tr>
                  ))}
                </DataTable>
              )}
            </article>
          ))
        )}
      </Section>

      <Section
        title="Trade And Compliance"
        copyId="component-browser.shared-title"
        count={shared.length}
      >
        {shared.length === 0 ? (
          <EmptyState id="component-browser.shared-empty">
            No lifecycle, lead time, origin or compliance facts on record.
          </EmptyState>
        ) : (
          <ul
            data-dev-id="component-browser.sourcing-shared"
            className="rounded-card border border-line bg-raise px-3 py-1"
          >
            {shared.map((fact) => (
              <li
                key={fact.id}
                className="flex items-baseline gap-2 border-b border-line/60 py-1.5 last:border-b-0"
              >
                <span className="min-w-0 flex-1 truncate text-2xs text-t2">{fact.label}</span>
                <span className="tnum flex-none font-mono text-2xs text-t1">
                  {fact.formattedValue || emptyValue}
                </span>
                <SourceNote source={fact.source} />
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        title="Related Parts"
        copyId="component-browser.relationships-title"
        count={relationships.reduce((total, group) => total + group.count, 0)}
        note={
          <Text id="component-browser.relationships-unvalidated">
            These are suggestions published by a distributor. Stockroom has not checked that any of
            them is electrically or mechanically interchangeable with this component, so treat every
            row as a lead to verify rather than a proven replacement.
          </Text>
        }
      >
        {relationships.length === 0 ? (
          <EmptyState id="component-browser.relationships-empty">
            No related parts were offered.
          </EmptyState>
        ) : (
          relationships.map((group) => (
            <div
              key={group.id}
              data-dev-id="component-browser.relationship-group"
              className="flex flex-col gap-1"
            >
              <h3 className="text-2xs font-semibold text-t2">
                {`${group.label} (${group.count})`}
              </h3>
              <ul className="rounded-card border border-line bg-raise px-3 py-1">
                {group.items.map((item, index) => (
                  <li
                    key={`${item.sourceId}:${item.mpn}:${index}`}
                    data-dev-id="component-browser.relationship-item"
                    className="flex items-baseline gap-2 border-b border-line/60 py-1.5 last:border-b-0"
                  >
                    <span className="tnum flex-none font-mono text-2xs text-t1">
                      {item.mpn || emptyValue}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-2xs text-t3" title={item.description}>
                      {item.description || item.manufacturer}
                    </span>
                    <span className="flex-none text-2xs text-t3">
                      {item.sourceLabel || item.sourceId}
                    </span>
                    {item.url ? (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noreferrer"
                        aria-label={`${openLabel} ${item.mpn}`}
                        className="flex-none rounded-control px-1 text-t2 transition-colors hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
                      >
                        <ExternalIcon />
                      </a>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ))
        )}
      </Section>

      <Section
        title="Documents"
        copyId="component-browser.resources-title"
        count={resources.length}
      >
        {resources.length === 0 ? (
          <EmptyState id="component-browser.resources-empty">
            No documents were offered.
          </EmptyState>
        ) : (
          <ul className="rounded-card border border-line bg-raise px-3 py-1">
            {resources.map((resource) => (
              <li
                key={`${resource.sourceId}:${resource.url}`}
                className="flex items-baseline gap-2 border-b border-line/60 py-1.5 last:border-b-0"
              >
                <a
                  data-dev-id="component-browser.resource-link"
                  href={resource.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex min-w-0 flex-1 items-center gap-1 truncate rounded-control text-2xs text-t1 transition-colors hover:text-acc focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
                >
                  <span className="truncate">{resource.title}</span>
                  <ExternalIcon />
                </a>
                <span className="flex-none text-2xs text-t3">
                  {resource.sourceLabel || resource.sourceId}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
