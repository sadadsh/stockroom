/**
 * One status vocabulary for the whole product, and no unreachable code left behind.
 *
 * Both gates read app source as raw strings via Vite's `?raw` glob, the same technique
 * `devIds.parity.test.ts` uses and for the same reason: `node:fs` breaks `tsc -b`, which
 * type-checks this file too.
 *
 * THE VOCABULARY. Nine words, closed: Ready / Needs Review / Missing / Failed / Not Required /
 * Validated / Downloaded / Available / Unknown. The point of closing the set is that a word never
 * means two things on one screen. "Complete" is the word this gate exists to keep out: it has
 * previously meant non-empty text fields in one band, attached CAD files in a chip 12px away, and
 * placeability in Settings - one part, three verdicts, one word.
 */
import { describe, expect, it } from "vitest";
import { REPRESENTATION_STATUS_LABEL, statusTone } from "./component-workspace/workspaceStatus";
import type { WorkspaceStatus } from "./component-workspace/workspaceStatus";

const RAW = import.meta.glob("/src/**/*.{ts,tsx}", {
  query: "?raw",
  eager: true,
  import: "default",
}) as Record<string, string>;

const SOURCE: ReadonlyArray<readonly [string, string]> = Object.entries(RAW).filter(
  ([path]) => !/\.(test|spec)\.[jt]sx?$/.test(path),
);

/** Source with its comments removed: a rule about CODE must not convict its own documentation. */
function withoutComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|\s)\/\/.*$/gm, "");
}

/** The closed set, spelled here so the gate fails if the module quietly grows a tenth word. */
const VOCABULARY: readonly WorkspaceStatus[] = [
  "Ready",
  "Needs Review",
  "Missing",
  "Failed",
  "Not Required",
  "Validated",
  "Downloaded",
  "Available",
  "Unknown",
];

describe("the status vocabulary is closed and consistent", () => {
  it("scans a non-trivial amount of source (the glob is wired)", () => {
    expect(SOURCE.length).toBeGreaterThan(50);
  });

  it("gives every word in the set a tone, and no word two tones", () => {
    for (const word of VOCABULARY) {
      expect(typeof statusTone(word)).toBe("string");
    }
    // The three "it is fine" words are all the ok tone, and the two "act on this" words are not.
    expect(statusTone("Ready")).toBe(statusTone("Validated"));
    expect(statusTone("Ready")).toBe(statusTone("Downloaded"));
    expect(statusTone("Failed")).toBe("err");
    expect(statusTone("Missing")).toBe("warn");
    expect(statusTone("Needs Review")).toBe("warn");
    // "Not Required" and "Available" are facts, not verdicts, so neither is coloured as one.
    expect(statusTone("Not Required")).toBe("neutral");
    expect(statusTone("Available")).toBe("neutral");
  });

  it("maps every representation status onto a word from the set, and nothing else", () => {
    const labels = Object.values(REPRESENTATION_STATUS_LABEL);
    expect(labels.length).toBeGreaterThan(0);
    for (const label of labels) expect(VOCABULARY).toContain(label);
  });

  it("never lets a second word mean what a vocabulary word already means", () => {
    // The banned synonyms, each of which has a word in the set that already says it about a
    // COMPONENT or one of its artifacts:
    //   Complete / Done / OK -> Ready        (or Validated, when a recorded check passed)
    //   Incomplete           -> Missing      (or Needs Review)
    //   N/A                  -> Not Required
    //
    // A JOB's lifecycle is deliberately NOT convicted here. "This batch Completed" and "this
    // symbol is Ready" are statements about different subjects, and collapsing them would be the
    // same mistake in the other direction; that set is asserted closed on its own below.
    //
    // Matched as a whole word in a JSX text node or a quoted string, so `isComplete`,
    // `complete_only` and the `complete` facet count are untouched: those are DATA, not a label.
    const banned = /(?:^|["'>\s])(Complete|Incomplete|Done|OK|N\/A)(?:["'<.\s]|$)/;
    const offenders: string[] = [];
    for (const [path, raw] of SOURCE) {
      // The catalogue of dev ids is a list of element ids, not of status labels.
      if (path.endsWith("/lib/devIds.ts")) continue;
      for (const line of withoutComments(raw).split("\n")) {
        // Only lines plausibly rendering a STATUS: a badge, a chip, or a status map.
        if (!/Badge|status|Status|tone=/.test(line)) continue;
        // `err instanceof Error` is a JavaScript type check, not a label.
        if (/instanceof Error/.test(line)) continue;
        const hit = banned.exec(line);
        if (hit) offenders.push(`${path}: ${hit[1]}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("keeps the JOB lifecycle a separate closed set, about a different subject", () => {
    // A durable batch is not a component. It gets its own seven words, and the gate above lets
    // them through precisely because they never describe an artifact's readiness. Closing this
    // set too is what stops "the run Finished" appearing beside "the run Completed".
    const raw = RAW["/src/components/LibraryCompletionSection.tsx"];
    expect(raw).toBeTruthy();
    const block = /\{\s*queued: "Queued",[\s\S]*?\}\[batch\.status\]/.exec(raw)![0];
    const words = [...block.matchAll(/: "([A-Za-z]+)"/g)].map((m) => m[1]).sort();
    expect(words).toEqual([
      "Blocked",
      "Cancelled",
      "Completed",
      "Failed",
      "Paused",
      "Queued",
      "Running",
    ]);
  });
});

describe("no orphaned component is left rendered by nothing", () => {
  it("has no PinoutViewer: its one capability moved onto the table that already existed", () => {
    // Deleted rather than surfaced. Re-surfacing it would have put two pinout tables in one sheet
    // reading two different shapes of the same data, and the surviving `PinoutTable` renders every
    // column the record wrote where that one showed pin and name only. The filter came with it.
    const paths = Object.keys(RAW);
    expect(paths.some((path) => path.includes("PinoutViewer"))).toBe(false);
    const importers = SOURCE.filter(([, raw]) => /from ["'].*PinoutViewer["']/.test(raw));
    expect(importers.map(([path]) => path)).toEqual([]);
  });

  it("has a live importer for HandoffBand: it is rendered, not merely kept", () => {
    // The other half of the orphan decision. Surfaced rather than deleted, because it is the only
    // surface that renders the generated EDA registry - deleting it would have made
    // `EDA_DATA_FIELDS` dead, and with it the contract that a third EDA tool joins by declaring
    // `data_fields` and regenerating.
    const importers = SOURCE.filter(([path, raw]) =>
      /from ["'].*\/HandoffBand["']/.test(raw) && !path.endsWith("/HandoffBand.tsx"),
    );
    expect(importers.length).toBeGreaterThan(0);
  });
});
