/**
 * THE ISSUES LIST'S OWN VOCABULARY: what a validator is allowed to say, and how it says it.
 *
 * Plan 1.4 is one sentence with a lot of weight in it - "a pure function over (layout document,
 * registries) producing the issues list" - and the load-bearing word is LIST. The editor never
 * refuses an edit (plan decision 3: warn, never block), so the entire consequence of a problem is
 * that a row appears here. That makes the row's shape the contract, and this module is that shape.
 *
 * Four properties this module exists to guarantee:
 *
 *   NOTHING BLOCKS, SO NOTHING IS AN ERROR. The severity ladder is two rungs, `warning` and `info`,
 *   and neither one gates anything. `document.ts`'s `validateLayout` still grades its own structural
 *   findings on a three-rung ladder that includes `error`, because those are defects in a DOCUMENT
 *   rather than judgements about a DESIGN; `fromLayoutIssue` below folds that ladder into this one
 *   and keeps the original tier in `detail.tier` so nothing is lost in the fold.
 *
 *   NO PROSE. An issue carries a COPY ID and a fallback, never a sentence the panel prints as-is.
 *   Interface text lives in the copy layer, which is what makes it rewordable in Dev Mode and what
 *   makes the letter rule enforceable; a validator that returned "Delete Component is unreachable"
 *   as a string would be authoring interface text inside a data module. The fallback exists for the
 *   same reason every `<Text>` call site carries one - so a missing id degrades to readable text
 *   rather than to a blank row - and it obeys the letter rule to the letter.
 *
 *   THE SUBJECT IS AN ID, NOT A NAME. "Delete Component is unreachable" is the canonical warning in
 *   the plan, and what this module produces for it is `{ kind: "action", id:
 *   "component-browser.delete" }`. The panel resolves the id to a label; the validator never does,
 *   because the validator runs in the commit pipeline where there is no copy layer and no locale.
 *
 *   ONE TOTAL ORDER. `compareIssues` is a total order over the whole model, so the same document
 *   validated twice produces the same list in the same sequence - which is what lets a committed
 *   layout's known issues be diffed rather than re-read (plan 1.4: a committed layout's issues ship
 *   with it).
 */
import type { LayoutIssue, LayoutIssueCode } from "./document";

/* -------------------------------------------------------------------------- */
/*  severity                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * Two rungs, and the distinction is about WHO the row is for.
 *
 * `warning` is a claim about the design: something the owner arranged is now unreachable, unreadable
 * or too small for what it holds. `info` is a claim about the HISTORY of the design: a piece a later
 * build placed automatically, a pairing nobody could measure. Neither refuses anything.
 */
export type IssueSeverity = "warning" | "info";

/** Panel order, and the first key of `compareIssues`. */
export const ISSUE_SEVERITY_ORDER: readonly IssueSeverity[] = ["warning", "info"];

/* -------------------------------------------------------------------------- */
/*  codes                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * What this validator can find, over and above what `validateLayout` already reports.
 *
 * Each one names a question a STRUCTURAL check cannot answer, because each needs something the
 * document alone does not hold: the registry's action declarations, the resolved token values, or a
 * record of what a later build did without being asked.
 */
export type ValidatorIssueCode =
  /** No placed, visible piece declares this action, so nothing on screen can reach it. */
  | "action-unreachable"
  /** A text pairing measures below the floor a word has to clear to be read. */
  | "contrast-below-text-floor"
  /** A mark, or a tier the design holds to the large-text floor, measures below that floor. */
  | "contrast-below-non-text-floor"
  /** A pairing could not be measured at all: a value is absent, or is not an opaque colour. */
  | "contrast-not-measured"
  /** The room a piece is given is smaller than the minimum its own manifest states. */
  | "piece-below-minimum"
  /** Two placed pieces in one region own the same scroll axis that region stacks them along. */
  | "piece-scroll-conflict"
  /** Provenance: a later build placed this piece from its manifest hints. Informational. */
  | "auto-placed"
  /** Provenance: this placement carries a style role scoped to itself alone. Informational. */
  | "style-role-exception";

/** Every code the composed list can carry: this module's own, plus the structural layer's. */
export type IssueCode = ValidatorIssueCode | LayoutIssueCode;

/* -------------------------------------------------------------------------- */
/*  subjects                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * What an issue is ABOUT, as an identifier the interface can resolve.
 *
 * Every variant carries `id`, so ordering and de-duplication work over the whole model without a
 * switch. `token-pair` carries its three parts separately as well, because the panel wants to draw
 * two swatches and a theme name rather than to re-split a string.
 */
export type IssueSubject =
  | { kind: "document"; id: string }
  | { kind: "region"; id: string }
  | { kind: "slot"; id: string }
  | { kind: "placement"; id: string }
  | { kind: "piece"; id: string }
  | { kind: "action"; id: string }
  | { kind: "splitter"; id: string }
  | {
      kind: "token-pair";
      /** `<theme>:<ink>:<surface>`, so one string names the pairing. */
      id: string;
      theme: string;
      /** The CSS variable the text or the mark is drawn in. */
      ink: string;
      /** The CSS variable it is drawn on. */
      surface: string;
    };

