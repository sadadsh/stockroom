import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Icon } from "./Icon";

// Render-diff guard for the non-modal <Icon> adoption (D-06) under the D-03 constraint (adoption may
// change NO icon's appearance). DetailPanel's glyphs, the ProjectsPage card thumbnail, and the Finder
// filter toggle are now drawn by <Icon id>; each must still emit the exact svg its hand-written source
// did. We canonicalise the rendered DOM (attrs sorted + names lowered) and compare it to the original
// markup, captured verbatim as it stood before this plan, parsed the same way. A match proves adoption
// changed no icon's output.
//
// Two attributes are excluded from the appearance compare because neither is a visual property:
//   - `style`      : jsdom's CSSOM mangles var() (mirrors iconWrappers.test.tsx).
//   - `aria-hidden`: an a11y hint, not appearance. detail.select-chevron's source svg was aria-hidden;
//                    a bespoke <Icon> without a title carries no aria attribute, and per the registry
//                    note (D-03) dropping it is acceptable. It is asserted separately below.
function canonical(el: Element): string {
  const attrs = Array.from(el.attributes)
    .map((a) => [a.name.toLowerCase(), a.value] as const)
    .filter(([name]) => name !== "style" && name !== "aria-hidden")
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([name, value]) => `${name}=${value}`)
    .join("|");
  const children = Array.from(el.children).map(canonical).join("");
  return `<${el.tagName.toLowerCase()} ${attrs}>${children}`;
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

// The original hand-written svg markup for each adopted call site, lifted verbatim from the source as
// it stood before this plan (JSX camelCase attrs are written here in their rendered kebab-case form).
const CASES: Array<{ name: string; el: React.ReactElement; svg: string }> = [
  {
    // DetailPanel: the Complete-Part row chevron.
    name: "detail.chevron-right",
    el: <Icon id="detail.chevron-right" className="h-3.5 w-3.5 flex-none text-t3" />,
    svg:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" class="h-3.5 w-3.5 flex-none text-t3">' +
      '<path d="m9 18 6-6-6-6"/></svg>',
  },
  {
    // DetailPanel: the readiness check. Its --c-ok tint is a root stroke ATTRIBUTE (not a style), so it
    // survives the canonical compare and is asserted explicitly below.
    name: "detail.ready-check",
    el: <Icon id="detail.ready-check" className="h-3.5 w-3.5 flex-none" />,
    svg:
      '<svg viewBox="0 0 24 24" fill="none" stroke="var(--c-ok)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" class="h-3.5 w-3.5 flex-none">' +
      '<path d="M20 6 9 17l-5-5"/></svg>',
  },
  {
    // DetailPanel: the category-select caret. The source carried aria-hidden="true"; the adopted <Icon>
    // drops it (excluded from the compare, asserted separately).
    name: "detail.select-chevron",
    el: (
      <Icon
        id="detail.select-chevron"
        className="pointer-events-none absolute right-1.5 top-1/2 h-3 w-3 -translate-y-1/2 text-t3"
      />
    ),
    svg:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="pointer-events-none absolute right-1.5 top-1/2 h-3 w-3 -translate-y-1/2 text-t3">' +
      '<path d="m6 9 6 6 6-6"/></svg>',
  },
  {
    // ProjectsPage: the project-card thumbnail (lucide circuit-board, echoing the Projects nav glyph).
    name: "glyph.project",
    el: <Icon id="glyph.project" className="h-[18px] w-[18px]" />,
    svg:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="h-[18px] w-[18px]">' +
      '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M11 9h4a2 2 0 0 0 2-2V3"/><circle cx="9" cy="9" r="2"/>' +
      '<path d="M7 21v-4a2 2 0 0 1 2-2h4"/><circle cx="15" cy="15" r="2"/></svg>',
  },
  {
    // Finder: the filter toggle (lucide list-filter). Its size 15 comes from the registry entry,
    // matching the source width/height 15; no size className is passed.
    name: "finder.filter",
    el: <Icon id="finder.filter" />,
    svg:
      '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M2 5h20"/><path d="M6 12h12"/><path d="M9 19h6"/></svg>',
  },
];

describe("non-modal <Icon> adoption - render-diff", () => {
  for (const { name, el, svg } of CASES) {
    it(`matches the pre-adoption svg: ${name}`, () => {
      expect(canonical(rendered(el))).toBe(canonical(original(svg)));
    });
  }

  it("keeps detail.ready-check's --c-ok stroke (a root attribute, not a style)", () => {
    const svg = rendered(<Icon id="detail.ready-check" className="h-3.5 w-3.5 flex-none" />);
    expect(svg.getAttribute("stroke")).toBe("var(--c-ok)");
  });

  it("drops aria-hidden on detail.select-chevron (accepted per the D-03 registry note)", () => {
    const svg = rendered(<Icon id="detail.select-chevron" className="h-3 w-3" />);
    expect(svg.hasAttribute("aria-hidden")).toBe(false);
  });
});
