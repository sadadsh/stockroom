// @ts-expect-error The browser build intentionally excludes Node ambient types; Vitest runs this
// contract in Node so it can test the exact CSS source rather than duplicating token literals.
import { readFileSync } from "node:fs";

type Rgba = readonly [number, number, number, number];

const css = readFileSync("src/styles/index.css", "utf8");

function themeBlock(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`${escaped}\\s*\\{([\\s\\S]*?)\\n\\s*\\}`));
  if (!match) {
    throw new Error(`Missing CSS theme block: ${selector}; input starts ${JSON.stringify(css.slice(0, 80))}`);
  }
  return match[1];
}

function property(block: string, name: string): string {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = block.match(new RegExp(`${escaped}\\s*:\\s*([^;]+);`));
  if (!match) throw new Error(`Missing CSS property: ${name}`);
  return match[1].trim();
}

function parseColor(value: string): Rgba {
  const hex = value.match(/^#([0-9a-f]{6})$/i);
  if (hex) {
    const packed = Number.parseInt(hex[1], 16);
    return [(packed >> 16) & 255, (packed >> 8) & 255, packed & 255, 1];
  }

  const rgba = value.match(
    /^rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(0(?:\.\d+)?|1(?:\.0+)?)\s*\)$/i,
  );
  if (rgba) {
    return [
      Number.parseInt(rgba[1], 10),
      Number.parseInt(rgba[2], 10),
      Number.parseInt(rgba[3], 10),
      Number.parseFloat(rgba[4]),
    ];
  }

  throw new Error(`Unsupported CSS color in contrast contract: ${value}`);
}

function composite(foreground: Rgba, background: Rgba): Rgba {
  const alpha = foreground[3] + background[3] * (1 - foreground[3]);
  return [
    (foreground[0] * foreground[3] +
      background[0] * background[3] * (1 - foreground[3])) /
      alpha,
    (foreground[1] * foreground[3] +
      background[1] * background[3] * (1 - foreground[3])) /
      alpha,
    (foreground[2] * foreground[3] +
      background[2] * background[3] * (1 - foreground[3])) /
      alpha,
    alpha,
  ];
}

function channelLuminance(channel: number): number {
  const normalized = channel / 255;
  return normalized <= 0.04045
    ? normalized / 12.92
    : ((normalized + 0.055) / 1.055) ** 2.4;
}

function luminance(color: Rgba): number {
  return (
    0.2126 * channelLuminance(color[0]) +
    0.7152 * channelLuminance(color[1]) +
    0.0722 * channelLuminance(color[2])
  );
}

function contrastRatio(foreground: Rgba, background: Rgba): number {
  const flattened = composite(foreground, background);
  const lighter = Math.max(luminance(flattened), luminance(background));
  const darker = Math.min(luminance(flattened), luminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

describe("CompletePartModal provider-route text contrast", () => {
  const textTokens = ["--c-t2", "--c-ok-text", "--c-warn-text", "--c-err-text"] as const;
  const themes = [
    ["dark", ":root"],
    ["light", ":root[data-theme=\"light\"]"],
  ] as const;

  it.each(themes)("%s theme keeps every 2xs ledger text token at WCAG AA", (_theme, selector) => {
    const block = themeBlock(selector);
    const popover = parseColor(property(block, "--c-popover"));
    const completeTint = parseColor(property(block, "--c-ok"));
    const partialTint = parseColor(property(block, "--c-warn"));
    const surfaces = [
      ["popover", popover],
      ["complete card", composite([completeTint[0], completeTint[1], completeTint[2], 0.07], popover)],
      ["partial card", composite([partialTint[0], partialTint[1], partialTint[2], 0.07], popover)],
    ] as const;

    for (const token of textTokens) {
      const text = parseColor(property(block, token));
      for (const [surfaceName, surface] of surfaces) {
        const ratio = contrastRatio(text, surface);
        expect(ratio, `${token} contrast against ${surfaceName}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  // VA-014. The FILES checklist pills ("Needed") are the quiet --c-t3 tier on a CHIP inside the
  // file card, which is a third composite the ledger case above never reached: the case only ever
  // measured --c-t2/--c-ok-text/--c-warn-text/--c-err-text against the card itself, so it stayed
  // green while the worst offender in this window failed. On the raised `bg-raise2` chip the dark
  // theme measured 2.92:1. The chip is the recessed `--c-field` step now, and both themes are
  // asserted here so the pairing cannot silently regress again.
  it.each(themes)("%s theme keeps the FILES checklist pill at WCAG AA", (_theme, selector) => {
    const block = themeBlock(selector);
    const popover = parseColor(property(block, "--c-popover"));
    const helper = parseColor(property(block, "--c-t3"));
    const chip = parseColor(property(block, "--c-field"));
    const completeTint = parseColor(property(block, "--c-ok"));
    const partialTint = parseColor(property(block, "--c-warn"));
    const cards = [
      ["file card", composite(parseColor(property(block, "--c-raise")), popover)],
      ["complete card", composite([completeTint[0], completeTint[1], completeTint[2], 0.07], popover)],
      ["partial card", composite([partialTint[0], partialTint[1], partialTint[2], 0.07], popover)],
    ] as const;

    for (const [cardName, card] of cards) {
      const ratio = contrastRatio(helper, composite(chip, card));
      expect(ratio, `--c-t3 contrast against the ${cardName} pill`).toBeGreaterThanOrEqual(4.5);
    }
  });
});
