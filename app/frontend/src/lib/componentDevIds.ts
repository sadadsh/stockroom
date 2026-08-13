/**
 * Dev ids that carry a runtime record id, and the INSTANCE / SHARED distinction that goes with them.
 *
 * The catalogue in `devIds.ts` is a fixed list, so an element that exists once per OPEN COMPONENT
 * (or once per staged candidate) cannot have a row there. Those ids are built here instead, from
 * one shared pattern:
 *
 *     component-browser.component[<component id>]
 *     component-browser.component[<component id>].tab
 *     component-browser.component[<component id>].representation[<kind>]
 *     component-browser.component[<component id>].provider[<provider id>]
 *     ingest.candidate[<candidate id>]
 *     detail.handoff-field[<registry field key>]
 *     detail.handoff-open[<registry field key>]
 *     stm.package[<package name>]
 *     stm.family[<family>]
 *
 * ONE builder, because the alternative is every call site interpolating an id into a template and
 * a second call site interpolating it slightly differently - at which point the ids are no longer
 * addressable and dev mode cannot find the element it was asked about.
 *
 * The id itself is bounded and stripped of the characters that would break the bracket grammar, so
 * a hostile or merely odd record id cannot forge a different element's id. Selectors go through
 * `CSS.escape` rather than string concatenation: a raw id in a selector is a parse error waiting
 * for the first part number with a quote or a bracket in it.
 *
 * --- INSTANCE vs SHARED -----------------------------------------------------------------------
 *
 * These two are different contracts and the difference is deliberate, because an override keyed on
 * the wrong one is either useless or destructive:
 *
 *   INSTANCE - an id carrying a `[value]` segment names exactly ONE element. Editing
 *              `component-browser.component[stm32h743vit6].tab` moves that one tab and leaves its
 *              siblings alone, because no other element can ever carry that id.
 *   SHARED   - a catalogue id names a ROLE. Editing `components.row` is meant to restyle every
 *              part row; that is the whole point of a class-level id, and narrowing it to the first
 *              match would silently break the contract every existing override was written under.
 *
 * An element may hold both: `data-dev-id` is the instance it IS, `data-dev-role` is the shared
 * class it BELONGS TO. `lib/applyElementOverrides.ts` resolves an id through whichever contract it
 * declares, so the two never quietly collapse into one another.
 */
import { designIdSelector, isGeneratedDesignId } from "./designIdentity";

import { DEV_ID_BY_ID } from "./devIds";

/** The area every opened-component element lives under. Matches the `devIds.ts` area name. */
export const COMPONENT_BROWSER_AREA = "component-browser";

// Long enough for any real record id (the session contract bounds ids at 192) and short enough
// that a pathological value cannot turn an attribute into a payload.
const MAX_SEGMENT = 192;

/**
 * One dynamic segment, made safe for the `name[value]` grammar above.
 *
 * Brackets, quotes, whitespace and control characters collapse to `_`: they are the only
 * characters that could either close the bracket early or make the attribute unreadable, and no
 * real component id needs them to stay distinct.
 */
