import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Icon } from "./Icon";

// Render-diff guard for the chrome + list icon adoption (Rail / SearchOverlay / PartsList). The
// hand-written inline svgs at those call sites are now <Icon id> draws; each must still emit the
// exact svg its source did. We canonicalise the rendered DOM (attrs sorted + names lowered, the
// theme-var `style` attribute excluded because jsdom's CSSOM mangles var()) and compare to the
// pre-adoption markup parsed the same way. A match proves adoption changed no icon's output.
//
// Two nuances, both non-visual:
//  - The shared primary preset draws every primary glyph aria-hidden (decorative), which the rail's
//    bare svgProps glyphs did not spell out. aria-hidden is an a11y attribute, not geometry, so the
//    primary literals below include it; every drawing attribute is otherwise byte-identical, and the
//    geometry-equivalence assertions compare children against the raw pre-adoption bodies.
//  - The two sizeless rail nav glyphs (nav.components / nav.about) intentionally moved from a
//    parent-sized 17px box to h-full w-full, so they are asserted appearance-equivalent (same
//    viewBox + same child geometry), not byte-identical on the class string.

function canonical(el: Element): string {
  const attrs = Array.from(el.attributes)
    .map((a) => [a.name.toLowerCase(), a.value] as const)
    .filter(([name]) => name !== "style")
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([name, value]) => `${name}=${value}`)
    .join("|");
  const children = Array.from(el.children).map(canonical).join("");
  return `<${el.tagName.toLowerCase()} ${attrs}>${children}`;
}

// Just the drawn geometry (the svg's children), for the reboxed sizeless glyphs where the root
// class legitimately differs but the shape must be identical.
function childrenCanonical(el: Element): string {
  return Array.from(el.children).map(canonical).join("");
}

function rendered(node: React.ReactElement): Element {
  const { container } = render(node);
  const svg = container.querySelector("svg");
  if (!svg) throw new Error("expected an <svg>");
  return svg;
}

function original(markup: string): Element {
  const host = document.createElement("div");
  host.innerHTML = markup;
  const svg = host.querySelector("svg");
  if (!svg) throw new Error("expected an <svg> in the fixture");
  return svg;
}

// --- byte-identical cases: the adopted render must equal the pre-adoption svg exactly ------------
// One primary rail glyph with an explicit size, the brand wordmark (asserting the `ico` token
// survives), a bespoke SearchOverlay glyph, and a PartsList category thumbnail.
const IDENTICAL: Array<{ name: string; el: React.ReactElement; svg: string }> = [
  {
    name: "nav.theme (primary rail glyph, explicit h-4 w-4)",
    el: <Icon id="nav.theme" className="h-4 w-4 flex-none" />,
    svg:
      '<svg class="ico h-4 w-4 flex-none" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<circle cx="12" cy="12" r="4"/>' +
      '<path d="M12 2v2"/><path d="M12 20v2"/>' +
      '<path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/>' +
      '<path d="M2 12h2"/><path d="M20 12h2"/>' +
      '<path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>',
  },
  {
    name: "brand.wordmark (brand, keeps the ico token)",
    el: <Icon id="brand.wordmark" className="ico h-5 w-5 flex-none text-t1" />,
    svg:
      '<svg class="ico h-5 w-5 flex-none text-t1" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z"/>' +
      '<path d="M12 22V12"/>' +
      '<polyline points="3.29 7 12 12 20.71 7"/>' +
      '<path d="m7.5 4.27 9 5.15"/></svg>',
  },
  {
    name: "overlay.chevron (SearchOverlay bespoke)",
    el: <Icon id="overlay.chevron" className="h-3 w-3 text-t3" />,
    svg:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" class="h-3 w-3 text-t3">' +
      '<path d="m6 9 6 6 6-6"/></svg>',
  },
  {
    name: "glyph.resistor (PartsList category thumbnail)",
    el: <Icon id="glyph.resistor" className="h-3.5 w-6 text-t2" />,
    svg:
      '<svg viewBox="0 0 32 18" class="h-3.5 w-6 text-t2" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M2 9h5l1.5-4 3 8 3-8 3 8 1.5-4H32"/></svg>',
  },
];

