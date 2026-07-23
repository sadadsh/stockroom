import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  AddPartIcon,
  BackIcon,
  BoardIcon,
  BuildIcon,
  CloseIcon,
  CubeArt,
  DoctorIcon,
  DownloadIcon,
  DuplicateIcon,
  EditIcon,
  EnrichIcon,
  ExternalIcon,
  FootprintArt,
  GitIcon,
  InfoIcon,
  LibraryIcon,
  ProjectsIcon,
  RefreshIcon,
  SearchIcon,
  SettingsIcon,
  SymbolArt,
  TrashIcon,
  UploadIcon,
  WarnIcon,
} from "./icons";
import { ICON_BY_ID } from "../lib/iconRegistry";

// Render-diff guard: the icons.tsx exports are now thin <Icon> wrappers, but each must still emit
// the exact svg its hand-written source did. We canonicalise the rendered DOM (attrs sorted + names
// lowered, the theme-var `style` attribute excluded because jsdom's CSSOM mangles var()) and compare
// it to the original markup parsed the same way. A match proves adoption changed no icon's output.
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

// The original svg markup for a representative slice: two primary icons (one with a className, one
// falling back to the default size), the sized bespoke line icons (including path-level caps and a
// filled sub-shape), and all three art glyphs (inner-group + root theme-var styling).
const CASES: Array<{ name: string; el: React.ReactElement; svg: string }> = [
  {
    name: "LibraryIcon (primary, explicit className)",
    el: <LibraryIcon className="h-4 w-4" />,
    svg:
      '<svg class="ico h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<rect x="3" y="4" width="7" height="16" rx="1"/><rect x="14" y="4" width="7" height="16" rx="1"/>' +
      '<path d="M6.5 8h0M6.5 12h0M17.5 8h0M17.5 12h0"/></svg>',
  },
  {
    name: "AddPartIcon (primary, default size)",
    el: <AddPartIcon />,
    svg:
      '<svg class="ico h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<path d="M12 5v14M5 12h14"/></svg>',
  },
  {
    name: "SearchIcon (bespoke)",
    el: <SearchIcon className="text-t3" />,
    svg:
      '<svg class="text-t3" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
      '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>',
  },
  {
    name: "UploadIcon (bespoke, weight 1.4)",
    el: <UploadIcon className="up" />,
    svg:
      '<svg class="up" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4">' +
      '<path d="M12 15V3m0 0L8 7m4-4l4 4"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>',
  },
  {
    name: "CloseIcon (bespoke, path-level cap)",
    el: <CloseIcon className="cl" />,
    svg:
      '<svg class="cl" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">' +
      '<path d="M6 6l12 12M18 6L6 18" stroke-linecap="round"/></svg>',
  },
  {
    name: "WarnIcon (bespoke, filled sub-shape)",
    el: <WarnIcon className="text-warn" />,
    svg:
      '<svg class="text-warn" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
      '<path d="M12 3.4l9.3 16.1H2.7z" stroke-linejoin="round"/><path d="M12 10v4.2" stroke-linecap="round"/>' +
      '<circle cx="12" cy="17.4" r="0.5" fill="currentColor" stroke="none"/></svg>',
  },
  {
    name: "ExternalIcon (bespoke, path-level caps)",
    el: <ExternalIcon className="ext" />,
    svg:
      '<svg class="ext" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
      '<path d="M14 4h6v6M20 4l-9 9M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  },
  {
    name: "SymbolArt (art, inner-group style)",
    el: <SymbolArt />,
    svg:
      '<svg viewBox="0 0 132 94" width="132" height="94">' +
      '<g style="stroke:var(--c-icon-line)" stroke-width="1.5" fill="none">' +
      '<rect x="40" y="20" width="52" height="54" rx="3"/>' +
      '<path d="M40 33H24M40 47H24M40 61H24M92 33h16M92 47h16M92 61h16"/></g></svg>',
  },
  {
    name: "FootprintArt (art, pads + edge rect)",
    el: <FootprintArt />,
    svg:
      '<svg viewBox="0 0 132 94" width="132" height="94">' +
      '<g style="fill:var(--c-icon-fill)">' +
      '<rect x="34" y="26" width="9" height="7" rx="1"/><rect x="48" y="26" width="9" height="7" rx="1"/>' +
      '<rect x="62" y="26" width="9" height="7" rx="1"/><rect x="76" y="26" width="9" height="7" rx="1"/>' +
      '<rect x="90" y="26" width="9" height="7" rx="1"/><rect x="34" y="61" width="9" height="7" rx="1"/>' +
      '<rect x="48" y="61" width="9" height="7" rx="1"/><rect x="62" y="61" width="9" height="7" rx="1"/>' +
      '<rect x="76" y="61" width="9" height="7" rx="1"/><rect x="90" y="61" width="9" height="7" rx="1"/></g>' +
      '<rect x="38" y="37" width="60" height="20" rx="2" fill="none" style="stroke:var(--c-icon-edge)" stroke-width="1.3"/></svg>',
  },
  {
    name: "CubeArt (art, root style)",
    el: <CubeArt />,
    svg:
      '<svg viewBox="0 0 90 90" width="70" height="70" fill="none" style="stroke:var(--c-icon-cube)" stroke-width="1.4">' +
      '<path d="M45 12l30 17v32L45 78 15 61V29z"/>' +
      '<path d="M45 12v18M45 30l30-17M45 30L15 13" opacity="0.5"/></svg>',
  },
];

describe("icons.tsx wrappers - render-diff", () => {
  for (const { name, el, svg } of CASES) {
    it(`matches the original svg: ${name}`, () => {
      expect(canonical(rendered(el))).toBe(canonical(original(svg)));
    });
  }
});

// Broad smoke over every one of the 24 named exports: each resolves to its registry entry and draws
// a single, non-empty svg with the right frame.
const ALL: Array<{ Comp: (p: { className?: string }) => React.ReactElement | null; id: string }> = [
  { Comp: SearchIcon, id: "action.search" },
  { Comp: WarnIcon, id: "status.warn" },
  { Comp: InfoIcon, id: "status.info" },
  { Comp: UploadIcon, id: "action.upload" },
  { Comp: CloseIcon, id: "action.close" },
  { Comp: BackIcon, id: "nav.back" },
  { Comp: ExternalIcon, id: "action.external" },
  { Comp: LibraryIcon, id: "nav.library" },
  { Comp: AddPartIcon, id: "action.add" },
  { Comp: DuplicateIcon, id: "action.duplicate" },
  { Comp: ProjectsIcon, id: "nav.projects.alt" },
  { Comp: DoctorIcon, id: "action.doctor" },
  { Comp: SettingsIcon, id: "action.settings" },
  { Comp: DownloadIcon, id: "action.download" },
  { Comp: BuildIcon, id: "action.build" },
  { Comp: RefreshIcon, id: "action.refresh" },
  { Comp: EditIcon, id: "action.edit" },
  { Comp: TrashIcon, id: "action.trash" },
  { Comp: EnrichIcon, id: "action.enrich" },
  { Comp: GitIcon, id: "action.git" },
  { Comp: BoardIcon, id: "nav.board" },
  { Comp: SymbolArt, id: "art.symbol" },
  { Comp: FootprintArt, id: "art.footprint" },
  { Comp: CubeArt, id: "art.model" },
];

describe("icons.tsx wrappers - coverage", () => {
  it("maps all 24 named exports to their registry ids", () => {
    expect(ALL).toHaveLength(24);
  });

  for (const { Comp, id } of ALL) {
    it(`renders one framed svg for ${id}`, () => {
      const svg = rendered(<Comp />);
      const entry = ICON_BY_ID.get(id);
      expect(entry, id).toBeDefined();
      expect(svg.getAttribute("viewBox")).toBe(entry?.viewBox);
      expect(svg.children.length).toBeGreaterThan(0);
      if (entry?.category === "primary") {
        expect(svg.classList.contains("ico")).toBe(true);
        expect(svg.getAttribute("stroke-width")).toBe(String(entry.strokeWidth));
      }
      if (typeof entry?.size === "number") {
        expect(svg.getAttribute("width")).toBe(String(entry.size));
      } else if (Array.isArray(entry?.size)) {
        expect(svg.getAttribute("width")).toBe(String(entry.size[0]));
        expect(svg.getAttribute("height")).toBe(String(entry.size[1]));
      }
    });
  }
});
