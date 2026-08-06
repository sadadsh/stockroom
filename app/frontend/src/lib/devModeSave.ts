/**
 * Persistence for the dev mode draft: `dirty` against the last-saved baseline, and the Save that
 * writes the working overrides back to SOURCE (lib/*.overrides.ts) via POST /api/dev/save - so a
 * committed change ships for everyone, not just this machine.
 *
 * ALL SIX SLICES, SINCE DESIGN MODE PHASE 4. The sixth is the ARRANGEMENT - the working layout
 * document - and it travels with the other five rather than through a route of its own. That is the
 * owner's decision 4 (plan 1.6) taken literally: "a committed redesign becomes the app", written to
 * `lib/layout.overrides.ts` and shipped through main like any other change. A named local draft is
 * still where an experiment lives; Save is what ends the experiment.
 *
 * WHAT A NULL LAYOUT MEANS ON SAVE, because it is the one asymmetry worth stating. `draft.layout` is
 * null for "no working edit", and the draft is SEEDED from the committed document, so on a normal
 * boot it is non-null exactly when something is committed. Sending null therefore clears the
 * committed arrangement back to the shipped default - which is what Reset all followed by Save means
 * for every other slice too (an empty token map commits the shipped stylesheet). Reverting a redesign
 * is a source change, and this is the pipeline that makes one.
 *
 * TWO THINGS THIS COMPUTES RATHER THAN FORWARDS, both because the frontend is the only place they can
 * be computed:
 *
 *   THE DEVIATION LIST. `layout/validateDocument.ts` is the validator, it is frontend TypeScript, and
 *   plan 1.4 says a committed layout's known issues are part of the commit. So Save runs it over the
 *   document it is about to commit and sends the result; the writer emits it verbatim beside the
 *   document. It is measured against the palette being committed (the draft's token overlay on the
 *   shipped defaults), not the shipped palette, so the row list matches the design that ships.
 *
 *   OWNER-AUTHORED COPY PROVENANCE. Plan 1.5's resolution: the letter rule binds text the app authors
 *   FOR the owner, and exempts text the owner typed themselves. Every entry in `draft.copy` whose text
 *   differs from what is committed was typed here, in this editor, by the owner - there is no other
 *   producer of that map - so Save records those ids. An entry carried over unchanged keeps whatever
 *   provenance the committed record already gave it, which is how a rewording somebody hand-edited
 *   into `copy.overrides.ts` stays bound by the lint.
 */
import { useCallback, useMemo, useState } from "react";
import { api } from "../api/client";
import { ApiError } from "../api/client";
import { validateDocument } from "../layout/validateDocument";
import { draftThemeTokens } from "../layout/validateContrast";
import { WORKSPACE_PIECE_REGISTRY } from "../layout/workspacePieces";
import type { ValidatorIssue } from "../layout/validatorIssues";
import { TOKEN_OVERRIDES } from "./token.overrides";
import { COPY_OVERRIDES, OWNER_AUTHORED_COPY_IDS } from "./copy.overrides";
import { ICON_OVERRIDES } from "./icon.overrides";
import { ELEMENT_OVERRIDES } from "./element.overrides";
import { BEHAVIOR_OVERRIDES } from "./behavior.overrides";
import { LAYOUT_OVERRIDES } from "./layout.overrides";
import { applicableOverrides } from "./applyElementOverrides";
import { copyPlaceholderDeclarations } from "./copyPlaceholders";
import type { DevModeDraft, TokenOverrides } from "./devModeDraft";
import type { LayoutDocument } from "../layout/document";

// The serialised last-saved value of each slice, compared against the live draft to derive `dirty`.
interface SavedBaseline {
  tokens: string;
  copy: string;
  icons: string;
  elements: string;
  behaviors: string;
  layout: string;
}

/**
 * The deviation list that ships with this commit: everything the validator says about the document
 * being written, in its own stable order. No document committed means nothing to say about one.
 *
 * MEASURED AGAINST THE PALETTE BEING COMMITTED, not the shipped one. `draftThemeTokens` resolves both
 * themes out of the same token slice this Save is writing, so a contrast row that ships with the
 * arrangement is about the colours that ship with it. Using the shipped palette would record rows the
 * committed design does not have, and miss the ones it does.
 */