export type IssueSubjectKind = IssueSubject["kind"];

/** Subject kinds in panel order: the document, then the tree, then what the tree exposes. */
const SUBJECT_KIND_ORDER: readonly IssueSubjectKind[] = [
  "document",
  "region",
  "slot",
  "placement",
  "piece",
  "action",
  "splitter",
  "token-pair",
];

/** One string that names a subject, for ordering and for de-duplication. */
export function subjectKey(subject: IssueSubject): string {
  return `${subject.kind}:${subject.id}`;
}

/** The token-pair subject, built so its `id` is derived rather than typed twice. */
export function tokenPairSubject(
  theme: string,
  ink: string,
  surface: string,
): IssueSubject {
  return { kind: "token-pair", id: `${theme}:${ink}:${surface}`, theme, ink, surface };
}

/* -------------------------------------------------------------------------- */
/*  copy                                                                       */
/* -------------------------------------------------------------------------- */

/**
 * The copy id a row renders through, and the text it degrades to.
 *
 * THE FALLBACKS OBEY THE LETTER RULE. `lib/interfaceTerms.ts` states it and
 * `copy.letterRule.test.ts` enforces it against the shapes copy is written in; a data table in a
 * `.ts` module is not one of those shapes, so the gate would not catch a slip here. `validatorIssues
 * .test.ts` therefore checks every fallback in this table itself, which is the honest way to be
 * bound by a rule the automatic gate cannot see.
 */
export interface IssueCopy {
  id: string;
  fallback: string;
}

const COPY_NAMESPACE = "layout-issues";

/** Every code's copy id and fallback. Exhaustive by type: a new code cannot skip this table. */
export const ISSUE_COPY: Readonly<Record<IssueCode, IssueCopy>> = {
  "action-unreachable": {
    id: `${COPY_NAMESPACE}.action-unreachable`,
    fallback: "No placed piece exposes this action.",
  },
  "contrast-below-text-floor": {
    id: `${COPY_NAMESPACE}.contrast-below-text-floor`,
    fallback: "Text on this surface is beneath the contrast floor a word answers to.",
  },
  "contrast-below-non-text-floor": {
    id: `${COPY_NAMESPACE}.contrast-below-non-text-floor`,
    fallback: "This pairing is beneath the contrast floor a mark or a supplemental tier answers to.",
  },
  "contrast-not-measured": {
    id: `${COPY_NAMESPACE}.contrast-not-measured`,
    fallback: "This pairing was not measured: a token value is absent or cannot be read.",
  },
  "piece-below-minimum": {
    id: `${COPY_NAMESPACE}.piece-below-minimum`,
    fallback: "This piece has less room than its manifest states as a minimum.",
  },
  "piece-scroll-conflict": {
    id: `${COPY_NAMESPACE}.piece-scroll-conflict`,
    fallback: "Two placed pieces scroll one axis in the same region.",
  },
  "auto-placed": {
    id: `${COPY_NAMESPACE}.auto-placed`,
    fallback: "A new piece was placed from its own manifest hints.",
  },
  "style-role-exception": {
    id: `${COPY_NAMESPACE}.style-role-exception`,
    fallback: "This placement holds a role set for this one instance alone.",
  },
  "unsupported-schema-version": {
    id: `${COPY_NAMESPACE}.unsupported-schema-version`,
    fallback: "This document names a schema this build does not read.",
  },
  "unknown-layout-mode": {
    id: `${COPY_NAMESPACE}.unknown-arrangement-mode`,
    fallback: "This region names an arrangement mode that does not exist.",
  },
  "duplicate-id": {
    id: `${COPY_NAMESPACE}.duplicate-id`,
    fallback: "Two nodes share one id.",
  },
  "orphan-slot": {
    id: `${COPY_NAMESPACE}.orphan-slot`,
    fallback: "This slot holds nothing.",
  },
  "unknown-piece": {
    id: `${COPY_NAMESPACE}.unknown-piece`,
    fallback: "No registered piece answers to this id.",
  },
  "splitter-unknown-slot": {
    id: `${COPY_NAMESPACE}.splitter-unknown-slot`,
    fallback: "This splitter names a slot the region does not hold.",
  },
  "scroll-owner-conflict": {
    id: `${COPY_NAMESPACE}.scroll-owner-conflict`,
    fallback: "Two regions scroll one axis in the same parent.",
  },
};

/**
 * The severity each of THIS module's codes carries.
 *
 * Structural codes are not in the table: they arrive already graded by `validateLayout`, and
 * `fromLayoutIssue` folds that grade rather than overruling it.
 */
export const VALIDATOR_ISSUE_SEVERITY: Readonly<Record<ValidatorIssueCode, IssueSeverity>> = {
  "action-unreachable": "warning",
  "contrast-below-text-floor": "warning",
  "contrast-below-non-text-floor": "warning",
  // NOT a warning. "I could not measure this" is a statement about the validator's inputs, not a
  // finding about the design, and grading it as a warning would put a row the owner cannot act on
  // in the same tier as a pairing that genuinely fails.
  "contrast-not-measured": "info",
  "piece-below-minimum": "warning",
  "piece-scroll-conflict": "warning",
  "auto-placed": "info",
  "style-role-exception": "info",
};

