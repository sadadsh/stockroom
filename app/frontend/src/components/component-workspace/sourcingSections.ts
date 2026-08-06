/**
 * Which sourcing sections have something in them, and whether the empty ones are on screen.
 *
 * THE PROBLEM THIS SOLVES. A component nobody has sourced rendered a full sentence per empty
 * section, and there are eight of them: "No distributor has quoted this component.", "No document
 * has been recorded for this component.", "No source has been consulted for this component yet.",
 * "No source disagrees with another about this component.", "Nobody has overridden a value on this
 * component.", "Nothing is recorded about how this component's data arrived.", "Nothing has changed
 * since this component was created.", "No distributor has suggested a related part." Measured on a
 * seeded capacitor at 1600x900, that was most of the column: paragraphs of prose where there is no
 * information, which is a large part of why the three columns read as uneven.
 *
 * So a section with no content is NOT RENDERED, and one control reveals every one of them. The
 * information stays reachable - "what has nobody told us about this part" is a real question and
 * the reveal answers it exactly - it simply stops being the loudest thing in the column.
 *
 * THE DECISIONS, and why each went the way it did:
 *
 *   PER COLUMN, not global. The Specifications column deliberately renders an expected field that
 *   nobody supplied, as a `Missing` row, because a gap in a specification IS the datum there. One
 *   switch governing both would either delete that or fail to help here.
 *
 *   PERSISTED, in local browser storage, under the same mechanism the column splitters already
 *   use. It is a workstation habit ("I want to see the gaps") rather than a property of a library,
 *   so it does not belong in the durable UI session that travels with one - and it is the storage
 *   that is already here, not a new one.
 *
 *   LIFECYCLE NEVER COLLAPSES. Its five rows read Unknown when nothing has been checked, and
 *   "nobody has checked" is information about the part. `Last Checked: Unknown` is the fact that
 *   sends someone to Refresh Offers; deleting it would hide the reason the rest is empty. So the
 *   column is never blank, whatever else is hidden, and the reveal control names a COUNT rather
 *   than standing alone in an empty panel.
 */
import type { ComponentDossier } from "../../api/dossierTypes";

/** The five sections that can be empty, in the column's fixed order. Lifecycle is not one. */
export type SourcingSectionId =
  | "offers"
  | "pricing"
  | "documents"
  | "related"
  | "provenance";

export const COLLAPSIBLE_SOURCING_SECTIONS: readonly SourcingSectionId[] = [
  "offers",
  "pricing",
  "documents",
  "related",
  "provenance",
];

export type SourcingSectionFill = Record<SourcingSectionId, boolean>;

/**
 * Which sections have content, read off the projection.
 *
 * Each rule names the thing that would be worth reading, never "is the array non-empty" for its
 * own sake:
 *
 *   offers      a quote, or a NAMED failure. "DigiKey could not be read" is content: it is the
 *               difference between a part nobody sells and a source nobody could reach.
 *   pricing     any of the three facts it states. Unlike lifecycle it carries no "last checked",
 *               so three Unknown rows here are three restatements of the empty offers table.
 *   documents   one document of any type.
 *   related     one suggested part.
 *   provenance  a consulted source, a disagreement, a reviewed decision, a dated event, or a
 *               compatibility notice. Developer mode adds Technical Diagnostics, which is always
 *               content - so the section stands whenever the storage readout is being shown.
 */
export function sourcingSectionFill(
  dossier: ComponentDossier,
  developerMode: boolean,
): SourcingSectionFill {
  const { supplySummary, distributorOffers, documents, relatedParts, provenance } = dossier;
  const priceBreaks = distributorOffers.reduce(
    (total, offer) => total + offer.priceBreaks.length,
    0,
  );
  return {
    offers: distributorOffers.length > 0 || supplySummary.failures.length > 0,
    pricing:
      supplySummary.bestUnitPrice !== null ||
      priceBreaks > 0 ||
      supplySummary.factoryLeadTime !== "",
    documents: documents.items.length > 0,
    related: relatedParts.length > 0,
    provenance:
      developerMode ||
      provenance.compatibility.hasNotice ||
      provenance.sources.length > 0 ||
      provenance.conflicts.length > 0 ||
      provenance.manualOverrides.length > 0 ||
      dossier.revisions.length > 0,
  };
}

/** The sections with nothing in them, in the column's fixed order. */
export function emptySourcingSections(fill: SourcingSectionFill): SourcingSectionId[] {
  return COLLAPSIBLE_SOURCING_SECTIONS.filter((id) => !fill[id]);
}

/**
 * Nothing has been sourced for this component AT ALL: no offer, no price, no document, no related
 * part, no provenance. The column holds the five lifecycle rows and the reveal control, and nothing
 * else, whatever it is given room for.
 *
 * This is what the column's WIDTH is decided from (`lib/workspaceColumns`). It is read off the
 * projection rather than off the reveal toggle deliberately: the width should follow what the
 * component HAS, not what the reader has currently chosen to look at, so turning the blank sections
 * on to audit the gaps does not also reshape the workspace - and turning them off again does not
 * reshape it back.
 */
export function sourcingIsSparse(fill: SourcingSectionFill): boolean {
  return COLLAPSIBLE_SOURCING_SECTIONS.every((id) => !fill[id]);
}

export const SOURCING_EMPTY_STORAGE_KEY = "stockroom.component-workspace.sourcing-empty.v1";

/**
 * Whether this machine wants the empty sections on screen. Absent means no.
 *
 * Every storage failure is swallowed, exactly as the splitter fractions do: a browser that refuses
 * local storage must render the column at its default, not fail to render it.
 */
export function readShowEmptySections(): boolean {
  try {
    return window.localStorage.getItem(SOURCING_EMPTY_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function writeShowEmptySections(show: boolean): void {
  try {
    window.localStorage.setItem(SOURCING_EMPTY_STORAGE_KEY, show ? "true" : "false");
  } catch {
    /* A browser that refuses storage still gets a working column. */
  }
}
