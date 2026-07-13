import { describe, expect, it } from "vitest";
import { fuzzyScore, fuzzyScoreFields } from "./fuzzy";

describe("fuzzyScore", () => {
  it("matches an exact substring", () => {
    expect(fuzzyScore("comp", "Components")).not.toBeNull();
  });

  it("matches a non-contiguous subsequence", () => {
    // c-m-p is a subsequence of "Components"
    expect(fuzzyScore("cmp", "Components")).not.toBeNull();
  });

  it("rejects a query that is not a subsequence", () => {
    // "xyz" chars never appear in order in "Components"
    expect(fuzzyScore("xyz", "Components")).toBeNull();
    // right chars, wrong order: "s...t" cannot match because 's' comes last
    expect(fuzzyScore("sc", "Components")).toBeNull();
  });

  it("is case-insensitive", () => {
    expect(fuzzyScore("COMP", "components")).not.toBeNull();
    expect(fuzzyScore("comp", "COMPONENTS")).not.toBeNull();
  });

  it("scores an empty query as neutral (matches anything)", () => {
    expect(fuzzyScore("", "anything")).toBe(0);
  });

  it("ranks a start-anchored match above a mid-string match", () => {
    // "op" at the front of "op-amp" beats "op" buried inside "backdrop"
    const front = fuzzyScore("op", "op-amp")!;
    const buried = fuzzyScore("op", "backdrop")!;
    expect(front).toBeGreaterThan(buried);
  });

  it("ranks a word-boundary match above a same-word mid match", () => {
    // "gt" as the start of two words ("Go To") beats "gt" inside one word
    const boundary = fuzzyScore("gt", "Go To Settings")!;
    const inWord = fuzzyScore("gt", "targeting")!;
    expect(boundary).toBeGreaterThan(inWord);
  });

  it("ranks a contiguous run above a scattered subsequence", () => {
    const contiguous = fuzzyScore("set", "Settings")!;
    const scattered = fuzzyScore("set", "Silent Threats")!;
    expect(contiguous).toBeGreaterThan(scattered);
  });
});

describe("fuzzyScoreFields", () => {
  it("returns the best score across fields", () => {
    // matches "manufacturer" field, not "name"
    const score = fuzzyScoreFields("yageo", ["R 10k", "RC0402", "Yageo", "Passives"]);
    expect(score).not.toBeNull();
  });

  it("returns null only when no field matches", () => {
    expect(
      fuzzyScoreFields("zzz", ["R 10k", "RC0402", "Yageo", "Passives"]),
    ).toBeNull();
  });

  it("prefers the field with the strongest match", () => {
    // "cap" matches the front of one field and the middle of another; the front
    // (word-boundary + contiguous) must win so the best score is returned.
    const best = fuzzyScoreFields("cap", ["Capacitor", "Landscape"])!;
    const onlyBuried = fuzzyScore("cap", "Landscape")!;
    expect(best).toBeGreaterThan(onlyBuried);
  });
});