/* -------------------------------------------------------------------------- */
/*  the issue                                                                  */
/* -------------------------------------------------------------------------- */

export interface ValidatorIssue {
  code: IssueCode;
  severity: IssueSeverity;
  /** The copy id the panel renders, plus the text a missing id degrades to. Never prose to print. */
  copy: IssueCopy;
  subject: IssueSubject;
  /** Machine-readable specifics: measured numbers, the ids that collided, the tier that was folded. */
  detail?: Readonly<Record<string, string | number>>;
  /** Where in the tree, when the subject is a node. Absent for an action or a token pairing. */
  path?: readonly string[];
}

export interface IssueOptions {
  detail?: Readonly<Record<string, string | number>>;
  path?: readonly string[];
}

/** Build one issue, taking its severity and its copy from the tables above rather than by hand. */
export function validatorIssue(
  code: ValidatorIssueCode,
  subject: IssueSubject,
  options: IssueOptions = {},
): ValidatorIssue {
  const issue: ValidatorIssue = {
    code,
    severity: VALIDATOR_ISSUE_SEVERITY[code],
    copy: ISSUE_COPY[code],
    subject,
  };
  if (options.detail) issue.detail = options.detail;
  if (options.path) issue.path = options.path;
  return issue;
}

/**
 * A structural finding, folded into this model.
 *
 * `validateLayout` grades on three tiers because a duplicate id is a defect rather than a
 * judgement, but nothing in Design Mode blocks, so `error` and `warning` both land on `warning`
 * here. The original tier travels in `detail.tier`, so a panel that wants to draw a defect
 * differently from a design judgement still can, and nothing about the fold is lossy.
 *
 * The subject kind is read off the code rather than off the node, because a `LayoutIssue` carries
 * only an id and a path - and the code already says what kind of thing that id names.
 */
export function fromLayoutIssue(issue: LayoutIssue): ValidatorIssue {
  const folded: ValidatorIssue = {
    code: issue.code,
    severity: issue.severity === "info" ? "info" : "warning",
    copy: ISSUE_COPY[issue.code],
    subject: { kind: layoutSubjectKind(issue.code), id: issue.nodeId } as IssueSubject,
    detail: { ...(issue.detail ?? {}), tier: issue.severity },
    path: issue.path,
  };
  return folded;
}

function layoutSubjectKind(code: LayoutIssueCode): IssueSubjectKind {
  switch (code) {
    case "unsupported-schema-version":
      return "document";
    case "orphan-slot":
      return "slot";
    case "unknown-piece":
      return "placement";
    case "splitter-unknown-slot":
      return "splitter";
    // `duplicate-id` can name any of the three kinds and the issue does not say which, so it is
    // reported against the node position rather than against a kind this module would be guessing.
    case "duplicate-id":
      return "region";
    default:
      return "region";
  }
}

/* -------------------------------------------------------------------------- */
/*  ordering                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * A TOTAL order: severity, then code, then subject kind, then subject id, then path, then detail.
 *
 * Total rather than merely deterministic. Two issues that agree on all five keys are the same row
 * twice, and `Array.prototype.sort` is stable, so identical rows keep the order their producer
 * emitted them in. Anything less would make a committed layout's issue list depend on the order the
 * validators happened to run in, which is exactly the drift a diffable commit cannot have.
 */
export function compareIssues(left: ValidatorIssue, right: ValidatorIssue): number {
  const bySeverity =
    ISSUE_SEVERITY_ORDER.indexOf(left.severity) - ISSUE_SEVERITY_ORDER.indexOf(right.severity);
  if (bySeverity !== 0) return bySeverity;

  const byCode = left.code < right.code ? -1 : left.code > right.code ? 1 : 0;
  if (byCode !== 0) return byCode;

  const byKind =
    SUBJECT_KIND_ORDER.indexOf(left.subject.kind) - SUBJECT_KIND_ORDER.indexOf(right.subject.kind);
  if (byKind !== 0) return byKind;

  const byId = left.subject.id < right.subject.id ? -1 : left.subject.id > right.subject.id ? 1 : 0;
  if (byId !== 0) return byId;

  const leftPath = (left.path ?? []).join("/");
  const rightPath = (right.path ?? []).join("/");
  if (leftPath !== rightPath) return leftPath < rightPath ? -1 : 1;

  const leftDetail = detailKey(left.detail);
  const rightDetail = detailKey(right.detail);
  if (leftDetail !== rightDetail) return leftDetail < rightDetail ? -1 : 1;
  return 0;
}

/** Detail as one comparable string, with its keys sorted so key order cannot change the answer. */
function detailKey(detail: ValidatorIssue["detail"]): string {
  if (!detail) return "";
  return Object.keys(detail)
    .sort()
    .map((key) => `${key}=${detail[key]}`)
    .join(",");
}

/** A new sorted array. Never sorts in place: the caller's list is the caller's. */
export function sortIssues(issues: readonly ValidatorIssue[]): ValidatorIssue[] {
  return [...issues].sort(compareIssues);
}
