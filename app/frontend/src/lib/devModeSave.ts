/**
 * Persistence for the dev mode draft: `dirty` against the last-saved baseline, and the Save that
 * writes the working overrides back to SOURCE (lib/*.overrides.ts) via POST /api/dev/save - so a
 * committed change ships for everyone, not just this machine.
 */
import { useCallback, useMemo, useState } from "react";
import { api } from "../api/client";
import { ApiError } from "../api/client";
import { TOKEN_OVERRIDES } from "./token.overrides";
import { COPY_OVERRIDES } from "./copy.overrides";
import { ICON_OVERRIDES } from "./icon.overrides";
import { ELEMENT_OVERRIDES } from "./element.overrides";
import { BEHAVIOR_OVERRIDES } from "./behavior.overrides";
import { applicableOverrides } from "./applyElementOverrides";
import { copyPlaceholderDeclarations } from "./copyPlaceholders";
import type { DevModeDraft } from "./devModeDraft";

// The serialised last-saved value of each slice, compared against the live draft to derive `dirty`.
interface SavedBaseline {
  tokens: string;
  copy: string;
  icons: string;
  elements: string;
  behaviors: string;
}

export function useDevModeSave(draft: DevModeDraft) {
  const { tokens, copy, icons, elements, behaviors } = draft;
  const [saving, setSaving] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  // The last-saved baseline, so `dirty` reflects unsaved edits (the imported modules are frozen).
  const [saved, setSaved] = useState<SavedBaseline>(() => ({
    tokens: JSON.stringify(TOKEN_OVERRIDES),
    copy: JSON.stringify(COPY_OVERRIDES),
    icons: JSON.stringify(ICON_OVERRIDES),
    elements: JSON.stringify(ELEMENT_OVERRIDES),
    behaviors: JSON.stringify(BEHAVIOR_OVERRIDES),
  }));

  const dirty =
    JSON.stringify(tokens) !== saved.tokens ||
    JSON.stringify(copy) !== saved.copy ||
    JSON.stringify(icons) !== saved.icons ||
    JSON.stringify(elements) !== saved.elements ||
    JSON.stringify(behaviors) !== saved.behaviors;

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
      await api.devSave({
        tokens,
        copy,
        icons,
        elements: applicableOverrides(elements),
        behaviors,
        copyPlaceholders: copyPlaceholderDeclarations(),
      });
      setSaved({
        tokens: JSON.stringify(tokens),
        copy: JSON.stringify(copy),
        icons: JSON.stringify(icons),
        elements: JSON.stringify(elements),
        behaviors: JSON.stringify(behaviors),
      });
    } catch (err) {
      setLastError(err instanceof ApiError ? err.message : "Could not save to source");
    } finally {
      setSaving(false);
    }
  }, [tokens, copy, icons, elements, behaviors]);

  return useMemo(
    () => ({ dirty, saving, lastError, save }),
    [dirty, saving, lastError, save],
  );
}
