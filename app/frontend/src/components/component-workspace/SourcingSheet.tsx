/**
 * The EXHAUSTIVE sourcing sheet: every offer, every price break, every document and every related
 * part, with the reason each one is here.
 *
 * Provider-neutral by construction. Nothing here reads `catalog.digikey` or any other vendor key -
 * the projection has already turned provider payloads into normalized offers, typed documents and
 * explained relationships, so adding a fifth distributor changes no line in this file.
 *
 * The relationships block is the one that has to be careful. A distributor's "substitution" is a
 * distributor's SUGGESTION. Stockroom has not compared pinouts, packages or ratings, and a row that
 * merely says "Substitutions" invites a person to drop one part in for another on our authority. So
 * every row states its own reason AND states that we have validated nothing - in prose, above and
 * inside the list, not in a tooltip and not only in a comment in the code.
 */
import type {
  DistributorOffer,
  DocumentView,
  RelatedPart,
  SourceLedgerEntry,
} from "../../api/dossierTypes";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { formatCount, formatPrice, formatTimestamp } from "../../lib/formatValue";
import { ExternalIcon } from "../icons";
import { DataTable, EmptyState, Section } from "../primitives";
import { SourceStateBadge } from "./SheetParts";

export function SourcingSheet({
  offers,
  documents,
  relatedParts,
  sources,
}: {
  offers: DistributorOffer[];
  documents: DocumentView[];
  relatedParts: RelatedPart[];
  /** The per-source outcomes, so a distributor that FAILED is not shown as one with no stock. */
  sources: SourceLedgerEntry[];
}) {
  const stockUnknown = useText("component-browser.stock-unknown", "Stock unknown");
  const undated = useText("component-browser.undated", "Undated");
  const emptyValue = useText("component-browser.no-value", "None");
  const priceTableLabel = useText("component-browser.price-ladder", "Price breaks");
  const statesLabel = useText("component-browser.source-states", "Sources");
  const openListing = useCopyFormatter("component-browser.open-listing", "Open {provider} Listing");
  const moqLabel = useCopyFormatter("component-browser.offer-moq", "MOQ {count}");
  const openRelated = useCopyFormatter("component-browser.open-related", "Open {mpn}");
  const notValidated = useText(
    "component-browser.related-not-validated",
    "Stockroom has not checked this for equivalence",
  );
  return (
    <div data-dev-id="component-browser.sourcing-sheet" className="flex flex-col gap-4">
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
              key={`${offer.provider}:${offer.sku}`}
              data-dev-id="component-browser.offer"
              aria-label={`${offer.providerLabel} ${offer.sku}`.trim()}
              className="flex flex-col gap-2 rounded-card border border-line bg-raise px-3 py-2"
            >
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="text-xs font-semibold text-t1">{offer.providerLabel}</span>
                <span className="tnum font-mono text-2xs text-t2">{offer.sku || emptyValue}</span>
                <span className="tnum font-mono text-2xs text-t2">
                  {offer.stock === null ? stockUnknown : formatCount(offer.stock)}
                </span>
                <span className="text-2xs text-t3">
                  {offer.moq === null ? "" : moqLabel({ count: formatCount(offer.moq) })}
                </span>
                <span className="text-2xs text-t3">{offer.leadTime}</span>
                <span className="text-2xs text-t3">
                  {offer.lastCheckedAt ? formatTimestamp(offer.lastCheckedAt).text : undated}
                </span>
                {offer.offerUrl ? (
                  <a
                    href={offer.offerUrl}
                    target="_blank"
                    rel="noreferrer"
                    aria-label={openListing({ provider: offer.providerLabel })}
                    className="ml-auto inline-flex flex-none items-center gap-1 rounded-control px-1 text-2xs text-t2 transition-colors hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
                  >
                    {openListing({ provider: offer.providerLabel })}
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
                  label={`${priceTableLabel} ${offer.providerLabel}`}
                  headings={[
                    <Text key="q" id="component-browser.price-col-qty">
                      Count
                    </Text>,
                    <Text key="p" id="component-browser.price-col-price">
                      Unit Price
                    </Text>,
                  ]}
                >
                  {offer.priceBreaks.map((entry, index) => (
                    <tr key={index} className="border-b border-line/60 last:border-b-0">
                      <td className="tnum px-3 py-1 font-mono">
                        {entry.qty === null ? emptyValue : formatCount(entry.qty)}
                      </td>
                      <td className="tnum px-3 py-1 font-mono">
                        {entry.price === null
                          ? emptyValue
                          : formatPrice(entry.price, offer.currency || "$")}
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
        title="Related Parts"
        copyId="component-browser.relationships-title"
        count={relatedParts.length}
        note={
          <Text id="component-browser.relationships-unvalidated">
            These are suggestions from a distributor. Stockroom has not checked whether these parts
            are interchangeable in circuit or in package with this component, so treat each row as a
            lead to validate rather than a proven replacement.
          </Text>
        }
      >
        {relatedParts.length === 0 ? (
          <EmptyState id="component-browser.relationships-empty">
            No related parts were offered.
          </EmptyState>
        ) : (
          <ul className="rounded-card border border-line bg-raise px-3 py-1">
            {relatedParts.map((part) => (
              <li
                key={`${part.provider}:${part.relation}:${part.mpn}`}
                data-dev-id="component-browser.relationship-item"
                data-related-reason={part.reason}
                className="flex flex-col gap-0.5 border-b border-line/60 py-1.5 last:border-b-0"
              >
                <span className="flex items-baseline gap-2">
                  <span className="tnum flex-none font-mono text-2xs text-t1">
                    {part.mpn || emptyValue}
                  </span>
                  <span
                    className="min-w-0 flex-1 truncate text-2xs text-t3"
                    title={part.description}
                  >
                    {part.description || part.manufacturer}
                  </span>
                  <span className="flex-none text-2xs text-t3">{part.providerLabel}</span>
                  {part.url ? (
                    <a
                      href={part.url}
                      target="_blank"
                      rel="noreferrer"
                      aria-label={openRelated({ mpn: part.mpn })}
                      className="flex-none rounded-control px-1 text-t2 transition-colors hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
                    >
                      <ExternalIcon />
                    </a>
                  ) : null}
                </span>
                <span className="text-2xs text-t3">
                  {[
                    part.reasonLabel,
                    ...part.evidence.map(
                      (item) => `${item.field}: ${item.ours} / ${item.theirs}`,
                    ),
                    notValidated,
                  ].join(" · ")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        title="Documents"
        copyId="component-browser.resources-title"
        count={documents.length}
      >
        {documents.length === 0 ? (
          <EmptyState id="component-browser.resources-empty">
            No documents were offered.
          </EmptyState>
        ) : (
          <ul className="rounded-card border border-line bg-raise px-3 py-1">
            {documents.map((document) => (
              <li
                key={`${document.documentType}:${document.localPath}:${document.remoteUrl}`}
                data-document-type={document.documentType}
                className="flex items-baseline gap-2 border-b border-line/60 py-1.5 last:border-b-0"
              >
                {document.remoteUrl ? (
                  <a
                    data-dev-id="component-browser.resource-link"
                    href={document.remoteUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex min-w-0 flex-1 items-center gap-1 truncate rounded-control text-2xs text-t1 transition-colors hover:text-acc focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-acc"
                  >
                    <span className="truncate">{document.title}</span>
                    <ExternalIcon />
                  </a>
                ) : (
                  <span className="min-w-0 flex-1 truncate text-2xs text-t1">{document.title}</span>
                )}
                <span className="flex-none text-2xs text-t3">{document.documentTypeLabel}</span>
                <span className="flex-none text-2xs text-t3">
                  {document.sourceLabel || document.host}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {/* LAST, and last on purpose. What happened to each source is the explanation behind
          everything above it, and an explanation read before the thing it explains is just a list
          of provider names in front of the numbers a person came for. */}
      <Section
        title="Source Status"
        copyId="component-browser.source-status-title"
        count={sources.length}
        note={
          <Text id="component-browser.source-status-note">
            What happened the last time each source was consulted. A source that failed is not a
            source that supplied data, and it does not mean the part is unavailable.
          </Text>
        }
      >
        {sources.length === 0 ? (
          <EmptyState id="component-browser.source-states-empty">
            No source has been consulted for this component so far.
          </EmptyState>
        ) : (
          <ul aria-label={statesLabel} className="flex flex-col gap-1">
            {sources.map((source) => (
              <li
                key={source.id}
                data-dev-id="component-browser.source-state"
                className="flex items-center gap-2 rounded-card border border-line bg-raise px-3 py-1.5"
              >
                <span className="min-w-0 flex-1 truncate text-2xs text-t1">{source.label}</span>
                <span
                  className="flex-none text-2xs text-t3"
                  title={source.fetchedAt ? formatTimestamp(source.fetchedAt).title : undefined}
                >
                  {source.fetchedAt ? formatTimestamp(source.fetchedAt).text : undated}
                </span>
                <SourceStateBadge state={source.state} />
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
