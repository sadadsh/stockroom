/**
 * The one pure logic module for Dev Mode v2 layout editing (Phase F / LAYOUT-01): app-friendly reorder
 * of an element among its container siblings via the CSS `order` property, keyed by `data-dev-id`.
 *
 * This is the reorder half of the layout capstone. It composes with the existing responsive layout and
 * reverts cleanly BECAUSE it never reparents the DOM: an `order` value is just override data that flows
 * through Phase E's element-override pipeline (lib/element.overrides.ts -> applyElementOverrides ->
 * inline style by id), which already applies on boot for everyone and already ships in the /api/dev/save
 * `elements` block. The DevPanel writes the values these functions compute; the backend `dev.py`
 * `_valid_css_value` grammar is the sole authority on what may be committed (isValidOrder below mirrors
 * that grammar client-side so the panel never emits a value the writer would reject with a 400).
 *
 * Every export is pure and free of getComputedStyle: className is read via getAttribute("class") (the
 * classTokens / inspectVars convention), so the logic is deterministic under jsdom, which computes no
 * layout. Visual sequence is therefore expressed by explicit integer `order` values, not measured.
 */

// The container layout kinds this module recognises (className-driven, decision 1a).
export type ContainerLayout = "flex" | "grid" | "none";

// The client-side mirror of the backend `order` grammar (dev.py `_ORDER_RE = ^-?\d{1,3}$`): an
// optionally-signed integer of one to three digits. It gates every `order` value the panel writes so a
// reorder can never emit a value the /api/dev/save writer would reject with a 400. The backend stays the
// sole authority on what may ship; this only keeps the panel from producing a doomed request.
const ORDER_RE = /^-?\d{1,3}$/;

/**
 * True only for an `order` value in the safe backend grammar (a signed 1-3 digit integer). Rejects the
 * empty string, four-plus digits, slot syntax like "1 / 2", and any non-numeric text.
 */
export function isValidOrder(value: string): boolean {
  return ORDER_RE.test(value);
}

// A Tailwind grid-cols-N utility, read WHOLE-token off the container className (grid-cols-2 -> 2), the
// same getAttribute("class") convention as containerLayoutOf so it stays deterministic under jsdom.
const GRID_COLS_RE = /^grid-cols-(\d+)$/;

/**
 * The declared column-track count of a grid container, read from its `grid-cols-N` class (e.g.
 * grid-cols-2 -> 2), or 0 when no such class is present. Reads className via getAttribute("class")
 * (never getComputedStyle), so it is deterministic under jsdom; the slot picker derives its column /
 * row position options from this count. Only the first grid-cols-N token is honoured.
 */
export function gridColumnsOf(container: Element | null | undefined): number {
  if (!container) return 0;
  const classes = (container.getAttribute("class") ?? "").split(/\s+/);
  for (const cls of classes) {
    const m = GRID_COLS_RE.exec(cls);
    if (m) return parseInt(m[1], 10);
  }
  return 0;
}

// The client-side mirror of the backend grid-slot grammar (dev.py `_GRID_TOKEN_RE` / `_valid_grid_slot`),
// kept as a SAFE SUBSET of it: a token is `auto`, a small (1-4 digit) signed integer, or `span N`. The
// backend additionally accepts bare named grid lines (an identifier like `red`), but the slot picker
// never emits those - it offers only auto / integer / span positions - so the client stays deliberately
// stricter. That keeps the guarantee that matters (every value the panel could emit is one the backend
// accepts, so a slot write can never earn a 400) while rejecting stray identifiers the picker cannot mean.
const GRID_TOKEN_RE = /^(?:auto|-?\d{1,4}|span\s+\d{1,4})$/;

/**
 * True only for a grid-column / grid-row value in the safe slot grammar: one or two line tokens
 * separated by a single `/`, each token `auto`, a small signed integer, or `span N`. Rejects a
 * three-part slot ("1 / 2 / 3"), the empty string, a stray identifier ("red"), and any token carrying
 * punctuation ("1;2"). A strict subset of the backend `_valid_grid_slot`, so the panel never writes a
 * value the writer would reject; the backend grammar remains the authority on what may ship.
 */
export function isValidGridSlot(value: string): boolean {
  const parts = value.split("/").map((p) => p.trim());
  if (parts.length < 1 || parts.length > 2) return false;
  return parts.every((p) => p !== "" && GRID_TOKEN_RE.test(p));
}

// Which direction a reorder moves the selected element among its siblings: one visual step earlier
// ("up") or later ("down").
export type ReorderDirection = "up" | "down";

/**
 * Report a container's layout kind by reading its className the same way classTokens does
 * (getAttribute("class"), not getComputedStyle - jsdom computes no layout, and an SVG's className is
 * not a plain string). Matches WHOLE class tokens so `flex-col` is not read as the `flex` display
 * class: "flex" / "inline-flex" -> "flex", "grid" / "inline-grid" -> "grid", anything else -> "none".
 */
export function containerLayoutOf(container: Element | null | undefined): ContainerLayout {
  if (!container) return "none";
  const classes = (container.getAttribute("class") ?? "").split(/\s+/);
  if (classes.includes("flex") || classes.includes("inline-flex")) return "flex";
  if (classes.includes("grid") || classes.includes("inline-grid")) return "grid";
  return "none";
}

/**
 * The direct-child [data-dev-id] elements of `el`'s parent, in DOM order (the reorder candidate set,
 * including `el` itself). Direct children only (parent.children), so a nested dev-id deeper in the tree
 * is never treated as a sibling. Reparenting is out of scope, so DOM order is stable across reorders;
 * the caller derives the current VISUAL sequence by sorting these by their live `order` override.
 */
export function reorderSiblingsOf(el: Element): HTMLElement[] {
  const parent = el.parentElement;
  if (!parent) return [];
  return Array.from(parent.children).filter(
    (c): c is HTMLElement => c instanceof HTMLElement && c.hasAttribute("data-dev-id"),
  );
}

/**
 * Given the sibling ids in their CURRENT VISUAL sequence and the id to move, return a normalized map of
 * EVERY sibling id -> an explicit 0-based `order` string, with the selected id swapped one step toward
 * `direction` ("up" = one earlier, "down" = one later). Normalizing (assigning 0..n-1 across the whole
 * set) makes the sequence explicit so a single write set fully determines the visual order.
 *
 * Idempotent at the ends: moving the first id "up" or the last id "down" swaps nothing (no throw), so it
 * returns the current sequence normalized - applying it does not change the visual order. Because the
 * caller re-derives the visual sequence before each call, repeated moves walk the element exactly one
 * step per click until it reaches an end, then hold.
 */
export function reorderSiblings(
  orderedIds: readonly string[],
  selectedId: string,
  direction: ReorderDirection,
): Record<string, string> {
  const seq = [...orderedIds];
  const i = seq.indexOf(selectedId);
  if (i !== -1) {
    const j = direction === "up" ? i - 1 : i + 1;
    if (j >= 0 && j < seq.length) {
      [seq[i], seq[j]] = [seq[j], seq[i]];
    }
  }
  const out: Record<string, string> = {};
  seq.forEach((id, idx) => {
    out[id] = String(idx);
  });
  return out;
}
