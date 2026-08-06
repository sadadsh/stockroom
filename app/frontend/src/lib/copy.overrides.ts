/**
 * Committed UI-copy overrides, written by dev mode (Ctrl+Shift+D, then click any label). This
 * file is the SOURCE OF TRUTH for any label the owner has reworded: it is read on every render
 * for everyone (not a per-machine setting), so a saved rewording ships with the app. A key is a
 * stable copy id (see <Text id="...">); an absent id falls back to the default text written in
 * the JSX. Regenerated whole by POST /api/dev/save - safe to hand-edit.
 */
export const COPY_OVERRIDES: Record<string, string> = {};

/**
 * OWNER-AUTHORED PROVENANCE for the rewordings above (plan 1.5, the owner amendment).
 *
 * The letter rule and the term map are the owner's own rules, enforced by `copy.letterRule.test.ts`
 * against text this application AUTHORS FOR the owner. Text the owner types themselves, through the
 * Design Mode editor, is not that: the lint exists to catch an agent writing a blocked word into
 * their product, not to overrule the owner inside it. So an id listed here is exempt from the letter
 * rule and every id that is not listed stays bound by it - including a rewording somebody hand-edited
 * into the map above, which is exactly the case the exemption must not cover.
 *
 * Written by POST /api/dev/save from what the editor reports it authored. Only an id that HAS an
 * override above can appear; the writer drops any other, so this can never become a standing
 * exemption for a string that is not there.
 */
export const OWNER_AUTHORED_COPY_IDS: readonly string[] = [];