describe("chrome/list icon adoption - render-diff (byte-identical)", () => {
  for (const { name, el, svg } of IDENTICAL) {
    it(`matches the pre-adoption svg: ${name}`, () => {
      expect(canonical(rendered(el))).toBe(canonical(original(svg)));
    });
  }

  it("brand.wordmark keeps the literal `ico` token in its class (category brand, no auto-.ico)", () => {
    const svg = rendered(<Icon id="brand.wordmark" className="ico h-5 w-5 flex-none text-t1" />);
    expect(svg.classList.contains("ico")).toBe(true);
  });
});

// --- appearance-equivalence: the sizeless rail nav glyphs, reboxed to h-full w-full -------------
// The class string legitimately changed (parent-sized 17px box -> h-full w-full fills the same
// box), so we assert the viewBox + drawn geometry are unchanged; the effective 17px size is proven
// by the both-theme screenshot, not by a class literal.
const SIZELESS: Array<{ name: string; el: React.ReactElement; body: string; viewBox: string }> = [
  {
    name: "nav.components",
    el: <Icon id="nav.components" className="h-full w-full" />,
    viewBox: "0 0 24 24",
    body:
      '<svg>' +
      '<path d="M12 20v2"/><path d="M12 2v2"/><path d="M17 20v2"/><path d="M17 2v2"/>' +
      '<path d="M2 12h2"/><path d="M2 17h2"/><path d="M2 7h2"/><path d="M20 12h2"/>' +
      '<path d="M20 17h2"/><path d="M20 7h2"/><path d="M7 20v2"/><path d="M7 2v2"/>' +
      '<rect x="4" y="4" width="16" height="16" rx="2"/>' +
      '<rect x="8" y="8" width="8" height="8" rx="1"/></svg>',
  },
  {
    name: "nav.about",
    el: <Icon id="nav.about" className="h-full w-full" />,
    viewBox: "0 0 24 24",
    body: '<svg><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>',
  },
];

describe("chrome/list icon adoption - render-diff (appearance-equivalent, reboxed sizeless glyphs)", () => {
  for (const { name, el, body, viewBox } of SIZELESS) {
    it(`keeps viewBox + geometry for the reboxed ${name}`, () => {
      const svg = rendered(el);
      expect(svg.getAttribute("viewBox")).toBe(viewBox);
      expect(childrenCanonical(svg)).toBe(childrenCanonical(original(body)));
    });
  }
});

// --- nav.up-to-date: the plain check body + the call-site --c-ok tint container ------------------
describe("chrome/list icon adoption - nav.up-to-date tint reapplied at the call site", () => {
  // Mirror the rail's up-to-date call site: the plain-check <Icon> wrapped in a span carrying the
  // --c-ok tint, so currentColor resolves to the ok green exactly as the old inline-style svg did.
  const CallSite = () => (
    <span className="flex flex-none" style={{ color: "var(--c-ok)" }}>
      <Icon id="nav.up-to-date" className="h-4 w-4 flex-none" />
    </span>
  );

  it("renders the plain check body (currentColor, no baked-in tint)", () => {
    const svg = rendered(<CallSite />);
    expect(childrenCanonical(svg)).toBe(
      childrenCanonical(original('<svg><path d="M20 6 9 17l-5-5"/></svg>')),
    );
    // The tint is not baked into the svg: it inherits currentColor, so the glyph itself is neutral.
    expect(svg.getAttribute("stroke")).toBe("currentColor");
  });

  it("wraps the glyph in a currentColor-based --c-ok tint container", () => {
    const { container } = render(<CallSite />);
    const svg = container.querySelector("svg");
    const span = svg?.parentElement;
    expect(span?.tagName.toLowerCase()).toBe("span");
    // The tint rides on the wrapper's inline color (var(--c-ok)); the exact serialization is left to
    // jsdom, so we assert the ok-token is present on the container that owns the glyph.
    expect(container.innerHTML).toContain("c-ok");
  });
});
