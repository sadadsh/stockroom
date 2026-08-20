import type { ReactNode } from "react";
import type {
  DistributorOffer,
  DocumentView,
  RelatedPart,
  SourceLedgerEntry,
  SupplySummaryView,
} from "../../api/dossierTypes";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { formatCount, formatPrice, formatTimestamp } from "../../lib/formatValue";
import { Icon } from "../Icon";
import type { IconId } from "../../lib/iconRegistry";
import { ExternalIcon, WarnIcon } from "../icons";
import { EmptyState, StatusText } from "../primitives";
import { SourceStateBadge } from "./SheetParts";
import { groupOffersByProvider, type OfferGroup } from "./offerFacts";

export function SourcingSheet({
  offers,
  documents,
  relatedParts,
  sources,
  supplySummary,
}: {
  offers: DistributorOffer[];
  documents: DocumentView[];
  relatedParts: RelatedPart[];
  sources: SourceLedgerEntry[];
  supplySummary: SupplySummaryView;
}) {
  const groups = groupOffersByProvider(offers);
  const stockUnknown = useText("component-browser.stock-unknown", "Not reported");
  const relatedWarning = useText(
    "component-browser.relationships-unvalidated",
    "Distributor suggestions are not verified replacements. Check pinout, package, ratings, and circuit behavior before using one.",
  );
  const statesLabel = useText("component-browser.source-states", "Sources");

  return (
    <div data-dev-id="component-browser.sourcing-sheet" className="flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-x-6 gap-y-3 px-1 py-1 lg:grid-cols-4">
        <SummaryMetric
          label={<Text id="component-browser.offers-title">Offers</Text>}
          value={formatCount(supplySummary.offerCount)}
        />
        <SummaryMetric
          label={<Text id="component-browser.total-stock">Total Stock</Text>}
          value={supplySummary.totalStock === null ? stockUnknown : formatCount(supplySummary.totalStock)}
        />
        <SummaryMetric
          label={<Text id="component-browser.documents-title">Documents</Text>}
          value={formatCount(documents.length)}
        />
        <SummaryMetric
          label={<Text id="component-browser.related-title">Related Parts</Text>}
          value={formatCount(relatedParts.length)}
        />
      </div>

      <RecordSection
        label="Distributor Offers"
        title={<Text id="component-browser.offers-title">Distributor Offers</Text>}
        icon="detail.offers"
        count={offers.length}
      >
        {groups.length === 0 ? (
          <EmptyState dense id="component-browser.sourcing-empty">
            No distributor offers on record.
          </EmptyState>
        ) : (
          <div className="flex flex-col gap-3 p-3">
            {groups.map((group) => (
              <ProviderOfferGroup key={group.provider || group.providerLabel} group={group} />
            ))}
          </div>
        )}
      </RecordSection>

      <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-2">
        <RecordSection
          label="Documents"
          title={<Text id="component-browser.documents-title">Documents</Text>}
          icon="detail.datasheet-link"
          count={documents.length}
        >
          {documents.length === 0 ? (
            <EmptyState dense id="component-browser.resources-empty">
              No documents were offered.
            </EmptyState>
          ) : (
            <ul className="divide-y divide-line/60">
              {documents.map((document) => (
                <DocumentRow key={document.id} document={document} />
              ))}
            </ul>
          )}
        </RecordSection>

        <RecordSection
          label="Related Parts"
          title={<Text id="component-browser.related-title">Related Parts</Text>}
          icon="nav.components"
          count={relatedParts.length}
        >
          {relatedParts.length === 0 ? (
            <EmptyState dense id="component-browser.relationships-empty">
              No related parts were offered.
            </EmptyState>
          ) : (
            <>
              <p
                id="sourcing-related-warning"
                className="flex items-start gap-1.5 bg-field/35 px-3 py-2 text-2xs leading-relaxed text-t2"
              >
                <WarnIcon className="mt-0.5 h-3 w-3 flex-none" />
                {relatedWarning}
              </p>
              <ul aria-describedby="sourcing-related-warning" className="divide-y divide-line/60">
                {relatedParts.map((part) => (
                  <RelatedPartRow
                    key={`${part.provider}:${part.relation}:${part.mpn}`}
                    part={part}
                  />
                ))}
              </ul>
            </>
          )}
        </RecordSection>
      </div>

      <RecordSection
        label="Source Status"
        title={<Text id="component-browser.source-status-title">Source Status</Text>}
        icon="status.info"
        count={sources.length}
      >
        {sources.length === 0 ? (
          <EmptyState dense id="component-browser.source-states-empty">
            No source has been consulted for this component so far.
          </EmptyState>
        ) : (
          <ul aria-label={statesLabel} className="grid grid-cols-1 lg:grid-cols-2">
            {sources.map((source, index) => (
              <SourceRow key={source.id} source={source} index={index} />
            ))}
          </ul>
        )}
      </RecordSection>
    </div>
  );
}

