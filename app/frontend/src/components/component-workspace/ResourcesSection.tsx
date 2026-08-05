/**
 * Documents and related parts: the complete record of what has been written about this component,
 * and what else might do the job.
 *
 * DOCUMENTS is the whole list, not a datasheet button. The header's Datasheet action is a shortcut
 * to the one copy a person usually wants; this is where the package drawing, the application
 * notes, the PCN / PDN and the compliance declarations live, because a part is not only its
 * datasheet and a reader looking for an errata sheet must not have to guess.
 *
 * Every row's subject is the document's TITLE. A raw URL is never a name - it is where the bytes
 * are, not what they say - and a local filename is never the title when a real one exists, because
 * `lm358.pdf` is a fact about our disk and "LM358 Dual Operational Amplifier" is a fact about the
 * part. The filename stays, one tier down, where it answers "which file is this".
 *
 * RELATED PARTS each state WHY. `Same function, different package` is information; an unexplained
 * "related" row asks the reader to work out for themselves whether it is the same die in another
 * body, a faster logic family, a reel instead of a cut tape, or a cross-sell - and those have
 * completely different consequences for a board. Every row also states that Stockroom has checked
 * nothing about electrical or mechanical equivalence, because a suggestion that reads as an
 * endorsement is how a wrong part reaches a fabricator.
 */
import type { DocumentView, RelatedPart } from "../../api/dossierTypes";
import { Text, useCopyFormatter, useText } from "../../lib/copy";
import { formatTimestamp } from "../../lib/formatValue";
import { ExternalIcon } from "../icons";
import { Button, EmptyState, StatusText } from "../primitives";
import { SourcingSection } from "./SourcingParts";

export function DocumentsSection({
  documents,
  preferredReason,
  onOpenDocument,
}: {
  documents: readonly DocumentView[];
  /** Why THIS copy is the one the header opens. An explanation, and also the next action. */
  preferredReason: string;
  onOpenDocument: (id: string) => void;
}) {
  return (
    <SourcingSection
      devId="component-browser.documents"
      title={<Text id="component-browser.documents-title">Documents</Text>}
    >
      {documents.length === 0 ? (
        <EmptyState dense id="component-browser.documents-empty">
          No document has been recorded for this component.
        </EmptyState>
      ) : (
        <>
          {preferredReason ? (
            <p
              data-dev-id="component-browser.preferred-datasheet-reason"
              className="ui-component-metadata px-2 py-1"
            >
              <Text
                id="component-browser.preferred-datasheet-reason"
                values={{ reason: preferredReason }}
              >
                {"Opening the {reason}"}
              </Text>
            </p>
          ) : null}
          {documents.map((item) => (
            // Addressed by the projection's derived id, never by list position: an index means
            // something different the moment an enrichment lands, and a viewer opened on index 2
            // would fetch a different document with nothing having failed.
            <DocumentRow
              key={item.id}
              document={item}
              onOpen={() => onOpenDocument(item.id)}
            />
          ))}
        </>
      )}
    </SourcingSection>
  );
}

/**
 * One document.
 *
 * The title is what the document IS; the revision and the source describe it; the retrieval
 * metadata and the filename sit behind both. Three tiers, in that order, every row.
 */
function DocumentRow({ document, onOpen }: { document: DocumentView; onOpen: () => void }) {
  const openLabel = useCopyFormatter("component-browser.open-document", "Open {title}");
  const currentLabel = useText("component-browser.document-current", "Current");
  const label = openLabel({ title: document.title });
  const stamp = document.retrievedAt ? formatTimestamp(document.retrievedAt) : null;
  // Revision, publisher and currency: what distinguishes this copy from another copy of the same
  // document. The type label leads because it is what the reader is scanning for.
  const detail = [
    document.documentTypeLabel,
    document.revision,
    document.manufacturer,
    document.sourceLabel,
    document.isCurrent ? currentLabel : "",
  ]
    .filter(Boolean)
    .join(" · ");
  // Tertiary. The filename answers "which file is this", and only that.
  const filename = document.localPath.split("/").pop() ?? "";
  return (
    <div
      data-dev-id="component-browser.document-row"
      data-document-type={document.documentType}
      data-document-preferred={document.isPreferred ? "true" : "false"}
      className="flex min-h-[26px] items-baseline gap-2 border-b border-line/60 px-2 py-1 last:border-b-0"
    >
      <span className="min-w-0 flex-1">
        <span className="ui-row-secondary block break-words" title={document.title}>
          {document.title}
        </span>
        {detail ? <span className="ui-component-metadata block break-words">{detail}</span> : null}
        {stamp || filename ? (
          <span className="ui-component-metadata block truncate" title={stamp?.title}>
            {[stamp?.text, filename].filter(Boolean).join(" · ")}
          </span>
        ) : null}
      </span>
      <StatusText tone={documentTone(document)} className="flex-none">
        <DocumentStatusLabel document={document} />
      </StatusText>
      {document.localPath || document.remoteUrl ? (
        <Button
          small
          data-dev-id="component-browser.document-open"
          aria-label={label}
          title={label}
          onClick={onOpen}
        >
          <Text id="component-browser.document-open">Open</Text>
        </Button>
      ) : null}
    </div>
  );
}

