/**
 * The issues list's vocabulary: the copy table, the fold from the structural tier, and the order.
 *
 * Every test names the mutation to `validatorIssues.ts` that would make it pass silently, because a
 * test over a data table is the shape most likely to be vacuous - a table asserted against itself
 * proves nothing.
 */
import { describe, expect, it } from "vitest";
import type { LayoutIssue, LayoutIssueCode } from "./document";
import {
  compareIssues,
  fromLayoutIssue,
  ISSUE_COPY,
  ISSUE_SEVERITY_ORDER,
  sortIssues,
  subjectKey,
  tokenPairSubject,
  VALIDATOR_ISSUE_SEVERITY,
  validatorIssue,
  type IssueCode,
  type ValidatorIssue,
} from "./validatorIssues";

/**
 * The structural codes, hand-listed HERE and nowhere else.
 *
 * `ISSUE_COPY` is typed `Record<IssueCode, IssueCopy>`, so a code with no entry is a compile error
 * and this list cannot be the thing that keeps the table complete. What it does is the other
 * direction: it pins the set the fold has to handle, so a code retired from `document.ts` without
 * its copy entry being retired shows up as a stale row below.
 */
const LAYOUT_CODES: readonly LayoutIssueCode[] = [
  "unsupported-schema-version",
  "unknown-layout-mode",
  "duplicate-id",
  "orphan-slot",
  "unknown-piece",
  "splitter-unknown-slot",
  "scroll-owner-conflict",
];

const OWN_CODES = Object.keys(VALIDATOR_ISSUE_SEVERITY) as (keyof typeof VALIDATOR_ISSUE_SEVERITY)[];