function SummaryMetric({ label, value }: { label: ReactNode; value: string }) {
  return (
    <div className="min-w-0 py-1.5">
      <div className="ui-property-label truncate">{label}</div>
      <div className="ui-key-fact ui-numeric mt-0.5 truncate text-sm">{value}</div>
    </div>
  );
}

function RecordSection({
  label,
  title,
  icon,
  count,
  children,
}: {
  label: string;
  title: ReactNode;
  icon: IconId;
  count: number;
  children: ReactNode;
}) {
  return (
    <section aria-label={label} className="min-w-0 overflow-hidden">
      <header className="flex min-h-[32px] items-center gap-2 border-b border-line px-1 py-1.5">
        <Icon id={icon} className="h-3.5 w-3.5 flex-none text-t3" />
        <h2 className="ui-section-title min-w-0 truncate">{title}</h2>
        <span className="ui-component-metadata ml-auto flex-none tabular-nums">{formatCount(count)}</span>
      </header>
      {children}
    </section>
  );
}

function ProviderOfferGroup({ group }: { group: OfferGroup }) {
  const offersLabel = group.offers.length === 1 ? "offer" : "offers";
  return (
    <section
      data-sourcing-provider={group.provider}
      aria-label={group.providerLabel}
      className="min-w-0 overflow-hidden"
    >
      <header className="flex items-center gap-2 bg-field/25 px-3 py-2">
        <h3 className="ui-row-primary min-w-0 flex-1 truncate">{group.providerLabel}</h3>
        <span className="ui-component-metadata flex-none">
          {formatCount(group.offers.length)} {offersLabel}
        </span>
      </header>
      <div className="divide-y divide-line/60">
        {group.offers.map((offer) => (
          <OfferDisclosure key={`${offer.provider}:${offer.sku}`} offer={offer} />
        ))}
      </div>
    </section>
  );
}

