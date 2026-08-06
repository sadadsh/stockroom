/**
 * Committed LAYOUT overrides: the arrangement the owner shipped, written by Design Mode's commit.
 *
 * The sibling of `token.overrides.ts`, `copy.overrides.ts`, `icon.overrides.ts`,
 * `element.overrides.ts` and `behavior.overrides.ts`, and it follows the same rule: this file is the
 * SOURCE OF TRUTH for a redesign, it applies on boot for EVERYONE (Design Mode on or off, because a
 * committed layout is not a per-machine setting), and `null` means "use the shipped default in
 * `layout/defaultWorkspaceLayout.ts`".
 *
 * ONE DIFFERENCE FROM ITS SIBLINGS, and it is the owner's decision 4 (plan 1.6): the other five are
 * written by `POST /api/dev/save`, which is a live round trip to source. A layout is NOT. Named local
 * drafts (`lib/layoutDrafts.ts`) are where an experiment lives, and a COMMIT - the plan's Phase 4
 * pipeline - is what serialises a draft into this file, regenerates whatever registries it touches
 * and runs the gates. Nothing writes this file yet; Phase 3 defines its shape and its application so
 * that Phase 4 has one place to write and no rendering question left to answer.
 *
 * WHY A KEYED OBJECT rather than a bare document. The plan's sequencing puts the workspace first
 * (Phase 1), the application shell in Phase 6 and the remaining routes in Phase 7, one at a time. Each
 * of those is its own layout document with its own default, so each gets its own key here rather than
 * its own module - one file the commit pipeline regenerates whole, exactly as
 * `POST /api/dev/save` regenerates the other five.
 *
 * WHAT MAY BE WRITTEN HERE: a document `layout/document.ts` can validate, at the schema version this
 * build knows. Nothing enforces that at boot and nothing should - a committed layout naming a piece
 * this build has not shipped is a real state (an older machine opening a newer layout), and
 * `validateLayout` REPORTS it while the renderer draws what it can. Warn, never block.
 */
import type { LayoutDocument } from "../layout/document";

export interface LayoutOverrides {
  /** The opened-component workspace (`workspace.component`), or `null` for the shipped default. */
  workspace: LayoutDocument | null;
}

export const LAYOUT_OVERRIDES: LayoutOverrides = {
  workspace: null,
};