describe("the copy table", () => {
  it("carries an entry for every code and no entry for anything else", () => {
    // Killing mutation: leave a copy entry behind for a code that no longer exists. The type system
    // catches the missing direction; this catches the stale one, which it cannot.
    const expected = [...OWN_CODES, ...LAYOUT_CODES].sort();
    expect(Object.keys(ISSUE_COPY).sort()).toEqual(expected);
  });

  it("namespaces every copy id and never reuses one", () => {
    // Killing mutation: paste one code's copy id onto another. Two rows would then reword together,
    // which is the exact failure a stable id exists to prevent.
    const ids = Object.values(ISSUE_COPY).map((copy) => copy.id);
    for (const id of ids) expect(id.startsWith("layout-issues.")).toBe(true);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("keeps U+0079 out of every fallback, which the copy gate cannot see", () => {
    // THE LETTER RULE, checked here because it is not checked anywhere else for this file.
    // `copy.letterRule.test.ts` reads four SHAPES - a `<Text>` child, a `useText` default, an
    // id-paired label prop, a committed override - and a data table in a `.ts` module is none of
    // them, so a fallback authored with the letter would ship unnoticed.
    //
    // Killing mutation: write "visibility" or "style" into any fallback below. Both carry it.
    const offenders = Object.entries(ISSUE_COPY)
      .filter(([, copy]) => copy.fallback.includes("y"))
      .map(([code, copy]) => `${code}: ${copy.fallback}`);
    expect(offenders).toEqual([]);
  });

  it("states a fallback that is a sentence rather than a code name", () => {
    // Killing mutation: set every fallback to its own code. The panel would then render
    // "action-unreachable" at a person, which is the failure a fallback exists to prevent.
    for (const [code, copy] of Object.entries(ISSUE_COPY)) {
      expect(copy.fallback.length, code).toBeGreaterThan(20);
      expect(copy.fallback, code).toMatch(/\.$/);
      expect(copy.fallback, code).not.toContain(code);
    }
  });
});

describe("severity", () => {
  it("grades a measurement gap as information and a real finding as a warning", () => {
    // Killing mutation: grade `contrast-not-measured` as a warning. A row the owner cannot act on
    // would then sit in the same tier as a pairing that genuinely fails its floor.
    expect(VALIDATOR_ISSUE_SEVERITY["contrast-not-measured"]).toBe("info");
    expect(VALIDATOR_ISSUE_SEVERITY["auto-placed"]).toBe("info");
    expect(VALIDATOR_ISSUE_SEVERITY["style-role-exception"]).toBe("info");
    expect(VALIDATOR_ISSUE_SEVERITY["action-unreachable"]).toBe("warning");
    expect(VALIDATOR_ISSUE_SEVERITY["contrast-below-text-floor"]).toBe("warning");
  });

  it("has no tier that blocks", () => {
    // The plan's decision 3 as a type-level fact: two rungs, neither of them an error.
    expect(ISSUE_SEVERITY_ORDER).toEqual(["warning", "info"]);
    expect(Object.values(VALIDATOR_ISSUE_SEVERITY)).not.toContain("error");
  });

  it("builds an issue from the tables rather than from its caller", () => {
    // Killing mutation: let `validatorIssue` take a severity argument. Two call sites would then be
    // free to grade the same code differently.
    const issue = validatorIssue("action-unreachable", { kind: "action", id: "a.b" });
    expect(issue.severity).toBe("warning");
    expect(issue.copy).toBe(ISSUE_COPY["action-unreachable"]);
    expect(issue.detail).toBeUndefined();
    expect(issue.path).toBeUndefined();
  });
});

describe("the fold from the structural tier", () => {
  const layoutIssue = (severity: LayoutIssue["severity"]): LayoutIssue => ({
    code: "duplicate-id",
    severity,
    nodeId: "r.1",
    path: ["root", "r.1"],
    detail: { kind: "region" },
  });

  it("lands an error on a warning and keeps the original tier", () => {
    // Killing mutation: drop `detail.tier`. The fold would then be lossy and a panel could no longer
    // draw a document defect differently from a design judgement.
    const folded = fromLayoutIssue(layoutIssue("error"));
    expect(folded.severity).toBe("warning");
    expect(folded.detail).toEqual({ kind: "region", tier: "error" });
    expect(folded.path).toEqual(["root", "r.1"]);
  });

  it("leaves information as information", () => {
    expect(fromLayoutIssue(layoutIssue("info")).severity).toBe("info");
  });

  it("reads the subject kind off the code", () => {
    // Killing mutation: make every folded subject a region. `orphan-slot` names a slot and
    // `unknown-piece` names a placement, and the panel navigates by subject kind.
    const slot = fromLayoutIssue({
      code: "orphan-slot",
      severity: "warning",
      nodeId: "s.1",
      path: ["root", "s.1"],
    });
    expect(slot.subject).toEqual({ kind: "slot", id: "s.1" });
    const placement = fromLayoutIssue({
      code: "unknown-piece",
      severity: "error",
      nodeId: "p.1",
      path: ["root", "p.1"],
    });
    expect(placement.subject.kind).toBe("placement");
  });
});

describe("the order", () => {
  const issue = (
    code: IssueCode,
    severity: ValidatorIssue["severity"],
    subjectId: string,
  ): ValidatorIssue => ({
    code,
    severity,
    copy: ISSUE_COPY[code],
    subject: { kind: "action", id: subjectId },
  });

  it("puts every warning above every information row", () => {
    // Killing mutation: sort on code first. An informational auto-placement would then sit above a
    // warning whose code sorts later, and the panel's first row would stop being its worst row.
    const sorted = sortIssues([
      issue("auto-placed", "info", "a"),
      issue("action-unreachable", "warning", "z"),
    ]);
    expect(sorted.map((i) => i.severity)).toEqual(["warning", "info"]);
  });

  it("is total, so the same set sorts the same whatever order it arrives in", () => {
    // Killing mutation: stop comparing detail. Two rows differing only in their measured ratio would
    // then compare equal, and their relative order would follow the producer rather than the data.
    const rows: ValidatorIssue[] = [
      { ...issue("contrast-below-text-floor", "warning", "x"), subject: tokenPairSubject("light", "--c-t3", "--c-active"), detail: { ratio: 4.43 } },
      { ...issue("contrast-below-text-floor", "warning", "x"), subject: tokenPairSubject("light", "--c-t3", "--c-active"), detail: { ratio: 2.1 } },
      issue("action-unreachable", "warning", "b"),
      issue("action-unreachable", "warning", "a"),
      issue("auto-placed", "info", "c"),
    ];
    const forward = sortIssues(rows).map((i) => `${i.code}|${subjectKey(i.subject)}|${i.detail?.ratio ?? ""}`);
    const backward = sortIssues([...rows].reverse()).map(
      (i) => `${i.code}|${subjectKey(i.subject)}|${i.detail?.ratio ?? ""}`,
    );
    expect(forward).toEqual(backward);
    expect(forward[0]).toContain("action-unreachable|action:a");
  });

  it("is antisymmetric on every pair it is given", () => {
    const rows = [
      issue("action-unreachable", "warning", "a"),
      issue("piece-below-minimum", "warning", "b"),
      issue("auto-placed", "info", "c"),
    ];
    for (const left of rows) {
      for (const right of rows) {
        // Summed rather than negated, so the pair that compares equal reads as 0 rather than
        // tripping over `Object.is(-0, 0)`.
        expect(Math.sign(compareIssues(left, right)) + Math.sign(compareIssues(right, left))).toBe(0);
      }
    }
  });

  it("never sorts its input in place", () => {
    // Killing mutation: `issues.sort(compareIssues)`. A caller holding the array it passed in would
    // find it reordered under it.
    const rows = [issue("auto-placed", "info", "a"), issue("action-unreachable", "warning", "z")];
    const before = [...rows];
    sortIssues(rows);
    expect(rows).toEqual(before);
  });
});

describe("subjects", () => {
  it("derives a token pairing's id from its three parts", () => {
    // Killing mutation: type the id separately from the parts. The two could then disagree, and the
    // id is what ordering and de-duplication run on.
    const subject = tokenPairSubject("dark", "--c-t1", "--c-canvas");
    expect(subject.id).toBe("dark:--c-t1:--c-canvas");
    expect(subjectKey(subject)).toBe("token-pair:dark:--c-t1:--c-canvas");
  });
});