export function devIdSegment(value: string): string {
  return (value || "unknown")
    .slice(0, MAX_SEGMENT)
    .replace(/[[\]"'`\\\s\u0000-\u001f\u007f]+/g, "_");
}

/** The opened component's workspace body. */
export function componentDevId(id: string): string {
  return `${COMPONENT_BROWSER_AREA}.component[${devIdSegment(id)}]`;
}

/** That component's tab in the strip. */
export function componentTabDevId(id: string): string {
  return `${componentDevId(id)}.tab`;
}

/** One representation module inside that component's dock. */
export function componentRepresentationDevId(id: string, kind: string): string {
  return `${componentDevId(id)}.representation[${devIdSegment(kind)}]`;
}

/**
 * One provider's coverage row for that component.
 *
 * The registry decides which providers exist, so this set is a library too: catalogued rows would
 * go stale the moment a provider is added, and an interpolated selector would break on the first
 * provider key carrying a character the bracket grammar cannot hold.
 */
export function componentProviderDevId(id: string, providerId: string): string {
  return `${componentDevId(id)}.provider[${devIdSegment(providerId)}]`;
}

/**
 * The general instance-id builder: a catalogued ROLE plus the record value that distinguishes this
 * one from its siblings.
 *
 * Every dynamic id in the app is built here or by one of the named helpers below. That is the point:
 * an id interpolated at a call site (`` `stm.package-${p.name}` ``) carries whatever the record
 * holds - a space, a bracket, a quote - straight into an attribute and into every selector built
 * from it, and it is invisible to the catalogue gate because it is not a literal.
 */
export function instanceDevId(role: string, value: string): string {
  return `${role}[${devIdSegment(value)}]`;
}

/** The shared role every staged candidate card belongs to. Its catalogue row is `ingest.candidate`. */
export const CANDIDATE_ROLE = "ingest.candidate";

/**
 * One staged candidate card.
 *
 * The intake list renders the same card once per candidate, so the card is the plainest case of the
 * problem this file exists for: without a per-candidate id, tuning one card tunes all of them. The
 * card also declares `data-dev-role={CANDIDATE_ROLE}`, so the class-level edit stays available.
 */
export function candidateDevId(id: string): string {
  return `${CANDIDATE_ROLE}[${devIdSegment(id)}]`;
}

/**
 * Which contract an id declares. A `[value]` segment is the marker, and it is a marker no catalogue
 * id can accidentally acquire: `devIds.ts` ids are dot-namespaced lowercase-kebab with no brackets.
 */
export type DevIdScope = "instance" | "shared";

const BRACKET_SEGMENT_RE = /\[[^\]]*\]/;

export function devIdScope(devId: string): DevIdScope {
  return BRACKET_SEGMENT_RE.test(devId) ? "instance" : "shared";
}

// --- what counts as a dev id at all -------------------------------------------------------------
// The client-side twin of `dev.py`'s `_valid_element_id`. An id is legitimate when it is a
// CATALOGUE row or when it matches one of the approved dynamic shapes below - and nothing else. An
// unregistered bracketed id is not "a dev id we forgot to catalogue", it is an unregistered
// selector, and both ends refuse to key an override on one.

// A bracket value, exactly as `devIdSegment()` emits it: no brackets, quotes, backslash, whitespace
// or control characters, and bounded.
const DYNAMIC_VALUE = "[^\\[\\]\"'`\\\\\\s\\u0000-\\u001f\\u007f]{1,192}";

const DYNAMIC_DEV_ID_RES: readonly RegExp[] = [
  `^component-browser\\.component\\[${DYNAMIC_VALUE}\\]$`,
  `^component-browser\\.component\\[${DYNAMIC_VALUE}\\]\\.tab$`,
  `^component-browser\\.component\\[${DYNAMIC_VALUE}\\]\\.representation\\[${DYNAMIC_VALUE}\\]$`,
  `^component-browser\\.component\\[${DYNAMIC_VALUE}\\]\\.provider\\[${DYNAMIC_VALUE}\\]$`,
  `^ingest\\.candidate\\[${DYNAMIC_VALUE}\\]$`,
  `^detail\\.handoff-field\\[${DYNAMIC_VALUE}\\]$`,
  `^detail\\.handoff-open\\[${DYNAMIC_VALUE}\\]$`,
  `^stm\\.package\\[${DYNAMIC_VALUE}\\]$`,
  `^stm\\.family\\[${DYNAMIC_VALUE}\\]$`,
].map((pattern) => new RegExp(pattern));

/** True for one of the approved per-instance shapes. */
export function isApprovedDynamicDevId(devId: string): boolean {
  return DYNAMIC_DEV_ID_RES.some((pattern) => pattern.test(devId));
}

/** True for a catalogued id or an approved instance id. Nothing else is addressable. */
export function isAllowedDevId(devId: string): boolean {
  if (!devId) return false;
  return devIdScope(devId) === "instance"
    ? isApprovedDynamicDevId(devId)
    : DEV_ID_BY_ID.has(devId);
}

/**
 * A `[data-dev-id=...]` selector for any dev id, dynamic or catalogued.
 *
 * `CSS.escape` produces an escaped IDENTIFIER, so the value is deliberately left unquoted - that
 * is the form the escape is defined for. The fallback exists only for runtimes without CSS.escape;
 * it quotes and escapes by hand rather than silently emitting an unsafe selector.
 */
export function devIdSelector(devId: string): string {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
    return `[data-dev-id=${CSS.escape(devId)}]`;
  }
  return `[data-dev-id="${devId.replace(/["\\]/g, "\\$&")}"]`;
}

/** The same selector against `data-dev-role`, for the shared-class half of the contract. */
export function devRoleSelector(devId: string): string {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
    return `[data-dev-role=${CSS.escape(devId)}]`;
  }
  return `[data-dev-role="${devId.replace(/["\\]/g, "\\$&")}"]`;
}

/**
 * Every element an id addresses, under the contract the id declares.
 *
 * An INSTANCE id resolves through `data-dev-id` only - it names one element, and a role match would
 * hand back its siblings. A SHARED id resolves through BOTH attributes, so a catalogue id keeps
 * reaching every element that carries it directly AND every instance that declares it as its role.
 */
export function nodesForDevId(devId: string, root: ParentNode = document): HTMLElement[] {
  if (isGeneratedDesignId(devId)) {
    return Array.from(root.querySelectorAll<HTMLElement>(designIdSelector(devId)));
  }
  const selector =
    devIdScope(devId) === "instance"
      ? devIdSelector(devId)
      : `${devIdSelector(devId)}, ${devRoleSelector(devId)}`;
  try {
    return Array.from(root.querySelectorAll<HTMLElement>(selector));
  } catch {
    // A committed override could hold an id no escape can turn into a selector. Reaching nothing is
    // the correct outcome; throwing out of the boot-time apply is not.
    return [];
  }
}

/** The one element an id names, or null. Never "the first of several" for an instance id. */
export function nodeForDevId(devId: string, root: ParentNode = document): HTMLElement | null {
  return nodesForDevId(devId, root)[0] ?? null;
}

/**
 * The shared role an element declares, or null when it only has an instance identity.
 *
 * This is what lets the Design panel offer "this one" and "all of these" as two separate edits
 * instead of guessing which the person meant.
 */
export function sharedRoleOf(el: Element | null | undefined): string | null {
  return el?.getAttribute("data-dev-role") ?? null;
}

/**
 * Every dev id currently in the document, de-duplicated and sorted.
 *
 * The catalogue cannot list a per-instance id, so searching the catalogue alone would never find
 * the tab of the component that is actually open. Enumerating the live DOM is the only honest
 * answer to "what can I address right now", and it is exact: each entry is an id some element is
 * carrying at this moment.
 */
export function renderedDevIds(root: ParentNode = document): string[] {
  const ids = new Set<string>();
  for (const el of root.querySelectorAll("[data-dev-id]")) {
    const id = el.getAttribute("data-dev-id");
    if (id) ids.add(id);
  }
  return [...ids].sort();
}
