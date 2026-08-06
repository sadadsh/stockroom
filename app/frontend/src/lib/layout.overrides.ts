/**
 * Committed LAYOUT overrides: the arrangement the owner shipped, written by Design Mode's commit.
 *
 * The sibling of `token.overrides.ts`, `copy.overrides.ts`, `icon.overrides.ts`,
 * `element.overrides.ts` and `behavior.overrides.ts`, and it follows the same rule: this file is the
 * SOURCE OF TRUTH for a redesign, it applies on boot for EVERYONE (Design Mode on or off, because a
 * committed layout is not a per-machine setting), and `null` means "use the shipped default in
 * `layout/defaultWorkspaceLayout.ts`".
 *
 * Regenerated whole by POST /api/dev/save, exactly as its five siblings are - that is the owner's
 * decision 4 (plan 1.6): a committed redesign becomes the app and ships through main like any other
 * change. Named local drafts are still where an experiment lives; Save is what ends the experiment.
 *
 * WHY A KEYED OBJECT rather than a bare document. The plan's sequencing puts the workspace first
 * (Phase 1), the application shell in Phase 6 and the remaining routes in Phase 7, one at a time. Each
 * of those is its own layout document with its own default, so each gets its own key here rather than
 * its own module - one file the writer regenerates whole.
 *
 * WHAT MAY BE WRITTEN HERE: a document `layout/document.ts` can validate, at the schema version this
 * build knows. Nothing enforces that at boot and nothing should - a committed layout naming a piece
 * this build has not shipped is a real state (an older machine opening a newer layout), and
 * `validateLayout` REPORTS it while the renderer draws what it can. Warn, never block.
 */
import type { LayoutDocument } from "../layout/document";
import type { ValidatorIssue } from "../layout/validatorIssues";

export interface LayoutOverrides {
  /** The opened-component workspace (`workspace.component`), or `null` for the shipped default. */
  workspace: LayoutDocument | null;
}

export const LAYOUT_OVERRIDES: LayoutOverrides = {
  workspace: null,
};

/**
 * THE DEVIATION LIST THAT SHIPS WITH THE COMMIT (plan 1.4: "a committed layout's known issues are
 * part of the commit, visible in Dev Mode - honesty travels with the design").
 *
 * These are `validateDocument`'s findings for the document above, computed on the frontend at the
 * moment Save was pressed and written here verbatim. They are a RECORD, not a cache: live validation
 * may legitimately differ, because contrast is measured against whatever palette is in force, a
 * reachability finding follows the piece registry this build ships, and a later build can register
 * pieces this commit had never heard of. A row here that live validation no longer reports is not a
 * bug in either one - it is what the owner accepted when they committed, next to what is true now.
 *
 * An empty array for a slice means the validator found nothing at commit time. An absent slice key
 * cannot happen: the writer emits one entry per key of `LayoutOverrides`.
 */
export interface LayoutCommittedIssues {
  /** The validator's reading of `LAYOUT_OVERRIDES.workspace`, as of the commit that wrote it. */
  workspace: readonly ValidatorIssue[];
}

export const LAYOUT_COMMITTED_ISSUES: LayoutCommittedIssues = {
  workspace: [],
};
