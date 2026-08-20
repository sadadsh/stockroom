/**
 * The typography kit is only worth having if it is the AUTHORITY, so these tests read the shipped
 * stylesheet and hold `TYPOGRAPHY_SCALE` to it property by property. A scale that only described
 * itself would be a second opinion beside the CSS, which is the exact failure the kit exists to end.
 *
 * The stylesheet is read through `node:fs` because `vite.config.ts` sets `test.css: false`: a CSS
 * import inside a test resolves to an empty string, so a computed-style assertion would pass
 * vacuously.
 */
// @ts-expect-error Vitest runs this source contract in Node; the browser bundle excludes Node types.
import { readFileSync } from "node:fs";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  ComponentMpn,
  PropertyLabel,
  PropertyValue,
  StatusText,
  TYPOGRAPHY_SCALE,
  TableHeader,
  type TypographyRole,
  type TypographyRoleName,
} from "./typography";
import { Badge } from "./primitives";

const css: string = readFileSync("src/styles/index.css", "utf8");

/** The declaration block of one `.ui-*` rule in the shipped stylesheet. */
function ruleBody(className: string): string {
  const match = css.match(new RegExp(`\\.${className}\\s*\\{([^}]*)\\}`));
  if (!match) throw new Error(`styles/index.css declares no .${className} rule`);
  return match[1];
}

function declaration(className: string, property: string): string {
  const body = ruleBody(className);
  const match = body.match(new RegExp(`(?:^|;|\\n)\\s*${property}\\s*:\\s*([^;]+);`));
  if (!match) throw new Error(`.${className} declares no ${property}`);
  return match[1].trim();
}

/** Resolve one level of var() against the :root block, so a token reads back as its px value. */
function resolve(value: string): string {
  const match = value.match(/^var\((--[\w-]+)\)$/);
  if (!match) return value;
  const declared = css.match(new RegExp(`${match[1]}:\\s*([^;]+);`));
  if (!declared) throw new Error(`index.css declares no ${match[1]}`);
  return declared[1].trim();
}

const TIER_TOKEN: Record<NonNullable<TypographyRole["tier"]>, string> = {
  primary: "var(--c-text-primary)",
  secondary: "var(--c-text-secondary)",
  label: "var(--c-text-label)",
  muted: "var(--c-text-muted)",
  disabled: "var(--c-text-disabled)",
};

const ROLES = Object.entries(TYPOGRAPHY_SCALE) as Array<[TypographyRoleName, TypographyRole]>;

describe("every role ships exactly what TYPOGRAPHY_SCALE claims", () => {
  it.each(ROLES)("%s", (_name, spec) => {
    expect(resolve(declaration(spec.className, "font-size"))).toBe(`${spec.fontSize}px`);
    expect(declaration(spec.className, "font-weight")).toBe(String(spec.fontWeight));
    expect(resolve(declaration(spec.className, "line-height"))).toBe(`${spec.lineHeight}px`);
    if (spec.tier) {
      expect(declaration(spec.className, "color")).toBe(TIER_TOKEN[spec.tier]);
    }
    if (spec.tabular) {
      expect(declaration(spec.className, "font-variant-numeric")).toBe("tabular-nums");
    }
  });
});

describe("the scale stays inside its budget", () => {
  it("spends four sizes, three weights and five tiers, and no more", () => {
    const specs = ROLES.map(([, spec]) => spec);
    expect([...new Set(specs.map((s) => s.fontSize))].sort((a, b) => b - a)).toEqual([
      14, 13, 11, 10,
    ]);
    expect([...new Set(specs.map((s) => s.fontWeight))].sort((a, b) => a - b)).toEqual([
      400, 500, 600,
    ]);
    const tiers = new Set(specs.map((s) => s.tier).filter(Boolean));
    expect(tiers.size).toBeLessThanOrEqual(5);
  });

  it("gives 14px to the canonical MPN and to nothing else", () => {
    const fourteens = ROLES.filter(([, s]) => s.fontSize === 14).map(([name]) => name);
    expect(fourteens).toEqual(["componentMpn"]);
  });

  it("keeps the MPN above the dialog title, and both above the body", () => {
    // The owner's diagnosis was that the MPN, the generated name, the description, the metadata,
    // the statuses and the actions all read as equally important. The ladder is the fix, so the
    // ladder is asserted rather than assumed.
    expect(TYPOGRAPHY_SCALE.componentMpn.fontSize).toBeGreaterThan(
      TYPOGRAPHY_SCALE.dialogTitle.fontSize,
    );
    expect(TYPOGRAPHY_SCALE.dialogTitle.fontSize).toBeGreaterThan(
      TYPOGRAPHY_SCALE.componentDescription.fontSize,
    );
    expect(TYPOGRAPHY_SCALE.componentDescription.fontSize).toBeGreaterThan(
      TYPOGRAPHY_SCALE.componentMetadata.fontSize,
    );
  });

  it("keeps the description and the metadata off the primary tier", () => {
    // A manufacturer blurb is not an identifier and a timestamp is not a value, so neither takes
    // the near-white reserved for identity and current values.
    expect(TYPOGRAPHY_SCALE.componentDescription.tier).toBe("secondary");
    expect(TYPOGRAPHY_SCALE.componentMetadata.tier).toBe("muted");
    expect(TYPOGRAPHY_SCALE.sourceText.tier).toBe("secondary");
    expect(TYPOGRAPHY_SCALE.componentMpn.tier).toBe("primary");
  });

  it("reserves monospace for machine text alone", () => {
    const monoRules = [...css.matchAll(/\.(ui-[\w-]+)\s*\{[^}]*font-family:/g)].map((m) => m[1]);
    expect(monoRules).toEqual(["ui-machine-text"]);
  });

  it("sets tabular figures wherever figures are read: prices, counts, dates, measurements", () => {
    for (const name of [
      "componentMpn",
      "componentMetadata",
      "keyFact",
      "rowMetadata",
      "machineText",
    ] as const) {
      expect(TYPOGRAPHY_SCALE[name].tabular, name).toBe(true);
    }
    expect(resolve(declaration("ui-numeric", "font-variant-numeric"))).toBe("tabular-nums");
    expect(declaration("ui-numeric", "text-align")).toBe("right");
  });
});

