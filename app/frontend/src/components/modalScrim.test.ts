/**
 * A full-viewport overlay that dismisses on a press is never a control.
 *
 * Every in-window modal here puts a `fixed inset-0` scrim behind its dialog and closes when the
 * press lands on the scrim itself. That press is a POINTER convenience: the keyboard equivalent is
 * Escape answered by the top layer of `lib/useModalDismiss.ts`, which also traps Tab, restores
 * focus, and stacks z-index. So the scrim must stay OUT of the accessibility tree - `presentation`
 * on a surface, or `aria-hidden` on the click-outside catcher pattern. Exposing it instead puts a
 * second, unnamed way to close the window in front of the dialog's own Close control.
 *
 * This is a source gate because the drift it catches is a drift of CONVENTION, not of behaviour:
 * `AltiumDbLibModal` and `AltiumSetupModal` were each written from the same template as the other
 * eight modals and each simply omitted the attribute, and nothing failed. It reads app source as
 * raw strings via Vite's `?raw` glob, the same technique `statusVocabulary.test.ts` uses and for
 * the same reason: `node:fs` breaks `tsc -b`, which type-checks this file too.
 */
import { describe, expect, it } from "vitest";

const RAW = import.meta.glob("/src/**/*.tsx", {
  query: "?raw",
  eager: true,
  import: "default",
}) as Record<string, string>;

const SOURCE: ReadonlyArray<readonly [string, string]> = Object.entries(RAW).filter(
  ([path]) => !/\.(test|spec)\.[jt]sx?$/.test(path),
);

/** The handlers that make an element a press target, matching the a11y rule's own default set. */
const PRESS_HANDLER = /\bon(?:Click|MouseDown|MouseUp|KeyDown|KeyUp|KeyPress)=/;

/**
 * A tag with its comments removed.
 *
 * LOAD-BEARING, and the reason is a mistake this gate made about itself. Comments are legal between
 * JSX attributes, and every scrim here carries one that NAMES the attribute it is explaining. A
 * gate reading the raw tag therefore matched `role="presentation"` inside the prose and passed for
 * a scrim whose actual attribute had been deleted - it was asserting that the comment existed.
 */
function withoutComments(tag: string): string {
  return tag.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/\/\/[^\n]*/g, " ");
}

/**
 * The JSX opening tag containing `index`, or "" when the scan cannot find one.
 *
 * Walks back to the `<` that opens the tag, then forward to the `>` that closes it, tracking brace
 * depth and quotes so an arrow function in a handler (`onClick={() => ...}`) does not end the tag
 * at its own `>`.
 */
function openingTagAt(source: string, index: number): string {
  let start = index;
  while (start >= 0 && source[start] !== "<") start -= 1;
  if (start < 0) return "";

  let depth = 0;
  let quote = "";
  for (let at = start; at < source.length; at += 1) {
    const char = source[at];
    if (quote) {
      if (char === quote) quote = "";
      continue;
    }
    if (char === '"' || char === "'" || char === "`") {
      quote = char;
      continue;
    }
    if (char === "{") depth += 1;
    else if (char === "}") depth -= 1;
    else if (char === ">" && depth === 0) return source.slice(start, at + 1);
  }
  return "";
}

describe("the modal scrim convention", () => {
  it("scans a non-trivial amount of source (the glob is wired)", () => {
    expect(SOURCE.length).toBeGreaterThan(50);
  });

  it("finds the scrims it is meant to be guarding", () => {
    // A gate that matches nothing passes forever. This is the assertion that would have caught
    // the regex quietly ceasing to match after a class-name change.
    let overlays = 0;
    for (const [, raw] of SOURCE) {
      for (const match of raw.matchAll(/fixed inset-0/g)) {
        const tag = withoutComments(openingTagAt(raw, match.index));
        if (PRESS_HANDLER.test(tag)) overlays += 1;
      }
    }
    expect(overlays).toBeGreaterThanOrEqual(8);
  });

  it("reads the ATTRIBUTE, never a comment that merely names it", () => {
    // The self-check for the vacuity above: a tag whose only mention of the attribute is prose
    // must not count as carrying it, or the gate silently stops guarding every scrim that
    // documents itself - which is all of them.
    const documented = '<div className="fixed inset-0" /* role="presentation" */ onClick={x}>';
    expect(/role="presentation"/.test(documented)).toBe(true);
    expect(/role="presentation"/.test(withoutComments(documented))).toBe(false);
  });

  it("keeps every pressable full-viewport overlay out of the accessibility tree", () => {
    const exposed: string[] = [];
    for (const [path, raw] of SOURCE) {
      for (const match of raw.matchAll(/fixed inset-0/g)) {
        const tag = withoutComments(openingTagAt(raw, match.index));
        if (!PRESS_HANDLER.test(tag)) continue;
        const hidden = /role="presentation"/.test(tag) || /\baria-hidden\b/.test(tag);
        if (!hidden) {
          const line = raw.slice(0, match.index).split("\n").length;
          exposed.push(`${path}:${line}`);
        }
      }
    }
    expect(exposed).toEqual([]);
  });
});