/** Semantic colour only where it means something: held and checked, held, referenced, gone. */
export function documentTone(document: DocumentView): "ok" | "warn" | "err" | "neutral" {
  if (document.status === "verified") return "ok";
  if (document.status === "unreachable") return "err";
  return "neutral";
}

function DocumentStatusLabel({ document }: { document: DocumentView }) {
  if (document.status === "verified")
    return <Text id="component-browser.document-verified">Verified</Text>;
  if (document.status === "stored")
    return <Text id="component-browser.document-stored">Stored</Text>;
  if (document.status === "referenced")
    return <Text id="component-browser.document-referenced">Referenced</Text>;
  return <Text id="component-browser.document-unreachable">Unavailable</Text>;
}

export function RelatedPartsSection({ parts }: { parts: readonly RelatedPart[] }) {
  return (
    <SourcingSection
      devId="component-browser.related"
      title={<Text id="component-browser.related-title">Related Parts</Text>}
    >
      {parts.length === 0 ? (
        <EmptyState dense id="component-browser.related-empty">
          No distributor has suggested a related part.
        </EmptyState>
      ) : (
        parts.map((part) => (
          <RelatedPartRow key={`${part.provider}:${part.relation}:${part.mpn}`} part={part} />
        ))
      )}
    </SourcingSection>
  );
}

/**
 * One related part, and why it is related.
 *
 * The reason is the projection's, derived from normalized differences rather than copied from a
 * distributor's label, and the evidence behind it is shown as the fields that differ. `validated`
 * is always false and is always said out loud.
 */
function RelatedPartRow({ part }: { part: RelatedPart }) {
  const notValidated = useText(
    "component-browser.related-not-validated",
    "Not checked for equivalence by Stockroom",
  );
  const openLabel = useCopyFormatter("component-browser.open-related", "Open {mpn}");
  return (
    <div
      data-dev-id="component-browser.related-row"
      data-related-reason={part.reason}
      data-related-validated={part.validated ? "true" : "false"}
      className="flex items-baseline gap-2 border-b border-line/60 px-2 py-1 last:border-b-0"
    >
      <span className="min-w-0 flex-1">
        <span className="ui-row-primary block truncate" title={part.mpn}>
          {part.mpn || part.description}
        </span>
        <span className="ui-component-metadata block break-words">
          {[part.reasonLabel, part.manufacturer, part.providerLabel].filter(Boolean).join(" · ")}
        </span>
        {part.evidence.length > 0 ? (
          <span
            data-dev-id="component-browser.related-evidence"
            className="ui-component-metadata block break-words"
          >
            {part.evidence
              .map((item) => `${item.field}: ${item.ours} → ${item.theirs}`)
              .join(" · ")}
          </span>
        ) : null}
        <span
          data-dev-id="component-browser.related-not-validated"
          className="ui-component-metadata block break-words text-t3"
        >
          {notValidated}
        </span>
      </span>
      {part.url ? (
        <a
          href={part.url}
          target="_blank"
          rel="noreferrer"
          aria-label={openLabel({ mpn: part.mpn })}
          title={openLabel({ mpn: part.mpn })}
          className={
            "inline-flex flex-none items-center rounded-control p-0.5 text-t2 transition-colors " +
            "hover:text-t1 focus-visible:outline focus-visible:outline-2 " +
            "focus-visible:outline-offset-1 focus-visible:outline-focus"
          }
        >
          <ExternalIcon className="h-3.5 w-3.5" />
        </a>
      ) : null}
    </div>
  );
}