export function committedIssuesFor(
  layout: LayoutDocument | null,
  tokens: TokenOverrides,
): ValidatorIssue[] {
  if (!layout) return [];
  return validateDocument(layout, WORKSPACE_PIECE_REGISTRY, draftThemeTokens(tokens));
}

/**
 * The copy ids this Save can honestly call owner-authored.
 *
 * Two sources, and neither is a guess: an id whose text is not what is committed was just typed in
 * the editor, and an id the committed record already marks keeps that mark for as long as it still
 * carries an override. An id with no override drops out, because there is nothing left to exempt.
 */
export function ownerAuthoredCopyIds(copy: Record<string, string>): string[] {
  const recorded = new Set(OWNER_AUTHORED_COPY_IDS);
  const ids = Object.keys(copy).filter((id) => copy[id] !== COPY_OVERRIDES[id] || recorded.has(id));
  return ids.sort();
}

export function useDevModeSave(draft: DevModeDraft) {
  const { tokens, copy, icons, elements, behaviors, layout } = draft;
  const [saving, setSaving] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  // The last-saved baseline, so `dirty` reflects unsaved edits (the imported modules are frozen).
  const [saved, setSaved] = useState<SavedBaseline>(() => ({
    tokens: JSON.stringify(TOKEN_OVERRIDES),
    copy: JSON.stringify(COPY_OVERRIDES),
    icons: JSON.stringify(ICON_OVERRIDES),
    elements: JSON.stringify(ELEMENT_OVERRIDES),
    behaviors: JSON.stringify(BEHAVIOR_OVERRIDES),
    layout: JSON.stringify(LAYOUT_OVERRIDES.workspace ?? null),
  }));

  const dirty =
    JSON.stringify(tokens) !== saved.tokens ||
    JSON.stringify(copy) !== saved.copy ||
    JSON.stringify(icons) !== saved.icons ||
    JSON.stringify(elements) !== saved.elements ||
    JSON.stringify(behaviors) !== saved.behaviors ||
    JSON.stringify(layout ?? null) !== saved.layout;

  const save = useCallback(async () => {
    setSaving(true);
    setLastError(null);
    try {
      // D-04 / ELEM-01: carry the working icon + element overrides as the `icons` / `elements`
      // blocks; the backend (already wired) validates them and writes lib/icon.overrides.ts +
      // lib/element.overrides.ts alongside the token/copy files.
      //
      // `elements` is narrowed to what the runtime would actually apply, so Save writes only
      // source-backed overrides: a property that is no longer editable, or a value outside the safe
      // grammar, is dropped here rather than sent to earn a 400 that names a value nobody typed.
      //
      // `copyPlaceholders` carries what each seen default DECLARES, so the writer can reject a
      // rewording that dropped a required placeholder or invented one. The default lives in the
      // JSX, so the backend has no other way to know the required set.
      //
      // `layout` is keyed by surface because lib/layout.overrides.ts is - the shell (Phase 6) and the
      // remaining routes (Phase 7) each become a key beside `workspace`, and one keyed block is what
      // lets the writer regenerate the module whole instead of merging into it.
      await api.devSave({
        tokens,
        copy,
        icons,
        elements: applicableOverrides(elements),
        behaviors,
        copyPlaceholders: copyPlaceholderDeclarations(),
        layout: { workspace: layout },
        committedIssues: { workspace: committedIssuesFor(layout, tokens) },
        ownerAuthoredCopy: ownerAuthoredCopyIds(copy),
      });
      setSaved({
        tokens: JSON.stringify(tokens),
        copy: JSON.stringify(copy),
        icons: JSON.stringify(icons),
        elements: JSON.stringify(elements),
        behaviors: JSON.stringify(behaviors),
        layout: JSON.stringify(layout ?? null),
      });
    } catch (err) {
      setLastError(err instanceof ApiError ? err.message : "Could not save to source");
    } finally {
      setSaving(false);
    }
  }, [tokens, copy, icons, elements, behaviors, layout]);

  return useMemo(
    () => ({ dirty, saving, lastError, save }),
    [dirty, saving, lastError, save],
  );
}
