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

  it("prefers a tighter (shorter) candidate when the match is otherwise equal", () => {
    // Both are a full, start-anchored, contiguous match; only length differs, so
    // the length tie-breaker (score - t.length * k) is the only thing that can
    // separate them. Load-bearing: drop the length penalty and the two scores tie.
    const tight = fuzzyScore("op", "op")!;
    const loose = fuzzyScore("op", "opamp")!;
    expect(tight).toBeGreaterThan(loose);
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

  it("rewards a contiguous run of matches, isolated from length", () => {
    // Both candidates are the same length and both anchor the first char at the
    // start, so the run bonus for adjacent hits is the ONLY thing that can
    // separate their scores. This keeps the test load-bearing: drop the run bonus
    // and the two scores tie exactly, so `toBeGreaterThan` fails. (A naive test
    // comparing a short contiguous string to a long scattered one is a false
    // green: the length penalty alone would carry it even with no run bonus.)
    const contiguous = fuzzyScore("abc", "abcxx")!; // a-b-c adjacent
    const scattered = fuzzyScore("abc", "axbxc")!; // a, b, c spread apart
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
