/**
 * THE ISSUES LIST: one call, one ordered list, four layers under it.
 *
 * Plan 1.4 describes a single surface - "the issues list renders live in edit mode, stays
 * inspectable outside it, and ships with the committed layout" - so the editor, the panel and the
 * commit pipeline all want ONE function and one stable order. This is that function. It owns no
 * checks of its own; it composes four modules and sorts what they return.
 *
 *   STRUCTURE, part one: `validateLayout` (document.ts), unchanged and not re-derived. Its
 *   three-tier grading is folded into this model's two by `fromLayoutIssue`, with the original tier
 *   kept in `detail.tier`. Included by default because a panel that showed design warnings and
 *   silently dropped "this slot holds nothing" would be the more dishonest of the two lists.
 *
 *   STRUCTURE, part two: `validateStructure`, the registry-aware remainder - a piece below the floor
 *   its own manifest states, a scroll axis two placed pieces both own.
 *
 *   REACHABILITY: `validateReachability`, every action the build can perform against every action
 *   the arrangement exposes.
 *
 *   VISIBILITY: `validateContrast`, measured over whichever palettes the caller supplies - the
 *   shipped defaults outside edit mode, a live draft while the style panel is open.
 *
 * PROVENANCE, and exactly how much of it exists. Plan 1.4's fourth category is informational
 * entries, and it names two:
 *
 *   AUTO-PLACEMENTS are PHASE 5. Decision 6 says a piece shipped into an already-redesigned layout
 *   places itself from its manifest's home hints and the placement is RECORDED here, which is the
 *   mitigation that makes a non-blocking update discoverable. The auto-placer does not exist, so
 *   there are no records - and this module does not invent any. What it defines is the SHAPE
 *   (`AutoPlacementRecord`) and the severity (`info`), passed in through `options.provenance`, so
 *   that when the auto-placer lands it has somewhere to put its output and no part of the panel
 *   changes. A caller that passes nothing gets nothing: the list is honest about being empty.
 *
 *   STYLE-ROLE EXCEPTIONS are derived, not recorded, because the document already holds them. A
 *   placement carrying `styleRoles` IS the "only here" scope the style panel writes (plan 1.5), so
 *   reading them back out is reporting what the document says rather than remembering what an editor
 *   did. The shipped default document sets none, which is why the shipped list has no info rows.
 */
import type { LayoutDocument, PiecePlacement } from "./document";
import { layoutPlacements, validateLayout } from "./document";
import type { PieceManifest } from "./registry";
import { validateContrast, shippedThemeTokens, type ContrastPairing, type ThemeTokens } from "./validateContrast";
import { validateReachability } from "./validateReachability";
import { validateStructure } from "./validateStructure";
import {
  fromLayoutIssue,
  sortIssues,
  validatorIssue,
  type ValidatorIssue,
} from "./validatorIssues";

/**
 * Everything the composed validator asks of a registry.
 *
 * The union of what the three registry-aware layers need, declared structurally so a test can hand
 * this a literal and `PieceRegistry` satisfies it without either module importing the other.
 */
export interface ValidationRegistry {
  has(id: string): boolean;
  get(id: string): PieceManifest | undefined;
  list(): readonly PieceManifest[];
}

/**
 * One auto-placement, as the Phase 5 placer will record it.
 *
 * Every field is a string, because this travels with a draft and with a commit through JSON, like
 * the document itself. `at` is an ISO-8601 instant rather than a number so a committed record reads
 * as a date in a diff.
 */
export interface AutoPlacementRecord {
  /** The piece that placed itself. */
  piece: string;
  /** The region its manifest's home hint named. */
  regionId: string;
  /** The slot it landed in, where the placer created one. */
  slotId?: string;
  /** The sibling group the hint kept it inside. */
  siblingGroup?: string;
  /** When, ISO-8601. */
  at?: string;
}

export interface ValidateDocumentOptions {
  /**
   * Auto-placement records since the arrangement was last edited. Phase 5 produces these; nothing
   * in this module fabricates one, and an absent list means an empty list rather than an unknown.
   */
  provenance?: readonly AutoPlacementRecord[];
  /** Measure a different pairing table, for a scoped or a test-time measurement. */
  pairings?: readonly ContrastPairing[];
  /**
   * Fold `validateLayout`'s structural findings in. Default true.
   *
   * The escape hatch exists for a caller that already renders that list separately - not as a way to
   * make the list shorter, which is why it defaults the other way.
   */
  includeLayoutIssues?: boolean;
}

/**
 * Everything wrong, or worth saying, about this arrangement - in one stable order.
 *
 * The order is `compareIssues`: severity, then code, then subject, then position. Stable in the
 * strong sense - the same document, registry and palettes produce a byte-identical list every time -
 * because a committed layout's issues ship with it and a list that reshuffled would make every
 * commit look like a change to its own known issues.
 */
export function validateDocument(
  document: LayoutDocument,
  registry: ValidationRegistry,
  themes: readonly ThemeTokens[] = shippedThemeTokens(),
  options: ValidateDocumentOptions = {},
): ValidatorIssue[] {
  const issues: ValidatorIssue[] = [];

  if (options.includeLayoutIssues !== false) {
    for (const issue of validateLayout(document, registry)) issues.push(fromLayoutIssue(issue));
  }

  issues.push(...validateReachability(document, registry));
  issues.push(...validateStructure(document, registry));
  issues.push(...validateContrast(document, themes, { pairings: options.pairings }));
  issues.push(...provenanceIssues(document, options.provenance ?? []));

  return sortIssues(issues);
}

/* -------------------------------------------------------------------------- */
/*  provenance                                                                 */
/* -------------------------------------------------------------------------- */

/**
 * The informational layer: what a later build did, and what the owner scoped to one instance.
 *
 * Exported on its own so the panel can draw the two provenance groups apart from the warnings
 * without re-running the measurements.
 */
export function provenanceIssues(
  document: LayoutDocument,
  records: readonly AutoPlacementRecord[],
): ValidatorIssue[] {
  const issues: ValidatorIssue[] = [];

  for (const record of records) {
    issues.push(
      validatorIssue(
        "auto-placed",
        { kind: "piece", id: record.piece },
        {
          detail: {
            region: record.regionId,
            ...(record.slotId ? { slot: record.slotId } : {}),
            ...(record.siblingGroup ? { group: record.siblingGroup } : {}),
            ...(record.at ? { at: record.at } : {}),
          },
        },
      ),
    );
  }

  for (const visit of layoutPlacements(document)) {
    const placement: PiecePlacement = visit.node;
    const roles = placement.styleRoles;
    if (!roles) continue;
    const names = Object.keys(roles).sort();
    if (names.length === 0) continue;
    issues.push(
      validatorIssue(
        "style-role-exception",
        { kind: "placement", id: placement.id },
        {
          path: visit.path,
          detail: { piece: placement.piece, roles: names.join(" ") },
        },
      ),
    );
  }

  return issues;
}
