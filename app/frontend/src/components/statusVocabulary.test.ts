/**
 * One status vocabulary for the whole product, and no unreachable code left behind.
 *
 * Both gates read app source as raw strings via Vite's `?raw` glob, the same technique
 * `devIds.parity.test.ts` uses and for the same reason: `node:fs` breaks `tsc -b`, which
 * type-checks this file too.
 *
 * THE VOCABULARY. Five words, closed: Ready / Needs Review / Missing / Failed / Not Required. The
 * point of closing the set is that a word never means two things on one screen. "Complete" is the
 * word this gate exists to keep out: it has previously meant non-empty text fields in one band,
 * attached CAD files in a chip 12px away, and placeability in Settings - one part, three verdicts,
 * one word.
 *
 * `Validated`, `Downloaded`, `Available` and `Unknown` were once listed here as a sixth through
 * ninth word. They are real words on the opened component and they belong to OTHER closed sets with
 * other subjects: `CadAssetStatus` (asserted below) says what a CAD asset is, and `CoverageStatus`
 * in the Manage Models provider list says what a provider has. Neither is a `WorkspaceStatus`, so
 * nothing could produce those four as one, and `statusTone` had four entries no caller could reach.
 * The two assertions that now close this set are what keep such a word from being re-added: one
 * reads the union out of the module and holds it to the list spelled below, and the other holds
 * every word in the list to being something `REPRESENTATION_STATUS_LABEL` can actually produce.
 */
import { describe, expect, it } from "vitest";
import {
  REPRESENTATION_STATUS_LABEL,
  cadAssetStatus,
  cadStatusTone,
  statusTone,
} from "./component-workspace/workspaceStatus";
import type { CadAssetStatus, WorkspaceStatus } from "./component-workspace/workspaceStatus";

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

/** The closed set, spelled here so the gate fails if the module quietly grows a sixth word. */
const VOCABULARY: readonly WorkspaceStatus[] = [
  "Ready",
  "Needs Review",
  "Missing",
  "Failed",
  "Not Required",
];

/**
 * The union as the MODULE declares it, read out of its source.
 *
 * A `type` leaves nothing behind at runtime, so the words are lifted from the declaration the same
 * way the job lifecycle below is lifted from its map. Without this, the list above could be trimmed
 * while the union kept a word - which is the state this whole file exists to make impossible.
 */
const DECLARED: readonly string[] = (() => {
  const raw = RAW["/src/components/component-workspace/workspaceStatus.ts"];
  const union = /export type WorkspaceStatus =[\s\S]*?;/.exec(raw ?? "")?.[0] ?? "";
  return [...union.matchAll(/"([^"]+)"/g)].map((m) => m[1]);
})();

