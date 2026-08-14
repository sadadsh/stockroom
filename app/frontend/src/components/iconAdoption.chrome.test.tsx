import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Icon } from "./Icon";

// Render-diff guard for registry-backed chrome and list icons (Rail / SearchOverlay / PartsList).
// Literal fixtures lock the current owner-approved output, including later Design Studio artwork
// promotions. We canonicalise the rendered DOM (attrs sorted + names lowered, the theme-var `style`
// attribute excluded because jsdom's CSSOM mangles var()) and compare exact framed SVG output.
//
// Two nuances, both non-visual:
//  - The shared primary preset draws every primary glyph aria-hidden (decorative), which the rail's
//    bare svgProps glyphs did not spell out. aria-hidden is an a11y attribute, not geometry, so the
//    primary literals below include it; every drawing attribute is otherwise byte-identical, and the
//    geometry-equivalence assertions compare children against the approved catalogue bodies.
//  - The two sizeless rail nav glyphs (nav.components / nav.about) intentionally moved from a
//    parent-sized 17px box to h-full w-full, so they are asserted appearance-equivalent (same
//    viewBox + same child geometry), not byte-identical on the class string.

function canonical(el: Element): string {
  const attrs = Array.from(el.attributes)
    .map((a) => [a.name.toLowerCase(), a.value] as const)
    .filter(([name]) => name !== "style" && name !== "data-design-id")
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

// --- byte-identical cases: the registry render must equal the approved svg exactly ----------------
// One primary rail glyph with an explicit size, the brand wordmark (asserting the `ico` token),
// and a bespoke SearchOverlay glyph.
const IDENTICAL: Array<{ name: string; el: React.ReactElement; svg: string }> = [
  {
    name: "nav.theme (primary rail glyph, explicit h-4 w-4)",
    el: <Icon id="nav.theme" className="h-4 w-4 flex-none" />,
    svg:
      '<svg class="ico h-4 w-4 flex-none" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<g transform="translate(0 0) scale(0.09375)" fill="currentColor" stroke="none"><path fill="currentColor" d="M235.54 150.21a104.84 104.84 0 0 1-37 52.91A104 104 0 0 1 32 120a103.1 103.1 0 0 1 20.88-62.52a104.84 104.84 0 0 1 52.91-37a8 8 0 0 1 10 10a88.08 88.08 0 0 0 109.8 109.8a8 8 0 0 1 10 10Z"/></g></svg>',
  },
  {
    name: "brand.wordmark (brand, keeps the ico token)",
    el: <Icon id="brand.wordmark" className="ico h-5 w-5 flex-none text-t1" />,
    svg:
      '<svg class="ico h-5 w-5 flex-none text-t1" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
      '<g transform="translate(0 2.4000000000000004) scale(0.0375)" fill="currentColor" stroke="none"><path d="M560.3 237.2c10.4 11.8 28.3 14.4 41.8 5.5 14.7-9.8 18.7-29.7 8.9-44.4l-48-72c-2.8-4.2-6.6-7.7-11.1-10.2L351.4 4.7c-19.3-10.7-42.8-10.7-62.2 0L88.8 116c-5.4 3-9.7 7.4-12.6 12.8L27.7 218.7c-12.6 23.4-3.8 52.5 19.6 65.1l33 17.7 0 53.3c0 23 12.4 44.3 32.4 55.7l176 99.7c19.6 11.1 43.5 11.1 63.1 0l176-99.7c20.1-11.4 32.4-32.6 32.4-55.7l0-117.5zm-240-9.8L170.2 144 320.3 60.6 470.4 144 320.3 227.4zm-41.5 50.2l-21.3 46.2-165.8-88.8 25.4-47.2 161.7 89.8z"/></g></svg>',
  },
  {
    name: "overlay.chevron (SearchOverlay bespoke)",
    el: <Icon id="overlay.chevron" className="h-3 w-3 text-t3" />,
    svg:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" class="h-3 w-3 text-t3">' +
      '<path d="m6 9 6 6 6-6"/></svg>',
  },
];

describe("chrome/list icon adoption - render-diff (byte-identical)", () => {
  for (const { name, el, svg } of IDENTICAL) {
    it(`matches the approved svg: ${name}`, () => {
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
      '<svg><g transform="translate(0 0) scale(1)" fill="currentColor" stroke="none"><path fill="currentColor" d="M7.5 22q-1.45 0-2.475-1.025T4 18.5v-13q0-1.45 1.025-2.475T7.5 2H18q.825 0 1.413.587T20 4v12.525q0 .2-.162.363t-.588.362q-.35.175-.55.5t-.2.75t.2.763t.55.487t.55.413t.2.562v.25q0 .425-.288.725T19 22zm2.213-7.288Q10 14.425 10 14V5q0-.425-.288-.712T9 4t-.712.288T8 5v9q0 .425.288.713T9 15t.713-.288M7.5 20h9.325q-.15-.35-.237-.712T16.5 18.5q0-.4.075-.775t.25-.725H7.5q-.65 0-1.075.438T6 18.5q0 .65.425 1.075T7.5 20"/></g></svg>',
  },
  {
    name: "nav.about",
    el: <Icon id="nav.about" className="h-full w-full" />,
    viewBox: "0 0 24 24",
    body: '<svg><g transform="translate(0 0) scale(1)" fill="currentColor" stroke="none"><path fill="currentColor" d="M12.713 16.713Q13 16.425 13 16v-4q0-.425-.288-.712T12 11t-.712.288T11 12v4q0 .425.288.713T12 17t.713-.288m0-8Q13 8.425 13 8t-.288-.712T12 7t-.712.288T11 8t.288.713T12 9t.713-.288M12 22q-2.075 0-3.9-.788t-3.175-2.137T2.788 15.9T2 12t.788-3.9t2.137-3.175T8.1 2.788T12 2t3.9.788t3.175 2.137T21.213 8.1T22 12t-.788 3.9t-2.137 3.175t-3.175 2.138T12 22"/></g></svg>',
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
