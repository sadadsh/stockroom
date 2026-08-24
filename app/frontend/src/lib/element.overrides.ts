/**
 * Committed per-element overrides, written by dev mode (Ctrl+Shift+D, then the Box tab). This file is the
 * SOURCE OF TRUTH for any single element the owner has tuned locally - the escape hatch for the one-off a
 * global token cannot reach (size, spacing, and later layout order / grid slot). It is applied on boot for
 * everyone (not a per-machine setting) as an inline style on every element carrying the matching
 * `data-dev-id`, so a saved tweak ships with the app. A key is a stable dev id (see lib/devIds.ts /
 * data-dev-id="..."); the value is a map of CSS property -> value. Generated whole by POST /api/dev/save
 * through a strict CSS-value validator (safe lengths / keywords only); safe to hand-edit but the backend
 * validator is the authority on what may ship.
 */
const HIDDEN_TARGETS = [
  "auto.parts-list.0iafwyi",
  "auto.product-state.0tk9qox",
  "auto.specifications-pieces.0fb5jxn",
  "component-browser.header-lifecycle",
  "component-browser.preferred-source",
  "component-browser.quality-summary",
  "component-browser.spec-anchors",
  "component-browser.spec-source::matching",
] as const;

export const ELEMENT_OVERRIDES: Record<string, Record<string, string>> = {
  ...Object.fromEntries(HIDDEN_TARGETS.map((id) => [id, { display: "none" }])),
  "auto.occurrence.1n39y9a": {
    left: "0px",
    position: "relative",
    top: "0px",
    "z-index": "3",
  },
  "auto.occurrence.1qyzb8v": {
    left: "0px",
    position: "relative",
    top: "0px",
    "z-index": "3",
  },
  "auto.occurrence.1t2ybpd": {
    left: "0px",
    position: "relative",
    top: "0px",
    "z-index": "3",
  },
  "auto.parts-list.1u34bm3": {
    left: "0px",
    position: "relative",
    top: "8px",
  },
};
