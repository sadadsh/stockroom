import { describe, expect, it } from "vitest";

const RAW = import.meta.glob("/src/**/*.{ts,tsx}", {
  query: "?raw",
  eager: true,
  import: "default",
}) as Record<string, string>;

const SOURCE = Object.entries(RAW).filter(([path]) => !/\.(test|spec)\.[jt]sx?$/.test(path));

function matches(pattern: RegExp): string[] {
  return SOURCE.flatMap(([path, source]) =>
    [...source.matchAll(pattern)].map((match) => {
      const line = source.slice(0, match.index).split("\n").length;
      return `${path}:${line}:${match[0]}`;
    }),
  );
}

describe("the shared UI scheme", () => {
  it("uses the dedicated focus token instead of the selection accent", () => {
    expect(matches(/focus(?:-visible)?:[^\s"'`]*acc\b/g)).toEqual([]);
  });

  it("contains no retired semantic utilities that Tailwind cannot generate", () => {
    // ASTRYX theme token names such as `--color-text-accent` are CSS-variable contracts, not
    // retired Tailwind utilities. Guard executable class vocabulary only.
    expect(matches(/(?<!color-)\b(?:bg|text|border)-(?:panel(?:-2)?|positive|accent|err-soft)\b/g)).toEqual([]);
  });

  it("keeps interface text on the four-size typography scale", () => {
    expect(matches(/\btext-\[(?:[0-9](?:\.[0-9]+)?)px\]/g)).toEqual([]);
  });
});