describe("the status vocabulary is closed and consistent", () => {
  it("scans a non-trivial amount of source (the glob is wired)", () => {
    expect(SOURCE.length).toBeGreaterThan(50);
  });

  it("declares exactly the words listed here, and no more", () => {
    // Reads the union out of the module, so trimming the list above without trimming the type -
    // or growing the type without saying so here - fails rather than passing quietly.
    expect(DECLARED.length).toBeGreaterThan(0);
    expect([...DECLARED].sort()).toEqual([...VOCABULARY].sort());
  });

  it("gives every word in the set a tone, and no word two tones", () => {
    for (const word of VOCABULARY) {
      expect(typeof statusTone(word)).toBe("string");
    }
    expect(statusTone("Ready")).toBe("ok");
    expect(statusTone("Failed")).toBe("err");
    expect(statusTone("Missing")).toBe("warn");
    expect(statusTone("Needs Review")).toBe("warn");
    // "Not Required" is a fact, not a verdict, so it is not coloured as one.
    expect(statusTone("Not Required")).toBe("neutral");
  });

  it("maps every representation status onto a word from the set, and every word onto a status", () => {
    const labels = Object.values(REPRESENTATION_STATUS_LABEL);
    expect(labels.length).toBeGreaterThan(0);
    for (const label of labels) expect(VOCABULARY).toContain(label);
    // BOTH directions. One direction alone lets the set keep a word nothing can produce, which is
    // how `Downloaded` and `Unknown` survived here for as long as they did: a tone entry and a
    // line in a list are not a code path, and a badge that can never be rendered is not a status.
    // The only producer of a `WorkspaceStatus` in this codebase is the map above, so its range IS
    // the vocabulary; a word that wants in has to arrive with something that emits it.
    expect([...VOCABULARY].sort()).toEqual([...new Set(labels)].sort());
  });

  it("never lets a second word mean what a vocabulary word already means", () => {
    // The banned synonyms, each of which has a word in the set that already says it about a
    // COMPONENT or one of its artifacts:
    //   Complete / Done / OK -> Ready        (or Validated, when a recorded check passed)
    //   N/A                  -> Not Required
    //
    // `Incomplete` USED to be banned here as a synonym of Missing, and it no longer is, because
    // the two turned out to name different conditions once a CAD asset could be measured rather
    // than merely counted. `Missing` is "no file is attached"; `Incomplete` is "the file IS
    // attached and its terminals are unnumbered or numbered twice" - a file that exists and
    // cannot be mapped. Reporting the second as the first sends a person to download a file they
    // already have. The CAD vocabulary is closed on its own below, which is what keeps this from
    // being a licence for a tenth word.
    //
    // A JOB's lifecycle is deliberately NOT convicted here. "This batch Completed" and "this
    // symbol is Ready" are statements about different subjects, and collapsing them would be the
    // same mistake in the other direction; that set is asserted closed on its own below.
    //
    // Matched as a whole word in a JSX text node or a quoted string, so `isComplete`,
    // `complete_only` and the `complete` facet count are untouched: those are DATA, not a label.
    const banned = /(?:^|["'>\s])(Complete|Done|OK|N\/A)(?:["'<.\s]|$)/;
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

  it("closes the CAD asset vocabulary at the nine words the owner fixed", () => {
    // A CAD asset speaks its OWN nine words, and "Ready" is deliberately not among them: a file
    // that merely exists and a file a recorded check has passed are not the same claim, and
    // calling both of them ready is how a component with an unvalidated footprint gets sent to a
    // fabricator. Each of the nine is reachable from real evidence, which is what stops the set
    // from growing a word nothing can produce.
    const CAD_VOCABULARY: readonly CadAssetStatus[] = [
      "Available",
      "Validated",
      "Needs Review",
      "Missing",
      "Failed",
      "Not Required",
      "Package Matched",
      "Pin Match Failed",
      "Incomplete",
    ];
    for (const word of CAD_VOCABULARY) expect(typeof cadStatusTone(word)).toBe("string");

    const view = (status: "ready" | "missing" | "failed" | "review" | "not_required", checks: unknown[] = []) => ({
      kind: "symbol" as const,
      status,
      selectedTool: "kicad",
      tools: [
        {
          tool: "kicad",
          toolLabel: "KiCad",
          status,
          present: status !== "missing" && status !== "not_required",
          embedded: false,
          reference: { lib: "", name: "X", file: "" },
          sourceId: "",
          sourceLabel: "",
          sourceUrl: "",
          capturedAt: "",
          checks: checks as never,
        },
      ],
      sourceLabel: "",
      issue: null,
    });

    const produced = new Set<CadAssetStatus>([
      cadAssetStatus(view("ready")),
      cadAssetStatus(view("missing")),
      cadAssetStatus(view("failed")),
      cadAssetStatus(view("review")),
      cadAssetStatus(view("not_required")),
      cadAssetStatus(view("ready"), {
        terminals: 5,
        expected: 8,
        duplicates: 0,
        unnumbered: 0,
      }),
      cadAssetStatus(view("ready"), {
        terminals: 8,
        expected: 8,
        duplicates: 1,
        unnumbered: 0,
      }),
      cadAssetStatus(
        view("ready", [
          { check: "package_vs_pads", measured: "SOIC-8", expected: "SOIC-8", against: "", checkedAt: "", note: "" },
        ]),
      ),
      cadAssetStatus(
        view("ready", [
          { check: "pins_vs_datasheet", measured: 8, expected: 8, against: "", checkedAt: "", note: "" },
        ]),
      ),
    ]);
    expect([...produced].sort()).toEqual([...CAD_VOCABULARY].sort());
    expect(produced.has("Ready" as never)).toBe(false);
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
