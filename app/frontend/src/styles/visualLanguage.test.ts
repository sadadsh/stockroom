// @ts-expect-error Vitest runs this source contract in Node; the browser bundle excludes Node types.
import { readFileSync } from "node:fs";

const css = readFileSync("src/styles/index.css", "utf8");
const librarySources = [
  "src/components/PartsList.tsx",
  "src/components/SearchOverlay.tsx",
  "src/pages/ComponentsPage.tsx",
].map((path) => readFileSync(path, "utf8"));

function themeBlock(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(
    new RegExp(`${escaped}\\s*\\{([\\s\\S]*?)\\n\\s*\\}`),
  );
  if (!match) throw new Error(`Missing theme block: ${selector}`);
  return match[1];
}

function property(block: string, name: string): string {
  const match = block.match(
    new RegExp(`${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*:\\s*([^;]+);`),
  );
  if (!match) throw new Error(`Missing CSS property: ${name}`);
  return match[1].trim();
}

function rgb(value: string): [number, number, number] {
  const match = value.match(/^#([0-9a-f]{6})$/i);
  if (!match) throw new Error(`Expected an opaque six-digit color, received ${value}`);
  const packed = Number.parseInt(match[1], 16);
  return [(packed >> 16) & 255, (packed >> 8) & 255, packed & 255];
}

function luminance(color: [number, number, number]): number {
  const channels = color.map((channel) => {
    const normalized = channel / 255;
    return normalized <= 0.04045
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrast(left: string, right: string): number {
  const a = luminance(rgb(left));
  const b = luminance(rgb(right));
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

describe("Library semantic visual language", () => {
  it("owns every compact text role with named tokens and no sub-10px UI text", () => {
    for (const role of [
      "meta",
      "caption",
      "body",
      "label",
      "heading",
      "subtitle",
      "title",
    ]) {
      expect(css).toContain(`--fs-ui-${role}:`);
    }

    const minima = [...css.matchAll(/--fs-ui-[\w-]+:\s*clamp\(([\d.]+)px/g)].map(
      (match) => Number(match[1]),
    );
    expect(minima.length).toBe(7);
    expect(Math.min(...minima)).toBeGreaterThanOrEqual(10);
    expect(librarySources.join("\n")).not.toMatch(
      /text-\[(?:9|10|13)(?:\.\d+)?px\]/,
    );
  });

  it.each([
    ["dark", ":root"],
    ["light", ':root[data-theme="light"]'],
  ])("%s helper text passes AA on every Library base surface", (_theme, selector) => {
    const block = themeBlock(selector);
    const helper = property(block, "--c-t3");
    for (const surfaceToken of ["--c-canvas", "--c-band", "--c-popover"]) {
      expect(
        contrast(helper, property(block, surfaceToken)),
        `${surfaceToken} helper contrast`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });
});
