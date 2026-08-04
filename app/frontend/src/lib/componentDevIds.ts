/**
 * Dev ids that carry a runtime component id.
 *
 * The catalogue in `devIds.ts` is a fixed list, so an element that exists once per OPEN COMPONENT
 * cannot have a row there. Those ids are built here instead, from one shared pattern:
 *
 *     component-browser.component[<component id>]
 *     component-browser.component[<component id>].tab
 *     component-browser.component[<component id>].representation[<kind>]
 *     component-browser.component[<component id>].provider[<provider id>]
 *
 * ONE builder, because the alternative is every call site interpolating an id into a template and
 * a second call site interpolating it slightly differently - at which point the ids are no longer
 * addressable and dev mode cannot find the element it was asked about.
 *
 * The id itself is bounded and stripped of the characters that would break the bracket grammar, so
 * a hostile or merely odd record id cannot forge a different element's id. Selectors go through
 * `CSS.escape` rather than string concatenation: a raw id in a selector is a parse error waiting
 * for the first part number with a quote or a bracket in it.
 */

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