function OfferDisclosure({ offer }: { offer: DistributorOffer }) {
  const stockUnknown = useText("component-browser.stock-unknown", "Stock not reported");
  const noPrice = useText("component-browser.no-price", "No price");
  const emptyValue = useText("component-browser.no-value", "None");
  const undated = useText("component-browser.undated", "Undated");
  const openListing = useCopyFormatter("component-browser.open-listing", "Open {provider} Listing");
  const priceTableLabel = useText("component-browser.price-ladder", "Price breaks");
  const stamp = offer.lastCheckedAt ? formatTimestamp(offer.lastCheckedAt) : null;
  const count = offer.priceBreaks.length;
  const countLabel = `${formatCount(count)} ${count === 1 ? "price break" : "price breaks"}`;
  const quote = offer.unitPrice === null ? noPrice : formatPrice(offer.unitPrice, offer.currency);

  return (
    <details
      data-dev-id="component-browser.offer"
      data-offer-provider={offer.provider}
      aria-label={`${offer.providerLabel} ${offer.sku}`.trim()}
      className="group"
    >
      <summary className="flex min-h-[46px] cursor-pointer list-none flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2 hover:bg-[var(--c-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-inset focus-visible:outline-focus">
        <span className="min-w-[12rem] flex-1">
          <span className="ui-row-primary block break-all">{offer.sku || emptyValue}</span>
          <span className="ui-component-metadata block">{countLabel}</span>
        </span>
        <SummaryFact
          label={<Text id="component-browser.offer-col-stock">Stock</Text>}
          value={offer.stock === null ? stockUnknown : formatCount(offer.stock)}
        />
        <SummaryFact
          label={<Text id="component-browser.offer-col-price">Unit Price</Text>}
          value={quote}
          emphasis
        />
        <Icon
          id="detail.chevron-right"
          className="h-3.5 w-3.5 flex-none text-t3 transition-transform group-open:rotate-90"
        />
      </summary>

      <div className="bg-raise px-3 pb-3 pt-2.5">
        <div className="mb-3 flex flex-wrap items-start gap-x-5 gap-y-2">
          {offer.currency ? (
            <OfferMeta label={<Text id="component-browser.offer-col-currency">Quote Code</Text>}>
              {offer.currency}
            </OfferMeta>
          ) : null}
          {offer.moq !== null ? (
            <OfferMeta label={<Text id="component-browser.offer-col-moq">MOQ</Text>}>
              {formatCount(offer.moq)}
            </OfferMeta>
          ) : null}
          {offer.leadTime ? (
            <OfferMeta label={<Text id="component-browser.offer-col-lead">Lead Time</Text>}>
              {offer.leadTime}
            </OfferMeta>
          ) : null}
          {offer.factoryLeadTime ? (
            <OfferMeta label={<Text id="component-browser.factory-lead-time">Manufacturer Lead Time</Text>}>
              {offer.factoryLeadTime}
            </OfferMeta>
          ) : null}
          {offer.lifecycle ? (
            <OfferMeta label={<Text id="component-browser.lifecycle-state">Product Status</Text>}>
              {offer.lifecycle}
            </OfferMeta>
          ) : null}
          <OfferMeta label={<Text id="component-browser.offer-col-checked">Last Checked</Text>}>
            <span title={stamp?.title}>{stamp?.text ?? undated}</span>
          </OfferMeta>
          {offer.offerUrl ? (
            <a
              href={offer.offerUrl}
              target="_blank"
              rel="noreferrer"
              aria-label={openListing({ provider: offer.providerLabel })}
              className="ml-auto inline-flex flex-none items-center gap-1 rounded-control text-2xs font-medium text-t2 hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            >
              {openListing({ provider: offer.providerLabel })}
              <ExternalIcon className="h-3.5 w-3.5" />
            </a>
          ) : null}
        </div>

        {offer.priceBreaks.length === 0 ? (
          <p className="ui-component-metadata">{noPrice}</p>
        ) : (
          <table
            data-dev-id="component-browser.offer-ladder"
            className="w-full table-fixed text-2xs"
            aria-label={`${priceTableLabel} ${offer.providerLabel}`}
          >
            <thead>
              <tr className="border-y border-line/60 text-t3">
                <th scope="col" className="px-2 py-1 text-left font-medium">
                  <Text id="component-browser.price-col-qty">Count</Text>
                </th>
                <th scope="col" className="px-2 py-1 text-right font-medium">
                  <Text id="component-browser.price-col-price">Unit Price</Text>
                </th>
              </tr>
            </thead>
            <tbody>
              {offer.priceBreaks.map((entry, index) => (
                <tr key={`${entry.qty}:${entry.price}:${index}`} className="border-b border-line/40 last:border-b-0">
                  <td className="ui-numeric px-2 py-1 text-left text-t2">
                    {entry.qty === null ? emptyValue : formatCount(entry.qty)}
                  </td>
                  <td className="ui-key-fact ui-numeric px-2 py-1 text-right">
                    {entry.price === null ? emptyValue : formatPrice(entry.price, offer.currency)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </details>
  );
}

function SummaryFact({
  label,
  value,
  emphasis = false,
}: {
  label: ReactNode;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <span className="min-w-[5.5rem] flex-none text-right">
      <span className="ui-property-label block">{label}</span>
      <span className={`${emphasis ? "ui-key-fact" : "ui-property-value"} ui-numeric block`}>
        {value}
      </span>
    </span>
  );
}

function OfferMeta({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <span className="min-w-[7rem]">
      <span className="ui-property-label block">{label}</span>
      <span className="ui-property-value block break-words">{children}</span>
    </span>
  );
}

function DocumentRow({ document }: { document: DocumentView }) {
  const openDocument = useCopyFormatter("component-browser.open-document", "Open {title}");
  const stamp = document.retrievedAt ? formatTimestamp(document.retrievedAt) : null;
  const metadata = [
    document.documentTypeLabel,
    document.revision,
    document.sourceLabel || document.host,
    stamp?.text,
  ].filter(Boolean).join(" · ");
  const url = document.remoteUrl;
  return (
    <li data-document-type={document.documentType} className="flex min-w-0 items-start gap-2 px-3 py-2">
      <span className="min-w-0 flex-1">
        <span className="ui-row-secondary block break-words">{document.title}</span>
        {metadata ? <span className="ui-component-metadata block break-words" title={stamp?.title}>{metadata}</span> : null}
      </span>
      <StatusText tone={document.status === "verified" ? "ok" : document.status === "unreachable" ? "err" : "neutral"} className="flex-none">
        <DocumentStatus document={document} />
      </StatusText>
      {url ? (
        <a
          data-dev-id="component-browser.resource-link"
          href={url}
          target="_blank"
          rel="noreferrer"
          aria-label={openDocument({ title: document.title })}
          className="inline-flex flex-none rounded-control p-0.5 text-t2 hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        >
          <ExternalIcon className="h-3.5 w-3.5" />
        </a>
      ) : null}
    </li>
  );
}

function DocumentStatus({ document }: { document: DocumentView }) {
  if (document.status === "verified") return <Text id="component-browser.document-verified">Verified</Text>;
  if (document.status === "stored") return <Text id="component-browser.document-stored">Stored</Text>;
  if (document.status === "referenced") return <Text id="component-browser.document-referenced">Referenced</Text>;
  return <Text id="component-browser.document-unreachable">Unavailable</Text>;
}

function RelatedPartRow({ part }: { part: RelatedPart }) {
  const emptyValue = useText("component-browser.no-value", "None");
  const openRelated = useCopyFormatter("component-browser.open-related", "Open {mpn}");
  const content = (
    <>
      <span className="min-w-0 flex-1">
        <span className="ui-row-primary block truncate" title={part.mpn}>{part.mpn || emptyValue}</span>
        <span className="ui-component-metadata block break-words">
          {[part.reasonLabel, part.manufacturer, part.providerLabel].filter(Boolean).join(" · ")}
        </span>
      </span>
      {part.url ? (
        <a
          href={part.url}
          target="_blank"
          rel="noreferrer"
          aria-label={openRelated({ mpn: part.mpn })}
          className="inline-flex flex-none rounded-control p-0.5 text-t2 hover:text-t1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        >
          <ExternalIcon className="h-3.5 w-3.5" />
        </a>
      ) : null}
    </>
  );

  if (part.evidence.length === 0) {
    return (
      <li data-dev-id="component-browser.relationship-item" data-related-reason={part.reason} className="flex items-start gap-2 px-3 py-2">
        {content}
      </li>
    );
  }

  return (
    <li data-dev-id="component-browser.relationship-item" data-related-reason={part.reason}>
      <details className="group">
        <summary className="flex cursor-pointer list-none items-start gap-2 px-3 py-2 hover:bg-[var(--c-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-inset focus-visible:outline-focus">
          {content}
          <Icon id="detail.chevron-right" className="mt-0.5 h-3 w-3 flex-none text-t3 transition-transform group-open:rotate-90" />
        </summary>
        <dl className="grid grid-cols-1 gap-x-4 gap-y-1 bg-field/25 px-3 py-2 sm:grid-cols-2">
          {part.evidence.map((item) => (
            <div key={`${item.field}:${item.ours}:${item.theirs}`} className="min-w-0">
              <dt className="ui-property-label break-words">{item.field}</dt>
              <dd className="ui-component-metadata flex items-center gap-1 break-words">
                <span>{item.ours}</span>
                <Icon id="relation.transition" className="h-3 w-3 flex-none" />
                <span>{item.theirs}</span>
              </dd>
            </div>
          ))}
        </dl>
      </details>
    </li>
  );
}

function SourceRow({ source, index }: { source: SourceLedgerEntry; index: number }) {
  const undated = useText("component-browser.undated", "Undated");
  const stamp = source.fetchedAt ? formatTimestamp(source.fetchedAt) : null;
  return (
    <li
      data-dev-id="component-browser.source-state"
      className={`flex min-w-0 items-center gap-3 border-b border-line/60 px-3 py-2 ${index % 2 === 0 ? "lg:border-r" : ""}`}
    >
      <span className="min-w-0 flex-1">
        <span className="ui-row-secondary block truncate">{source.label}</span>
        <span className="ui-component-metadata block truncate" title={stamp?.title}>
          {formatCount(source.fieldCount)} fields · {stamp?.text ?? undated}
        </span>
      </span>
      <SourceStateBadge state={source.state} />
    </li>
  );
}
