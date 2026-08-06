/**
 * Which document the Datasheet action opens, and what the menu behind it offers.
 *
 * The PREFERRED datasheet is not re-derived here. The projection ranks the copies - a verified
 * local manufacturer PDF beats an official manufacturer URL beats a verified imported PDF beats a
 * trusted distributor copy - and it also sends the REASON it chose, which is what turns a link into
 * an explanation ("you are seeing a distributor's copy because the manufacturer's own PDF is not on
 * file"). Recomputing the winner on the client would be a second ranking that disagrees with the
 * first the moment a rule changes.
 *
 * What this module decides is presentation: how a document is OPENED, which is a different question
 * from which one wins. A stored file is opened from the library's own bytes; a PDF that exists only
 * as a URL is fetched from that URL; an HTML product page is not a PDF at all and is opened
 * externally rather than shown in a pane that would never render it.
 */
import type { DocumentView, DocumentsView } from "../../api/dossierTypes";

/**
 * How a document can be opened.
 *
 *   file      stored bytes the library holds, fetched through the documents endpoint
 *   remote    a PDF that exists only as a URL
 *   page      an HTML resource - a product page, not a document, and never a PDF pane
 *   none      nothing to open, which is a real answer and not a disabled button
 */
export type DatasheetOpenKind = "file" | "remote" | "page" | "none";

export interface DatasheetTarget {
  /**
   * The document's own stable id, which is how the file endpoint addresses it.
   *
   * Deliberately not a list position. The list can change between the render and the click - an
   * enrichment landing, a revision arriving - and a position would then name a different document
   * while looking like it worked.
   */
  id: string;
  document: DocumentView;
  kind: DatasheetOpenKind;
}

/**
 * How this document should be opened.
 *
 * A stored file wins over a URL for the same document: the bytes are on this machine, they load
 * without a network round trip, and they are the copy whose digest was checked. `datasheet_page`
 * is an HTML resource whatever else it carries.
 */
export function openKindFor(document: DocumentView): DatasheetOpenKind {
  if (document.documentType === "datasheet_page") return "page";
  if (document.localPath) return "file";
  if (!document.remoteUrl) return "none";
  const isPdf =
    document.mimeType.toLowerCase().includes("pdf") ||
    /\.pdf(\?|#|$)/i.test(document.remoteUrl);
  return isPdf ? "remote" : "page";
}

function target(document: DocumentView): DatasheetTarget {
  return { id: document.id, document, kind: openKindFor(document) };
}

/**
 * The document the primary Datasheet action opens, or `null` when there is none.
 *
 * Matched by id, so a response that was cloned through a structural copy still resolves to the
 * same document, and so does one whose list order changed.
 */
export function preferredTarget(documents: DocumentsView): DatasheetTarget | null {
  const preferred = documents.preferredDatasheet;
  if (!preferred) return null;
  const found = documents.items.find((item) => item.id === preferred.id);
  return found ? target(found) : target(preferred);
}

/**
 * The other revisions of the preferred datasheet - the same document, superseded.
 *
 * A revision is another copy of the same document family, so it is matched on type and title
 * rather than on being "a datasheet somewhere in the list". A package drawing is not a revision of
 * a datasheet and must not appear under one.
 */
export function revisionTargets(documents: DocumentsView): DatasheetTarget[] {
  const preferred = preferredTarget(documents);
  if (!preferred) return [];
  const family = preferred.document;
  return documents.items
    .map(target)
    .filter(
      (item) =>
        item.id !== preferred.id &&
        item.document.documentType === family.documentType &&
        item.document.title.trim().toLowerCase() === family.title.trim().toLowerCase(),
    );
}

/** Every other document: drawings, application notes, PCN / PDN, compliance declarations. */
export function otherDocumentTargets(documents: DocumentsView): DatasheetTarget[] {
  const preferred = preferredTarget(documents);
  const revisions = new Set(revisionTargets(documents).map((item) => item.id));
  return documents.items
    .map(target)
    .filter(
      (item) => item.id !== preferred?.id && !revisions.has(item.id) && item.kind !== "none",
    );
}

/** A revision reads as its revision string, or as its retrieval date when it carries none. */
export function revisionLabel(document: DocumentView): string {
  if (document.revision.trim()) return document.revision.trim();
  return document.retrievedAt.slice(0, 10);
}