describe("the roles reach the DOM", () => {
  it("puts the role class on the element and keeps the caller's own utilities", () => {
    render(<ComponentMpn className="truncate">STM32F407VGT6</ComponentMpn>);
    const el = screen.getByText("STM32F407VGT6");
    expect(el.className.split(" ")).toContain("ui-component-mpn");
    expect(el.className.split(" ")).toContain("truncate");
  });

  it("renders a table header as a real th, because a column header has to be one", () => {
    render(
      <table>
        <thead>
          <tr>
            <TableHeader>Stock</TableHeader>
          </tr>
        </thead>
      </table>,
    );
    const th = screen.getByText("Stock");
    expect(th.tagName).toBe("TH");
    expect(th.className).toContain("ui-table-header");
  });

  it("right-aligns a numeric value and leaves an ordinary one alone", () => {
    render(
      <>
        <PropertyValue numeric>1,240</PropertyValue>
        <PropertyValue>Tape and reel</PropertyValue>
      </>,
    );
    expect(screen.getByText("1,240").className).toContain("ui-numeric");
    expect(screen.getByText("Tape and reel").className).not.toContain("ui-numeric");
  });

  it("paints an unavailable value in the disabled tier rather than fading it", () => {
    render(<PropertyValue disabled>Not stocked</PropertyValue>);
    expect(screen.getByText("Not stocked").className).toContain("ui-disabled");
    expect(screen.getByText("Not stocked").className).not.toMatch(/opacity-/);
  });

  it("keeps a property label off bold and off caps", () => {
    render(<PropertyLabel>Package</PropertyLabel>);
    const el = screen.getByText("Package");
    expect(el.className).not.toMatch(/font-(?:semi)?bold/);
    expect(el.className).not.toMatch(/uppercase|tracking-/);
    // And the role itself never turns them back on.
    expect(ruleBody("ui-property-label")).not.toMatch(/text-transform:\s*uppercase/);
    expect(ruleBody("ui-property-label")).not.toMatch(/letter-spacing:\s*[^n]/);
  });
});

describe("a status is not a button", () => {
  it("strips every affordance in the role itself, so no ancestor can lend it one", () => {
    const body = ruleBody("ui-status-text");
    expect(body).toContain("cursor: default");
    expect(body).toContain("border: 0");
    expect(body).toContain("background: none");
    expect(body).toContain("box-shadow: none");
  });

  it("renders as a bare span with a tone and nothing pressable", () => {
    render(<StatusText tone="warn">Incomplete</StatusText>);
    const el = screen.getByText("Incomplete");
    expect(el.tagName).toBe("SPAN");
    expect(el.className).toContain("ui-status-text");
    expect(el.className).toContain("text-warn");
    expect(el.className).not.toMatch(/cursor-pointer|hover:bg-|active:|focus-visible:outline/);
    expect(el.closest("button")).toBeNull();
    const mark = el.querySelector("svg");
    expect(mark).toHaveClass("ico");
    expect(mark).toHaveAttribute("viewBox", "0 0 24 24");
    expect(mark).toHaveAttribute("stroke-width", "2");
  });

  it("the Badge that feature code already uses is a status too, not a pill button", () => {
    // Badge shipped as a filled 12px pill with 10px of padding, which is the exact shape of the
    // primary action three inches away. It now carries the status role.
    render(<Badge tone="err">Missing footprint</Badge>);
    const el = screen.getByText("Missing footprint");
    expect(el.tagName).toBe("SPAN");
    expect(el.className).toContain("ui-status-text");
    expect(el.className).not.toMatch(/cursor-pointer|hover:|active:|focus-visible:|border-/);
  });
});
